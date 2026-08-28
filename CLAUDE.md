# Water Tank Level Monitor — Server

Backend for a battery-powered ESP32C6 + HC-SR04 firmware that wakes
periodically (default 15 min, adjustable), measures water tank level via
ultrasonic distance, and POSTs the reading over WiFi/HTTPS.

**Read `device.md` in this directory first** — it's the full, self-contained
API contract (exact request/response JSON schemas, validation ranges,
retry/backlog semantics, known gaps). The firmware itself lives in a
separate repo and isn't available here; treat `device.md` as authoritative
for what the device sends and expects back.

## Goal

- Accept the device's POST, store readings in a time-series-friendly way.
- Serve/expose the data for visualization.
- The server will be hosted on a VPS
- there should be one page with public access, read only
- And one page that is configurable and can send parameters to the device by Optionally responding with config updates (`wakeup_period_min`, `avg_sample_count`) to let the device be retuned without reflashing. Bonus, not required for v1.
- Main goal:display the time variation of the water level to the user. The time scale should be adjustable and by default display the last 7 days (or the full time variation if less than 7 days).
- Display parameters chosen by the user can be saved in a cookie for next time access (no need of RGPD acceptance since this is not for tracking)
- Since this watertank get the water from the roof, its level rise when it rains, proportionally to the rain quantity. Later on, I want to correlate these data to meteo data publicly available: on the curve a local event should be detected when the water level rise, a local indicator display the quantity of rain (in mm), and correlate to public meteo data (we use this as a local meteo station regarding rain level. This functionnality will be desactivated when the tank is full (no more linearity between rain quantity and level))
- Similarly the level mainly goes down when we water the garden, these event should be detected also and tagged on the curve.
- The surface of the tank has not been measured yet (approx ~10m2), so until it is calibrated the results should be presented in mm or Liters, but the conversion will be approximate until the surface is confirmed.
- An admin page must be accessible (with a different url, no login link on the public page). This page must be protected by password. This page must repeat the public page, but add some content, such as: possibility to modify wakeup_period_min and avg_sample_count
- Grafana is a possibility but probably we need a custom made approach (advise needed on this point)

## Suggested stack (not mandatory, just where prior discussion landed)

FastAPI + Postgres (SQLite is fine to start if that's simpler to stand up).
No strong opinion beyond: keep it simple, avoid infra you don't need yet
(no message queues, no microservices, no auth system until the device
actually needs one — see `device.md`'s "Known gaps" section, the device
currently sends no ID/auth token at all).

## Working style (carried over from the firmware side of this project)

- Keep it functional and minimal — no speculative abstractions, no building
  for hypothetical future requirements. Three similar lines beats a
  premature abstraction.
- Confirm non-obvious design decisions before implementing them, especially
  anything affecting the API contract (changes there need to stay in sync
  with the firmware).
- Test incrementally — e.g. stand up the POST endpoint and verify it with a
  hand-built curl/httpie request matching `device.md`'s schema *before*
  wiring up the real device, same way the firmware side was built and
  tested one module at a time.
- The device is currently pointed at `https://httpbin.org/post` for testing
  (a public echo service). Once this server has a real deployed URL, that
  needs to be updated in the firmware's `include/secrets.h` (`POST_URL`) —
  that's a firmware-repo change, flag it as a to-do rather than assuming
  it's handled here.

## First steps (suggested, not prescriptive)

1. Design the DB schema for readings (device sends raw `distance_cm` +
   `battery_mv` per reading, plus `rssi` and current `config` once per
   request — see `device.md` for exact shapes).
2. Build the POST endpoint, validate against the documented request schema.
3. Decide the tank calibration approach (empty/full distance → level% or
   liters) — this lives entirely server-side per `device.md`.
4. Only then: design the dashboard, and (optional/bonus) config-sync responses.
