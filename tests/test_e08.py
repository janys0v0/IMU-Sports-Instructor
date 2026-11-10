"""E08: aligning a new day's OpenCap recording to the Watch clock."""

import numpy as np


def test_xcorr_lag_recovers_a_known_shift():
    from experiments.E08_new_day.align import norm, xcorr_lag

    rng = np.random.default_rng(0)
    watch = norm(np.convolve(rng.standard_normal(3000), np.ones(9) / 9, "same"))
    clip = watch[400:1400].copy()  # the clip starts 400 samples into the Watch recording
    k, c = xcorr_lag(watch, norm(clip))
    assert k == 400
    assert c.max() > 0.5
