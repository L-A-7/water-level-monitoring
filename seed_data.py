"""Populate the local SQLite DB with a simulated 90-day reading history.

Dev-only tool for testing the frontend before the real device is deployed.
Clears existing readings/requests each run so it's safe to re-run.
"""

import random
from datetime import datetime, timedelta, timezone

import db
from calibration import sensor_position_at
from config import TANK_HEIGHT_CM

random.seed(42)

DAYS = 90
INTERVAL_MIN = 15
WAKEUP_PERIOD_MIN = 15
AVG_SAMPLE_COUNT = 30
SENTINEL_PROBABILITY = 0.005
RAIN_START_PROBABILITY = 1 / 500
WATERING_START_PROBABILITY = 1 / 300


def simulate() -> None:
    db.init_db()

    n_points = DAYS * 24 * 60 // INTERVAL_MIN
    end_time = datetime.now(timezone.utc).replace(microsecond=0)
    start_time = end_time - timedelta(minutes=(n_points - 1) * INTERVAL_MIN)

    max_level_cm = TANK_HEIGHT_CM - sensor_position_at(start_time)
    level_cm = max_level_cm * 0.6

    rain_remaining = 0
    rain_rate = 0.0
    watering_remaining = 0
    watering_rate = 0.0

    with db.get_connection() as conn:
        conn.execute("DELETE FROM readings")
        conn.execute("DELETE FROM requests")

        for i in range(n_points):
            t = start_time + timedelta(minutes=i * INTERVAL_MIN)

            level_cm -= 0.01  # slow evaporation/seepage baseline

            if rain_remaining == 0 and random.random() < RAIN_START_PROBABILITY:
                rain_remaining = random.randint(2, 8)
                rain_rate = random.uniform(0.5, 3.0)
            if rain_remaining > 0:
                level_cm += rain_rate
                rain_remaining -= 1

            if watering_remaining == 0 and random.random() < WATERING_START_PROBABILITY:
                watering_remaining = random.randint(2, 6)
                watering_rate = random.uniform(0.5, 2.0)
            if watering_remaining > 0:
                level_cm -= watering_rate
                watering_remaining -= 1

            level_cm += random.uniform(-0.05, 0.05)
            level_cm = max(0.0, min(max_level_cm, level_cm))

            sensor_position_cm = sensor_position_at(t)
            if random.random() < SENTINEL_PROBABILITY:
                # Matches main.py's ingest handling: the -1.00 sentinel is
                # stored as NULL, never as a literal distance.
                distance_cm = None
            else:
                distance_cm = round(TANK_HEIGHT_CM - sensor_position_cm - level_cm, 2)
                distance_cm = max(0.0, min(400.0, distance_cm))

            battery_mv = round(4200 - (i / n_points) * 250 + random.uniform(-10, 10))
            rssi = random.randint(-75, -55)

            request_id = db.insert_request(
                conn,
                received_at=t.isoformat(),
                rssi=rssi,
                wakeup_period_min=WAKEUP_PERIOD_MIN,
                avg_sample_count=AVG_SAMPLE_COUNT,
            )
            db.insert_reading(
                conn,
                request_id=request_id,
                seq=0,
                reading_time=t.isoformat(),
                distance_cm=distance_cm,
                battery_mv=battery_mv,
            )

    print(f"Inserted {n_points} readings from {start_time.isoformat()} to {end_time.isoformat()}")


if __name__ == "__main__":
    simulate()
