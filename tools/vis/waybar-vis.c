#include <pipewire/pipewire.h>
#include <spa/param/audio/format-utils.h>
#include <spa/param/audio/raw.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <signal.h>
#include <stdatomic.h>
#include <time.h>
#include <unistd.h>

#include "fft.h"

#define N_SAMPLES 512
#define N_BINS    256
#define RING_SIZE 8192
#define RING_MASK (RING_SIZE - 1)

#define MIN_DBFS -60.0f
#define SMOOTH_DECAY  0.82f

#define MAX_SINKS      32
#define VERSION "0.2.0"

static struct pw_main_loop *main_loop = NULL;
static struct pw_core *core = NULL;
static struct pw_stream *stream = NULL;
static struct spa_source *timer_src = NULL;
static struct spa_hook stream_listener;
static struct pw_loop *loop = NULL;
static int timer_hz = 0;

/* 0Hz idle: watch playback streams, capture only while audio plays.
 * (Triggering on sink state would self-trigger: our own monitor
 * keeps the sink RUNNING. Our capture is Stream/Input, never Output.) */
struct sink_watch {
    struct pw_node *node;
    struct spa_hook listener;
    uint32_t id;
    int running;
};
static struct sink_watch watches[MAX_SINKS];
static int n_watches = 0;
static struct pw_registry *registry = NULL;
static struct spa_hook registry_listener;
static struct spa_hook core_listener;
static int capture_on = 0;
static int sync_seq = 0;

static float ring_buf[RING_SIZE];
static atomic_uint write_pos;
static atomic_uint read_pos;

static float *smoothed = NULL;
static float xscale[65];
static char last_out[320] = "";
static int have_last = 0;
static int n_bands = 16;
static int refresh_rate = 30;
static float silence_thresh = 0.08f;
static float sensitivity = 1.0f;
static float decay = 0.995f;

static int running = 1;
static int hidden = 1;
static float peak_max = 1.0f;
static const char *css_class = "vis";
static char json_class[64];

static int escape_json(char *dst, size_t size, const char *src)
{
    size_t len = 0;
    for (const unsigned char *p = (const unsigned char *)src; *p; p++)
    {
        if (*p == '"' || *p == '\\')
        {
            if (len + 2 >= size) return -1;
            dst[len++] = '\\';
            dst[len++] = *p;
        }
        else if (*p < 0x20)
        {
            if (len + 6 >= size) return -1;
            len += (size_t)snprintf(dst + len, size - len, "\\u%04x", *p);
        }
        else
        {
            if (len + 1 >= size) return -1;
            dst[len++] = *p;
        }
    }
    dst[len] = '\0';
    return 0;
}

static void sighandler(int sig)
{
    (void)sig;
    running = 0;
    if (main_loop)
        pw_main_loop_quit(main_loop);
}

static void compute_bands(const float *freq, float *bands, int n)
{
    for (int b = 0; b < n; b++)
    {
        float low = xscale[b];
        float high = xscale[b + 1];
        int a = (int)ceilf(low);
        int b2 = (int)floorf(high);
        float val = 0.0f;

        if (b2 < a)
        {
            int idx = b2;
            if (idx >= 0 && idx < N_BINS)
                val = freq[idx] * (high - low);
        }
        else
        {
            if (a > 0 && a - 1 < N_BINS)
                val += freq[a - 1] * (a - low);
            for (int k = a; k < b2 && k < N_BINS; k++)
                val += freq[k];
            if (b2 < N_BINS)
                val += freq[b2] * (high - b2);
        }

        val *= (float)n / 12.0f;
        float db = 20.0f * log10f(val + 1e-10f);
        float norm = (db - MIN_DBFS) / (-MIN_DBFS);
        if (norm < 0.0f) norm = 0.0f;
        if (norm > 1.0f) norm = 1.0f;
        bands[b] = norm;
    }
}

static void on_process(void *userdata)
{
    (void)userdata;
    struct pw_buffer *b = pw_stream_dequeue_buffer(stream);
    if (!b) return;

    struct spa_buffer *spa_buf = b->buffer;
    struct spa_data *d = &spa_buf->datas[0];

    if (d->data && d->chunk && d->chunk->offset <= d->maxsize &&
        d->chunk->size <= d->maxsize - d->chunk->offset)
    {
        const uint8_t *samples = (const uint8_t *)d->data + d->chunk->offset;
        int stride = d->chunk->stride >= (int32_t)sizeof(float)
                   ? d->chunk->stride : (int)sizeof(float);
        unsigned n = d->chunk->size / (unsigned)stride;
        unsigned wp = atomic_load_explicit(&write_pos, memory_order_relaxed);
        unsigned rp = atomic_load_explicit(&read_pos, memory_order_acquire);
        for (unsigned i = 0; i < n && wp - rp < RING_SIZE - 1; i++)
        {
            memcpy(&ring_buf[wp & RING_MASK], samples + (size_t)i * stride,
                   sizeof(float));
            wp++;
        }
        atomic_store_explicit(&write_pos, wp, memory_order_release);
    }

    pw_stream_queue_buffer(stream, b);
}

