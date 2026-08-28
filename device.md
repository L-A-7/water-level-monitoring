# Device API Contract — Water Tank Level Monitor

Firmware: XIAO ESP32C6 + HC-SR04 ultrasonic sensor, battery powered, deep-sleep
between wakes. This document is self-contained — it describes device behavior,
not firmware source (the firmware lives in a separate repo).

## Transport

- HTTPS POST, one request per wake cycle.
- `Content-Type: application/json`.
- Device validates the server's TLS certificate against the standard CA
  bundle (mbedTLS default bundle) — the server needs a properly chain-signed
  cert (e.g. Let's Encrypt). Self-signed certs will fail the handshake.
- Any HTTP status outside 200-299 is treated as failure by the device: the
  measurement is queued locally and retried on a future wake (see Retry
  semantics below). The response body is only parsed on 2xx.
- Request timeout on the device side is 8s.

## Known gaps (not yet implemented on the device)

- **No device identifier or auth.** The request carries no device ID, API
  key, or token. Fine for a single-device v1; if the server will ever need
  to support multiple devices or basic auth, that's a firmware change, not
  just a server one — flag it early if it matters.
- **No tank calibration on-device.** `distance_cm` is raw sensor-to-surface
  distance, not a fill level or volume. Converting to level%/liters (sensor
  mounting height, empty/full distances, tank geometry) is entirely a server
  concern.

## Request body (device → server)

```json
{
  "config": {
    "wakeup_period_min": 15,
    "avg_sample_count": 30
  },
  "rssi": -66,
  "readings": [
    {"distance_cm": 50.50, "distance_std_cm": 0.31, "battery_mv": 4200, "chip_temp_c": 34.12},
    {"distance_cm": 50.60, "distance_std_cm": 0.28, "battery_mv": 4195, "chip_temp_c": 34.05},
    {"distance_cm": 50.47, "distance_std_cm": 0.35, "battery_mv": 4223, "chip_temp_c": 33.98}
  ]
}
```

**New fields as of this update: `readings[].chip_temp_c` and
`readings[].distance_std_cm`.** If the server's request schema rejects unknown
fields, these need to be accepted (or at least tolerated) *before* the
corresponding firmware ships, or every POST will 422 and — per the Retry
semantics below — permanently wedge the device's backlog, since a rejected
batch is never acknowledged/cleared.

**TEMPORARY diagnostic field, now flashed to the real device (2026-08-20):
`readings[].samples_cm`.** Gated behind `DEBUG_SEND_RAW_SAMPLES` in the
firmware's `config.h` — currently `1`. The *last* entry in `readings` (the
current wake, never a backlog entry) carries an extra array of the fully
raw, pre-outlier-rejection HC-SR04 samples for that wake — e.g.
`"samples_cm": [50.52, 50.48, -1.00, 50.55, ...]`, always exactly
`avg_sample_count` values long: one entry per attempted ping, in order,
nothing dropped. A ping whose echo timed out or was out of range shows up as
`-1.00` (the same sentinel `distance_cm` uses) rather than being omitted —
so a burst of failed pings is visible in the data, not silently invisible.
This exists to let raw sample distributions be studied offline to design a
better outlier filter — it's meant to be flipped off again afterward.

The server now does more than tolerate this field: whenever `samples_cm` is
present on a reading, the server re-runs outlier rejection itself and that
server-computed `distance_cm`/`distance_std_cm` — not the device's own
on-device-filtered values in the same reading — becomes the value that's
stored and charted. The device's own `distance_cm`/`distance_std_cm` are
still sent and still used as-is for any reading without `samples_cm` (all
backlog entries, and the current reading whenever `DEBUG_SEND_RAW_SAMPLES`
is off). Raw samples are also persisted (not just logged) so they can be
browsed per-reading from the admin page.

