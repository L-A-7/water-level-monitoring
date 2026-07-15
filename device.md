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
    {"distance_cm": 50.50, "battery_mv": 4200},
    {"distance_cm": 50.60, "battery_mv": 4195},
    {"distance_cm": 50.47, "battery_mv": 4223}
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `config.wakeup_period_min` | uint, minutes | Device's *current* wake interval (echoes back what it's running, doesn't necessarily match what you last told it — see Response below). |
| `config.avg_sample_count` | uint | Device's current HC-SR04 sample count (median+3σ-filtered mean per wake). |
| `rssi` | int, dBm | WiFi signal strength of *this* connection only. Not present per-reading — there's no historical RSSI for backlog entries (no WiFi = no RSSI at the time they were queued). |
| `readings` | array | Oldest first, **current reading is always last**. Array has 1 entry in the normal case; more than 1 when flushing a backlog after a WiFi outage (queue holds up to 192 entries / 48h at 15-min sampling, ring-buffer overwrite-oldest if exceeded). |
| `readings[].distance_cm` | float, 2 decimals | Raw sensor distance. **Sentinel value `-1.00` means the HC-SR04 got no valid echo that wake** — filter/flag these, don't treat as a literal reading. |
| `readings[].battery_mv` | int | Battery voltage in mV (~3000-4200 for the single-cell LiPo in use). |

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
| `avg_sample_count` | 1 – 100 | Ignored, device keeps its current value (in practice the device also hard-caps actual sampling at 100 internally regardless of what's configured, for battery/timing reasons) |

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
