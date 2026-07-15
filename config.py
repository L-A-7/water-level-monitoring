from datetime import datetime, timezone

# TODO: move to a config file (or DB row) once these are measured on-site.

TANK_HEIGHT_CM = 350  # full internal height of the tank, top rim to bottom
TANK_SURFACE_AREA_M2 = 10.0  # approximate, not yet measured

BATTERY_MIN_MV = 3000  # voltage treated as "needs charging", low end of the documented ~3000-4200mV range

# Sensor mounting position over time: vertical distance from the tank's top
# rim down to the sensor's mounting point. Changes if the sensor is
# physically repositioned, so it's tracked as a history rather than a
# single constant — each entry covers [start, end). end=None means "still
# in effect". Entries must be in chronological order and non-overlapping.
SENSOR_POSITION_HISTORY = [
    # (start, end, sensor_position_cm)
    (datetime(2026, 1, 1, tzinfo=timezone.utc), None, 50),
]