**Rain can beat the "majority of samples are good" assumption.** Any
median-anchored filter (including the device's own median+3sigma) assumes
the true-surface pings are the majority of the batch. Observed in the
field: rain splashing against the tank surface can produce enough scattered
near-sensor echoes that they outnumber the true-surface pings within a
single wake's batch, even though the true-surface pings are still tightly
clustered among themselves — sometimes as little as a quarter of the batch.
A median-anchored filter converges on the scattered majority instead and
has no way to recover, by construction.

The server's filter (`sample_filter.py`) instead works by density, not
majority: sort the batch, split it into runs wherever consecutive samples
are more than 2cm apart, discard any run smaller than 25% of the batch (a
small run can look deceptively tight purely because a small sample's std
dev is a noisy estimate — even a single lone point has "zero" spread), and
take whichever remaining run has the lowest std dev. An earlier design
seeded from the single closest pair of points and grew outward from there,
but real batches can have an exact-duplicate pair sitting inside the wrong
(scattered) group, which a seed-based approach latches onto immediately
with no way to recover — the run-based approach doesn't have that failure
mode since the split is a single global rule over the whole sorted batch,
not a local pick. Even the winning run still gets discarded (stored as the
same sentinel as a real no-echo ping) if its std dev exceeds 1.5cm — a
last-resort check for batches with no trustworthy cluster at all. The raw
`samples_cm` are persisted and browsable either way, so nothing about a
rejected reading is actually lost, only its derived distance/level.

| Field | Type | Notes |
|---|---|---|
| `config.wakeup_period_min` | uint, minutes | Device's *current* wake interval (echoes back what it's running, doesn't necessarily match what you last told it — see Response below). |
| `config.avg_sample_count` | uint | Device's current HC-SR04 sample count (median+3σ-filtered mean per wake). |
| `rssi` | int, dBm | WiFi signal strength of *this* connection only. Not present per-reading — there's no historical RSSI for backlog entries (no WiFi = no RSSI at the time they were queued). |
| `readings` | array | Oldest first, **current reading is always last**. Array has 1 entry in the normal case; more than 1 when flushing a backlog after a WiFi outage (queue holds up to 192 entries / 48h at 15-min sampling, ring-buffer overwrite-oldest if exceeded). |
| `readings[].distance_cm` | float, 2 decimals | Raw sensor distance. **Sentinel value `-1.00` means the HC-SR04 got no valid echo that wake** — filter/flag these, don't treat as a literal reading. |
| `readings[].distance_std_cm` | float, 2 decimals | RMS deviation from the mean across the `avg_sample_count` HC-SR04 readings taken that wake, computed after the same median+3σ outlier rejection used for `distance_cm` (so it reflects the spread of the samples actually averaged in, not the raw noise floor). Sensor's physical accuracy is ~0.3cm, so values well below that reflect measurement consistency, not calibrated precision. **Shares `distance_cm`'s sentinel: `-1.00` whenever `distance_cm` is `-1.00`** (no echo / implausible range that wake) — treat both fields as sentinel together. |
| `readings[].battery_mv` | int | Battery voltage in mV (~3000-4200 for the single-cell LiPo in use). |
| `readings[].chip_temp_c` | float, 2 decimals | ESP32-C6's internal **die/package temperature, not ambient** — self-heating from WiFi TX and CPU load typically reads several °C above actual ambient air/water temperature. Diagnostic/device-health signal only; not a substitute for a real ambient sensor. **Sentinel value `-999.00` means the on-chip sensor read failed** that wake (out of its configured -10..80°C range, or a driver error) — filter/flag these like the distance sentinel. |
| `readings[].samples_cm` | array of float, 2 decimals | **TEMPORARY, diagnostic-only** (see note above) — only present on the current-wake reading, never on backlog entries, and only when the firmware's `DEBUG_SEND_RAW_SAMPLES` is enabled. Fully raw per-ping distances, before outlier rejection/averaging, one entry per attempted ping (`avg_sample_count` long) with no drops — failed pings (no echo / out of range) appear as `-1.00`, the same sentinel `distance_cm` uses. |

### On-device outlier filter (median+3σ)

This is the filter that turns `samples_cm` (raw, one entry per attempted
ping) into `distance_cm`/`distance_std_cm` (one filtered value per wake). It
runs on-device, once per wake, over that wake's `avg_sample_count` pings —
`config.avg_sample_count`/`n` below is that same value. Documented here
because **it's the baseline the raw `samples_cm` data needs to be compared
against**: it's still letting some false points through in the field, which
is the whole reason `samples_cm` exists — to study *why*, from the actual
raw distributions, and design something that catches what this doesn't.
Exact algorithm (`hcsr04_filter_samples()` in the firmware):

1. Take the `n` raw per-ping distances (echo-timeout/out-of-range pings are
   never handed to this step at all — they're excluded upstream, not by this
   filter; see the `samples_cm` sentinel note above for how those show up in
   the raw array).
2. `median` = the middle element of the sorted samples (`sorted[n/2]`; for
   even `n` this is the upper of the two middle values, not their average).
3. `mean` = arithmetic mean of **all** `n` samples (not median-centered, no
   rejection applied yet).
4. `sigma` = RMS deviation from that `mean`, across all `n` samples:
   `sqrt(sum((x_i - mean)^2) / n)`.
5. Keep every sample within `3 * sigma` of the `median`; reject the rest.
6. `distance_cm` = mean of the kept samples (falls back to `median` if
   somehow none survive).
7. `distance_std_cm` = RMS deviation of the kept samples from `distance_cm`
   (0 if fewer than 2 survive).

**Why this still lets false points through** — the load-bearing weakness is
step 4: `sigma` is computed from the *mean of all samples, including the
outliers step 5 is about to screen for*. Mean and this kind of sigma are not
robust statistics — a couple of far-off echoes (e.g. a multipath/second
reflection off the tank wall, foam, or a ripple) drag the mean toward them
and, worse, inflate `sigma` right along with it. Since the acceptance window
is `3 * sigma` wide, an inflated `sigma` can be enough to let those same
outliers (or others) fall inside the window and survive — the points most
responsible for corrupting the threshold are exactly the ones the threshold
was supposed to catch. This gets worse the more outliers cluster together
in a single wake (two similar bad echoes reinforce each other) and the
smaller `n` is (at the field default `n=30`, one or two bad points have
outsized leverage on `sigma`). A scale estimate that isn't dragged around by
the outliers it's measuring — e.g. MAD, median absolute deviation from the
median, instead of RMS-from-mean — doesn't have this self-defeating
property, and is one direction worth evaluating against the raw
`samples_cm` data. Also note the sensor's stated physical accuracy is
~0.3cm (see `distance_std_cm` above): a low `distance_std_cm` on a given
wake means the surviving samples agree with each other, not that they agree
with reality — it's not proof an outlier didn't survive rejection.

### Timestamp reconstruction

The device does not send timestamps (no on-device RTC/NTP by design choice —
see rationale below). Readings are spaced exactly `config.wakeup_period_min` apart,
since the device pushes to the queue once per wake regardless of success.
Reconstruct each reading's approximate time by counting backward from
request-receipt time:

```
reading[i].time ≈ receipt_time - (len(readings) - 1 - i) * wakeup_period_min minutes
```

Caveat: this drifts if `wakeup_period_min` changed partway through an outage (rare,
acceptable approximation — not worth on-device NTP complexity for this).

## Response body (server → device) — config sync

Optional. If you want to push new settings to the device, respond with:

```json
{"wakeup_period_min": 20, "avg_sample_count": 25}
```

**Critical formatting constraint:** the device's response parser is
intentionally minimal — a plain substring search for `"wakeup_period_min"` and
`"avg_sample_count"` anywhere in the response text, not a full JSON parser.
**Do not echo the request body, wrap the values in a nested object, or
include these key names anywhere else in the response** (logging fields,
debug echoes, etc.) — any occurrence will be picked up and misapplied. Keep
the response body to just these two flat keys (both optional; include only
the ones you want to change). Anything else in the response is ignored.

Validation (enforced device-side, silently — the server gets no rejection
feedback, only a device-side log line):

| Field | Range | Out-of-range behavior |
|---|---|---|
| `wakeup_period_min` | 1 – 1440 (24h) | Ignored, device keeps its current value |
| `avg_sample_count` | 1 – 100 | Ignored, device keeps its current value (matches the device's actual hard sampling cap, for battery/timing reasons) |

Each field is validated and applied independently — a valid `wakeup_period_min`
with an invalid `avg_sample_count` still applies the `wakeup_period_min` change.

## Retry / failure semantics

- Failed POST (network error, non-2xx, or WiFi connect failure) → current
  reading is appended to an on-device ring buffer (NVS-backed, survives
  power loss/reset, not just deep sleep) and retried on the next successful
  connection, batched with whatever else has accumulated.
- Buffer capacity: 192 entries (~48h at 15-min sampling). Beyond that,
  oldest entries are silently overwritten — there is no way to know
  server-side that entries were dropped except a gap larger than expected
  between consecutive reading timestamps.
