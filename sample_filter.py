"""Server-side replacement for the firmware's on-device outlier filter.

See device.md's "On-device outlier filter (median+3sigma)" section: the
device rejects samples more than 3 sigma from the median, but computes sigma
as the RMS deviation from the *mean of all samples, including the outliers
sigma is about to screen for* -- a couple of far-off echoes drag the mean
toward them and inflate sigma right along with it, which can let those same
outliers survive.

Median+3sigma (and MAD-based variants of it) also assume the true-surface
pings are the *majority* of the batch. That can be false: rain splashing can
produce enough scattered near-sensor echoes that they outnumber the
true-surface pings, which are still tightly clustered among themselves but
no longer the majority. No median-anchored filter can recover the right
answer in that case, by construction.

What this does instead -- gap segmentation, then pick the tightest run large
enough to trust:

1. Sort the batch. Split it into runs wherever consecutive samples are more
   than GAP_THRESHOLD_CM apart. This is a single global rule over the whole
   sorted list, unlike a "seed" approach that starts from some small local
   window (e.g. the closest pair of points) and grows outward -- tried that
   first, but a real batch can have an exact-duplicate pair sitting *inside*
   the wrong (scattered) group, which a from-a-seed approach latches onto
   immediately with no way to recover.
2. Drop any run smaller than MIN_RUN_FRACTION of the batch. Without this, a
   handful of scattered points that happen to land close together by chance
   (or worse, a single lone point, which trivially has zero spread since it
   can't disagree with itself) can look tighter than the true cluster simply
   because a small sample's std dev is a much noisier estimate than a large
   one's -- "tight" only means something once it's backed by enough points.
3. Of the runs that pass that bar, take the one with the lowest std dev.
4. Even that pick still gets rejected (treated as a real no-echo ping) if its
   std dev exceeds REJECT_STD_THRESHOLD_CM -- a last-resort sanity check for
   batches with no trustworthy cluster at all (e.g. no run reaches the
   minimum size, or every run that does is still implausibly noisy).

Only used when a reading carries raw samples_cm (device.md's TEMPORARY
DEBUG_SEND_RAW_SAMPLES field) -- readings without it keep the device's own
on-device-filtered distance_cm/distance_std_cm untouched.
"""

from schemas import SENTINEL_NO_ECHO

# How far apart two consecutive (sorted) samples can be before they're
# considered different clusters rather than jitter within the same one.
GAP_THRESHOLD_CM = 2.0

# A run must be at least this fraction of the batch (and at least
# MIN_RUN_SIZE_FLOOR points) to be a candidate "true" cluster -- otherwise a
# small coincidentally-tight scatter of bad points can out-score a larger,
# genuinely tight cluster on std dev alone (see module docstring, point 2).
MIN_RUN_FRACTION = 0.25
MIN_RUN_SIZE_FLOOR = 3

# Sensor's stated physical accuracy is ~0.3cm (device.md); a calm-water batch
# typically comes out well under 0.1cm. Raised from the sensor spec to allow
# for legitimately-noisier-but-correctly-identified clusters (observed during
# rain, the true cluster itself can run to ~1.1-1.2cm) while still rejecting
# a selected run with no real business being called "a reading".
REJECT_STD_THRESHOLD_CM = 1.5


def _std_dev(run: list[float]) -> float:
    if len(run) == 1:
        return 0.0
    mean = sum(run) / len(run)
    return (sum((x - mean) ** 2 for x in run) / len(run)) ** 0.5


def filter_samples(samples_cm: list[float]) -> tuple[float, float]:
    """Raw per-ping distances (may include the -1.00 no-echo sentinel) ->
    (distance_cm, distance_std_cm) of the tightest sufficiently-large cluster
    found. Both are SENTINEL_NO_ECHO if no ping in the batch got a valid
    echo, if no cluster reaches MIN_RUN_FRACTION of the batch, or if the best
    candidate's std dev still exceeds REJECT_STD_THRESHOLD_CM.
    """
    valid = [s for s in samples_cm if s != SENTINEL_NO_ECHO]
    if not valid:
        return SENTINEL_NO_ECHO, SENTINEL_NO_ECHO
    if len(valid) == 1:
        return round(valid[0], 2), 0.0

    sorted_samples = sorted(valid)
    n = len(sorted_samples)

    runs = []
    current = [sorted_samples[0]]
    for i in range(1, n):
        if sorted_samples[i] - sorted_samples[i - 1] > GAP_THRESHOLD_CM:
            runs.append(current)
            current = []
        current.append(sorted_samples[i])
    runs.append(current)

    min_run_size = max(MIN_RUN_SIZE_FLOOR, round(MIN_RUN_FRACTION * n))
    candidates = [run for run in runs if len(run) >= min_run_size]
    if not candidates:
        return SENTINEL_NO_ECHO, SENTINEL_NO_ECHO

    best_run = min(candidates, key=_std_dev)
    distance_cm = sum(best_run) / len(best_run)
    distance_std_cm = _std_dev(best_run)

    if distance_std_cm > REJECT_STD_THRESHOLD_CM:
        return SENTINEL_NO_ECHO, SENTINEL_NO_ECHO

    return round(distance_cm, 2), round(distance_std_cm, 2)