static void set_timer_hz(int hz)
{
    /* re-arming from inside the timer callback is safe in pipewire */
    if (hz == timer_hz || !loop || !timer_src)
        return;
    timer_hz = hz;
    struct timespec ts = { hz <= 1 ? 1 : 0, hz <= 1 ? 0 : 1000000000 / hz };
    pw_loop_update_timer(loop, timer_src, &ts, &ts, false);
}

static void on_timer(void *userdata, uint64_t expirations)
{
    (void)userdata;
    (void)expirations;
    unsigned wp = atomic_load_explicit(&write_pos, memory_order_acquire);
    unsigned rp = atomic_load_explicit(&read_pos, memory_order_relaxed);
    unsigned avail = wp - rp;

    /* starved: sink suspended, node watcher tears capture down shortly */
    if (avail < N_SAMPLES)
        return;

    rp = wp - N_SAMPLES;
    float pcm[N_SAMPLES];
    for (unsigned i = 0; i < N_SAMPLES; i++)
        pcm[i] = ring_buf[(rp + i) & RING_MASK];
    atomic_store_explicit(&read_pos, rp + N_SAMPLES, memory_order_release);

    float freq[N_BINS];
    calculate_spectrum(pcm, freq);

    float raw[n_bands];
    compute_bands(freq, raw, n_bands);

    float peak = 0.0f;
    static const char *blocks[] = {
        "\xe2\x96\x81", "\xe2\x96\x82", "\xe2\x96\x83", "\xe2\x96\x84",
        "\xe2\x96\x85", "\xe2\x96\x86", "\xe2\x96\x87", "\xe2\x96\x88"
    };

    char text[193];
    int pos = 0;
    for (int i = 0; i < n_bands; i++)
    {
        if (raw[i] > smoothed[i])
            smoothed[i] = raw[i];
        else
            smoothed[i] = smoothed[i] * SMOOTH_DECAY +
                          raw[i] * (1.0f - SMOOTH_DECAY);

        if (smoothed[i] > peak) peak = smoothed[i];
        int level = (int)(smoothed[i] / peak_max * 8.0f * sensitivity);
        if (level < 0) level = 0;
        if (level > 7) level = 7;
        pos += snprintf(text + pos, sizeof(text) - pos, "%s", blocks[level]);
    }

    if (peak < silence_thresh) {
        /* snap bars to zero: no droop through low blocks before hiding */
        memset(smoothed, 0, (size_t)n_bands * sizeof(float));
        hidden = 1;
    } else
        hidden = 0;

    if (peak > peak_max)
        peak_max = peak;
    else
        peak_max *= decay;

    if (peak_max < 0.01f) peak_max = 0.01f;

    char out[320];
    if (hidden)
    {
        snprintf(out, sizeof(out), "{\"text\":\"\",\"class\":\"hidden\"}\n");
    }
    else
    {
        snprintf(out, sizeof(out),
                 "{\"text\":\"%s\",\"class\":\"%s\",\"tooltip\":\"Spectrum %d bands\"}\n",
                 text, json_class, n_bands);
    }
    /* steady audio/silence: don't force waybar to re-render identical frames */
    if (!have_last || strcmp(out, last_out) != 0)
    {
        fputs(out, stdout);
        fflush(stdout);
        memcpy(last_out, out, strlen(out) + 1);
        have_last = 1;
    }
}

static void on_state_changed(void *userdata, enum pw_stream_state old,
                             enum pw_stream_state state, const char *error)
{
    (void)userdata;
    (void)old;
    if (state == PW_STREAM_STATE_ERROR)
    {
        fprintf(stderr, "stream error: %s\n", error ? error : "unknown");
        pw_main_loop_quit(main_loop);
    }
}

static void start_capture(void);
static void stop_capture(void);

static void reevaluate(void)
{
    int any = 0;
    for (int i = 0; i < n_watches; i++)
    {
        if (watches[i].running)
        {
            any = 1;
            break;
        }
    }
    if (any && !capture_on)
        start_capture();
    else if (!any && capture_on)
        stop_capture();
}

