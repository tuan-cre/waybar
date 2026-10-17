#include "fft.h"
#include <math.h>
#include <stdlib.h>

#define TWO_PI 6.2831853f
#define N 512
#define LOGN 9

static float hamming[N];
static int reversed[N];
static float roots_real[N / 2];
static float roots_imag[N / 2];
static int generated = 0;

static int bit_reverse(int x)
{
    int y = 0;
    for (int n = LOGN; n--;)
    {
        y = (y << 1) | (x & 1);
        x >>= 1;
    }
    return y;
}

static void generate_tables(void)
{
    if (generated) return;

    for (int n = 0; n < N; n++)
        hamming[n] = 1 - 0.85f * cosf(n * (TWO_PI / N));

    for (int n = 0; n < N; n++)
        reversed[n] = bit_reverse(n);

    for (int n = 0; n < N / 2; n++)
    {
        float angle = n * (TWO_PI / N);
        roots_real[n] = cosf(angle);
        roots_imag[n] = sinf(angle);
    }

    generated = 1;
}

static void do_fft(float a_real[N], float a_imag[N])
{
    int half = 1;
    int inv = N / 2;

    while (inv)
    {
        for (int g = 0; g < N; g += half << 1)
        {
            for (int b = 0, r = 0; b < half; b++, r += inv)
            {
                float rr = roots_real[r];
                float ri = roots_imag[r];
                float ar = a_real[g + half + b];
                float ai = a_imag[g + half + b];
                float odd_real = rr * ar - ri * ai;
                float odd_imag = rr * ai + ri * ar;

                float even_real = a_real[g + b];
                float even_imag = a_imag[g + b];

                a_real[g + b] = even_real + odd_real;
                a_imag[g + b] = even_imag + odd_imag;
                a_real[g + half + b] = even_real - odd_real;
                a_imag[g + half + b] = even_imag - odd_imag;
            }
        }

        half <<= 1;
        inv >>= 1;
    }
}

void calculate_spectrum(const float *pcm, float *freq_out)
{
    generate_tables();

    float a_real[N], a_imag[N];
    for (int i = 0; i < N; i++)
    {
        a_real[reversed[i]] = pcm[i] * hamming[i];
        a_imag[reversed[i]] = 0.0f;
    }

    do_fft(a_real, a_imag);

    for (int i = 0; i < N / 2 - 1; i++)
        freq_out[i] = 2.0f * sqrtf(a_real[1 + i] * a_real[1 + i] +
                                    a_imag[1 + i] * a_imag[1 + i]) / N;

    freq_out[N / 2 - 1] = sqrtf(a_real[N / 2] * a_real[N / 2] +
                                 a_imag[N / 2] * a_imag[N / 2]) / N;
}
