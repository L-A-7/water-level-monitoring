from datetime import datetime

from config import SENSOR_POSITION_HISTORY, TANK_HEIGHT_CM, TANK_SURFACE_AREA_M2


def sensor_position_at(timestamp: datetime) -> float:
    """Sensor mounting offset (cm below tank top) in effect at `timestamp`."""
    for start, end, position_cm in SENSOR_POSITION_HISTORY:
        if start <= timestamp and (end is None or timestamp < end):
            return position_cm
    raise ValueError(f"no sensor position defined for {timestamp}")


def distance_to_level(sensor_distance_cm: float | None, timestamp: datetime) -> tuple[float | None, float | None]:
    """Raw sensor distance (cm), read at `timestamp` -> (water_level_cm, volume_liters).

    water_level = tank_height - sensor_position - sensor_distance
    """
    if sensor_distance_cm is None:
        return None, None

    sensor_position_cm = sensor_position_at(timestamp)
    water_level_cm = TANK_HEIGHT_CM - sensor_position_cm - sensor_distance_cm
    volume_liters = water_level_cm * TANK_SURFACE_AREA_M2 * 10
    return water_level_cm, volume_liters