static void node_info_cb(void *data, const struct pw_node_info *info)
{
    struct sink_watch *w = (struct sink_watch *)data;
    int r = (info && info->state == PW_NODE_STATE_RUNNING);
    if (r != w->running)
    {
        w->running = r;
        reevaluate();
    }
}

static const struct pw_node_events node_events = {
    PW_VERSION_NODE_EVENTS,
    .info = node_info_cb,
};

static void registry_global_cb(void *data, uint32_t id, uint32_t permissions,
                               const char *type, uint32_t version,
                               const struct spa_dict *props)
{
    (void)data;
    (void)permissions;
    (void)version;
    if (strcmp(type, PW_TYPE_INTERFACE_Node) != 0)
        return;
    const char *cls = props ? spa_dict_lookup(props, PW_KEY_MEDIA_CLASS) : NULL;
    if (!cls || strcmp(cls, "Stream/Output/Audio") != 0)
        return;
    if (n_watches >= MAX_SINKS)
        return;
    struct pw_node *n = (struct pw_node *)pw_registry_bind(registry, id, type,
                                                        PW_VERSION_NODE, 0);
    if (!n)
        return;
    struct sink_watch *w = &watches[n_watches++];
    w->node = n;
    w->id = id;
    w->running = 0;
    pw_node_add_listener(n, &w->listener, &node_events, w);
}

static void registry_remove_cb(void *data, uint32_t id)
{
    (void)data;
    for (int i = 0; i < n_watches; i++)
    {
        if (watches[i].id != id)
            continue;
        spa_hook_remove(&watches[i].listener);
        pw_proxy_destroy((struct pw_proxy *)watches[i].node);
        watches[i] = watches[--n_watches];
        reevaluate();
        return;
    }
}

static const struct pw_registry_events registry_events = {
    PW_VERSION_REGISTRY_EVENTS,
    .global = registry_global_cb,
    .global_remove = registry_remove_cb,
};

static void core_done_cb(void *data, uint32_t id, int seq)
{
    (void)data;
    (void)id;
    /* initial registry dump has arrived: evaluate startup state */
    if (seq == sync_seq)
        reevaluate();
}

static const struct pw_core_events core_events = {
    PW_VERSION_CORE_EVENTS,
    .done = core_done_cb,
};

static void start_capture(void)
{
    struct pw_properties *props = pw_properties_new(
        PW_KEY_NODE_NAME, "waybar-vis",
        PW_KEY_MEDIA_TYPE, "Audio",
        PW_KEY_MEDIA_CATEGORY, "Capture",
        PW_KEY_MEDIA_ROLE, "DSP",
        PW_KEY_STREAM_CAPTURE_SINK, "true",
        NULL
    );

    stream = pw_stream_new(core, "waybar-vis", props);
    if (!stream)
    {
        fprintf(stderr, "failed to create stream\n");
        return;
    }

    static const struct pw_stream_events events = {
        PW_VERSION_STREAM_EVENTS,
        .process = on_process,
        .state_changed = on_state_changed,
    };
    pw_stream_add_listener(stream, &stream_listener, &events, NULL);

    uint8_t params_buffer[1024];
    struct spa_pod_builder b = SPA_POD_BUILDER_INIT(params_buffer, sizeof(params_buffer));
    const struct spa_pod *params[1];
    params[0] = spa_format_audio_raw_build(&b, SPA_PARAM_EnumFormat,
        &SPA_AUDIO_INFO_RAW_INIT(
            .format = SPA_AUDIO_FORMAT_F32,
            .channels = 1,
            .rate = 44100
        ));

    if (pw_stream_connect(stream, PW_DIRECTION_INPUT, PW_ID_ANY,
            PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS,
            params, 1) < 0)
    {
        fprintf(stderr, "failed to connect stream\n");
        spa_hook_remove(&stream_listener);
        pw_stream_destroy(stream);
        stream = NULL;
        return;
    }

    timer_src = pw_loop_add_timer(loop, on_timer, NULL);
    if (!timer_src)
    {
        fprintf(stderr, "failed to create timer\n");
        spa_hook_remove(&stream_listener);
        pw_stream_destroy(stream);
        stream = NULL;
        return;
    }

    /* drop stale ring data so resume starts clean */
    atomic_store_explicit(&read_pos,
                          atomic_load_explicit(&write_pos, memory_order_acquire),
                          memory_order_release);
    hidden = 0;
    memset(smoothed, 0, (size_t)n_bands * sizeof(float));
    set_timer_hz(refresh_rate);
    capture_on = 1;
}

