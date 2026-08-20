"""Server-side replacement for the firmware's on-device outlier filter.

See device.md's "On-device outlier filter (median+3sigma)" section: the
device rejects samples more than 3 sigma from the median, but computes sigma
as the RMS deviation from the *mean of all samples, including the outliers
sigma is about to screen for* -- a couple of far-off echoes drag the mean
toward them and inflate sigma right along with it, which can let those same
outliers survive. This reimplements the same median+3sigma structure but
with sigma estimated via MAD (median absolute deviation from the median),
which isn't dragged around by the outliers it's measuring.

Only used when a reading carries raw samples_cm (device.md's TEMPORARY
DEBUG_SEND_RAW_SAMPLES field) -- readings without it keep the device's own
on-device-filtered distance_cm/distance_std_cm untouched.
"""

from schemas import SENTINEL_NO_ECHO

# Standard consistency constant that scales MAD to be comparable to a normal
# distribution's standard deviation (1 / Phi^-1(3/4)), so the same "3 sigma"
# window width from the device's algorithm still means the same thing here.
MAD_TO_SIGMA = 1.4826
OUTLIER_SIGMA_MULT = 3.0


def filter_samples(samples_cm: list[float]) -> tuple[float, float]:
    """Raw per-ping distances (may include the -1.00 no-echo sentinel) ->
    (distance_cm, distance_std_cm), both SENTINEL_NO_ECHO if no ping in the
    batch got a valid echo.
    """
    valid = [s for s in samples_cm if s != SENTINEL_NO_ECHO]
    if not valid:
        return SENTINEL_NO_ECHO, SENTINEL_NO_ECHO
    if len(valid) == 1:
        return round(valid[0], 2), 0.0

    sorted_samples = sorted(valid)
    median = sorted_samples[len(sorted_samples) // 2]  # matches device's sorted[n/2]

    abs_deviations = sorted(abs(x - median) for x in valid)
    mad = abs_deviations[len(abs_deviations) // 2]
    sigma = MAD_TO_SIGMA * mad

    if sigma == 0:
        # More than half the samples exactly match the median -- no spread
        # to measure, so nothing to reject rather than a zero-width window.
        kept = valid
    else:
        kept = [x for x in valid if abs(x - median) <= OUTLIER_SIGMA_MULT * sigma]
        if not kept:
            kept = [median]  # mirrors the firmware's fallback, shouldn't happen in practice

    distance_cm = sum(kept) / len(kept)
    if len(kept) > 1:
        distance_std_cm = (sum((x - distance_cm) ** 2 for x in kept) / len(kept)) ** 0.5
    else:
        distance_std_cm = 0.0

    return round(distance_cm, 2), round(distance_std_cm, 2)
