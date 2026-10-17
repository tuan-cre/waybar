#include "fft.h"
#include <assert.h>
#include <math.h>

int main(void)
{
    float pcm[512] = {0};
    float spectrum[256];

    calculate_spectrum(pcm, spectrum);
    for (int i = 0; i < 256; i++)
        assert(spectrum[i] == 0.0f);

    for (int i = 0; i < 512; i++)
        pcm[i] = sinf(2.0f * 3.14159265f * 16 * i / 512);
    calculate_spectrum(pcm, spectrum);
    assert(spectrum[15] > spectrum[14]);
    assert(spectrum[15] > spectrum[16]);
    return 0;
}