static void stop_capture(void)
{
    capture_on = 0;
    if (timer_src)
    {
        pw_loop_destroy_source(loop, timer_src);
        timer_src = NULL;
    }
    timer_hz = 0;
    if (stream)
    {
        spa_hook_remove(&stream_listener);
        pw_stream_destroy(stream);
        stream = NULL;
    }
    /* waybar would otherwise freeze on the last bars */
    printf("{\"text\":\"\",\"class\":\"hidden\"}\n");
    fflush(stdout);
}

int main(int argc, char *argv[])
{
    for (int i = 1; i < argc; i++)
    {
        if (strcmp(argv[i], "-b") == 0 && i + 1 < argc)
            n_bands = atoi(argv[++i]);
        else if (strcmp(argv[i], "-r") == 0 && i + 1 < argc)
            refresh_rate = atoi(argv[++i]);
        else if (strcmp(argv[i], "-t") == 0 && i + 1 < argc)
            silence_thresh = atof(argv[++i]);
        else if (strcmp(argv[i], "-d") == 0 && i + 1 < argc)
            decay = atof(argv[++i]);
        else if (strcmp(argv[i], "-s") == 0 && i + 1 < argc)
            sensitivity = atof(argv[++i]);
        else if (strcmp(argv[i], "-c") == 0 && i + 1 < argc)
            css_class = argv[++i];
        else if (strcmp(argv[i], "--version") == 0)
        {
            printf("waybar-vis version %s\n", VERSION);
            return 0;
        }
        else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0)
        {
            printf("usage: waybar-vis [-b bands] [-r rate] [-t threshold]\n");
            printf("       [-d decay] [-s sensitivity] [-c class] [--version]\n");
            printf("  -b        number of bands (4-64, default 16)\n");
            printf("  -r        refresh rate in Hz (10-60, default 30)\n");
            printf("  -t        silence threshold (default 0.08)\n");
            printf("  -d        peak decay rate (default 0.995, higher = smoother)\n");
            printf("  -s        sensitivity multiplier (default 1.0, lower = less reactive)\n");
            printf("  -c        CSS class for Waybar (default \"vis\")\n");
            printf("  --version print version and exit\n");
            return 0;
        }
    }

    if (n_bands < 4) n_bands = 4;
    if (n_bands > 64) n_bands = 64;
    if (refresh_rate < 10) refresh_rate = 10;
    if (refresh_rate > 60) refresh_rate = 60;
    if (escape_json(json_class, sizeof(json_class), css_class) < 0)
    {
        fprintf(stderr, "CSS class is too long\n");
        return 1;
    }

    for (int i = 0; i <= n_bands; i++)
        xscale[i] = powf(256.0f, (float)i / n_bands) - 0.5f;

    smoothed = calloc(n_bands, sizeof(float));
    if (!smoothed) return 1;
    signal(SIGINT, sighandler);
    signal(SIGTERM, sighandler);
    signal(SIGPIPE, SIG_IGN);

    pw_init(&argc, &argv);

    main_loop = pw_main_loop_new(NULL);
    if (!main_loop) { fprintf(stderr, "failed to create main loop\n"); return 1; }

    struct pw_loop *main_pw_loop = pw_main_loop_get_loop(main_loop);
    loop = main_pw_loop;
    struct pw_context *context = pw_context_new(main_pw_loop, NULL, 0);
    if (!context) { fprintf(stderr, "failed to create context\n"); return 1; }

    core = pw_context_connect(context, NULL, 0);
    if (!core) { fprintf(stderr, "failed to connect core\n"); return 1; }

    pw_core_add_listener(core, &core_listener, &core_events, NULL);

    registry = pw_core_get_registry(core, PW_VERSION_REGISTRY, 0);
    if (!registry) { fprintf(stderr, "failed to get registry\n"); return 1; }
    pw_registry_add_listener(registry, &registry_listener, &registry_events, NULL);

    /* round-trip: initial sink dump arrives before this completes */
    sync_seq = pw_core_sync(core, PW_ID_CORE, 0);

    /* waybar gets a state immediately instead of waiting for audio */
    printf("{\"text\":\"\",\"class\":\"hidden\"}\n");
    fflush(stdout);

    pw_main_loop_run(main_loop);

    if (capture_on)
        stop_capture();
    for (int i = 0; i < n_watches; i++)
    {
        spa_hook_remove(&watches[i].listener);
        pw_proxy_destroy((struct pw_proxy *)watches[i].node);
    }
    n_watches = 0;
    spa_hook_remove(&registry_listener);
    pw_proxy_destroy((struct pw_proxy *)registry);
    spa_hook_remove(&core_listener);
    pw_core_disconnect(core);
    pw_context_destroy(context);
    pw_main_loop_destroy(main_loop);
    pw_deinit();
    free(smoothed);

    return 0;
}
