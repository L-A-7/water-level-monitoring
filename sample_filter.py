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

What this does instead -- gap segmentation, then pick the farthest tight run:

1. Sort the batch. Split it into runs wherever consecutive samples are more
   than GAP_THRESHOLD_CM apart. This is a single global rule over the whole
   sorted list, unlike a "seed" approach that starts from some small local
   window (e.g. the closest pair of points) and grows outward -- tried that
   first, but a real batch can have an exact-duplicate pair sitting *inside*
   the wrong (scattered) group, which a from-a-seed approach latches onto
   immediately with no way to recover.
2. Candidate runs need at least MIN_RUN_SIZE points (a lone point, or two,
   trivially look "tight" -- tight only means something once it's backed by
   enough points) and a std dev no larger than REJECT_STD_THRESHOLD_CM.
3. Of the candidates, take the FARTHEST one, not the tightest. Real data
   (2026-08..10) shows recurring "ghost" clusters at fixed distances
   (~57-59, 62, 71, 84, 96, 108cm) -- inflow stream/splash during rain, and
   something fixed in the tank at ~108cm even in calm weather. They can be
   tighter than, and outnumber, the true-surface cluster (e.g. 2026-09-29
   13:15 UTC: 9 pings at ~58cm vs 6 at ~146cm), so "tightest" or "largest"
   picks the ghost. But every ghost sits *above* the water -- nothing
   echoes from below the surface -- so the true surface is the farthest
   tight cluster whenever it's present at all.
4. Reject the reading if more than MAX_PINGS_BEYOND valid pings lie farther
   than the chosen run: the surface can't have a crowd of echoes behind it,
   so that means the true-surface cluster is missing from this batch and the
   chosen run is itself a ghost.

Known gap: a batch where the true surface is entirely absent and only a
ghost answers (e.g. all 30 pings at ~108cm, seen 2026-08-28) passes, since
nothing in a single batch distinguishes it. Catching that would need a
rate-of-change check against neighbouring readings, deliberately not done:
real storms can move the level >60cm/h.

Only used when a reading carries raw samples_cm (device.md's TEMPORARY
DEBUG_SEND_RAW_SAMPLES field) -- readings without it keep the device's own
on-device-filtered distance_cm/distance_std_cm, subject only to the same
REJECT_STD_THRESHOLD_CM check (see main.py).
"""

from schemas import SENTINEL_NO_ECHO

# How far apart two consecutive (sorted) samples can be before they're
# considered different clusters rather than jitter within the same one.
GAP_THRESHOLD_CM = 2.0

# Minimum points for a run to count as a cluster at all (see docstring, 2),
# capped at the batch size.
MIN_RUN_SIZE = 4

# Sensor's stated physical accuracy is ~0.3cm (device.md); a calm-water batch
# typically comes out well under 0.1cm. Raised from the sensor spec to allow
# for legitimately-noisier true clusters (observed during rain, ~1.1-1.2cm).
REJECT_STD_THRESHOLD_CM = 1.5

# More valid pings than this farther than the chosen run -> the chosen run
# isn't the surface (see docstring, 4).
MAX_PINGS_BEYOND = 3


def _std_dev(run: list[float]) -> float:
    if len(run) == 1:
        return 0.0
    mean = sum(run) / len(run)
    return (sum((x - mean) ** 2 for x in run) / len(run)) ** 0.5


def filter_samples(samples_cm: list[float]) -> tuple[float, float]:
    """Raw per-ping distances (may include the -1.00 no-echo sentinel) ->
    (distance_cm, distance_std_cm) of the farthest tight cluster found. Both
    are SENTINEL_NO_ECHO if no ping got a valid echo, if no run reaches
    MIN_RUN_SIZE with a std dev within REJECT_STD_THRESHOLD_CM, or if more
    than MAX_PINGS_BEYOND pings lie beyond the chosen run.
    """
    valid = sorted(s for s in samples_cm if s != SENTINEL_NO_ECHO)
    if not valid:
        return SENTINEL_NO_ECHO, SENTINEL_NO_ECHO

    runs = []
    current = [valid[0]]
    for x in valid[1:]:
        if x - current[-1] > GAP_THRESHOLD_CM:
            runs.append(current)
            current = []
        current.append(x)
    runs.append(current)

    # Capped by the batch size so a small configured avg_sample_count (down
    # to 1, see device.md) still yields readings.
    min_run_size = min(MIN_RUN_SIZE, len(samples_cm))
    candidates = [run for run in runs if len(run) >= min_run_size and _std_dev(run) <= REJECT_STD_THRESHOLD_CM]
    if not candidates:
        return SENTINEL_NO_ECHO, SENTINEL_NO_ECHO

    best_run = candidates[-1]  # runs are in ascending distance order
    if sum(1 for x in valid if x > best_run[-1]) > MAX_PINGS_BEYOND:
        return SENTINEL_NO_ECHO, SENTINEL_NO_ECHO

    distance_cm = sum(best_run) / len(best_run)
    return round(distance_cm, 2), round(_std_dev(best_run), 2)
