from datetime import datetime

from config import TANK_SURFACE_AREA_M2

CalibrationHistory = list[tuple[datetime, "datetime | None", float, float]]


def calibration_at(history: CalibrationHistory, timestamp: datetime) -> tuple[float, float]:
    """(reference_offset_cm, chip_temp_offset_c) in effect at `timestamp`."""
    for start, end, reference_offset_cm, chip_temp_offset_c in history:
        if start <= timestamp and (end is None or timestamp < end):
            return reference_offset_cm, chip_temp_offset_c
    raise ValueError(f"no calibration defined for {timestamp}")


def distance_to_level(
    history: CalibrationHistory, sensor_distance_cm: float | None, timestamp: datetime
) -> tuple[float | None, float | None]:
    """Raw sensor distance (cm), read at `timestamp` -> (water_level_cm, volume_liters).

    water_level = reference_offset_cm - sensor_distance
    """
    if sensor_distance_cm is None:
        return None, None

    reference_offset_cm, _ = calibration_at(history, timestamp)
    water_level_cm = reference_offset_cm - sensor_distance_cm
    volume_liters = water_level_cm * TANK_SURFACE_AREA_M2 * 10
    return water_level_cm, volume_liters


def temp_display(history: CalibrationHistory, chip_temp_c: float | None, timestamp: datetime) -> float | None:
    """Raw chip temperature (°C) -> calibrated display temperature."""
    if chip_temp_c is None:
        return None

    _, chip_temp_offset_c = calibration_at(history, timestamp)
    return chip_temp_c + chip_temp_offset_c
