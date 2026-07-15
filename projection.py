from datetime import datetime, timedelta, timezone

from config import BATTERY_MIN_MV

TANK_PROJECTION_WINDOW_DAYS = 30
TANK_MIN_SPAN_DAYS = 7
TANK_MAX_LOOKAHEAD_DAYS = 182  # ~6 months

BATTERY_PROJECTION_WINDOW_DAYS = 10
BATTERY_MIN_SPAN_DAYS = 2
BATTERY_MAX_LOOKAHEAD_DAYS = 30


def _fit_crossing(points: list[tuple[datetime, float]], threshold: float) -> datetime | None:
    """OLS-fit (time, value) points; return the projected time the fitted line
    crosses `threshold`, or None if the fit isn't trending toward it."""
    n = len(points)
    xs = [p[0].timestamp() for p in points]
    ys = [p[1] for p in points]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None

    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    if slope >= 0:
        return None

    cross_x = mean_x + (threshold - mean_y) / slope
    return datetime.fromtimestamp(cross_x, tz=timezone.utc)


def _project(
    points: list[tuple[datetime, float]],
    window_days: int,
    min_span_days: float,
    threshold: float,
    max_lookahead_days: int,
    now: datetime,
) -> datetime | None:
    window_start = now - timedelta(days=window_days)
    windowed = [p for p in points if p[0] >= window_start]
    if len(windowed) < 2:
        return None

    span_days = (max(p[0] for p in windowed) - min(p[0] for p in windowed)).total_seconds() / 86400
    if span_days < min_span_days:
        return None

    crossing = _fit_crossing(windowed, threshold)
    if crossing is None or crossing > now + timedelta(days=max_lookahead_days):
        return None
    return crossing


def estimate_tank_empty_date(level_points: list[tuple[datetime, float]], now: datetime) -> datetime | None:
    """Linear projection from the last 30 days of water level (cm) readings.

    Returns the projected date the level crosses 0cm, if that's within the
    next ~6 months and there's at least 7 days of data to fit against.
    """
    return _project(
        level_points,
        window_days=TANK_PROJECTION_WINDOW_DAYS,
        min_span_days=TANK_MIN_SPAN_DAYS,
        threshold=0.0,
        max_lookahead_days=TANK_MAX_LOOKAHEAD_DAYS,
        now=now,
    )


def estimate_battery_critical_date(battery_points: list[tuple[datetime, float]], now: datetime) -> datetime | None:
    """Linear projection from the last 10 days of battery voltage (mV) readings.

    Returns the projected date voltage crosses BATTERY_MIN_MV, if that's
    within the next ~30 days and there's at least 2 days of data to fit against.
    """
    return _project(
        battery_points,
        window_days=BATTERY_PROJECTION_WINDOW_DAYS,
        min_span_days=BATTERY_MIN_SPAN_DAYS,
        threshold=BATTERY_MIN_MV,
        max_lookahead_days=BATTERY_MAX_LOOKAHEAD_DAYS,
        now=now,
    )


def days_until(target: datetime | None, now: datetime) -> int | None:
    if target is None:
        return None
    return max(0, (target - now).days)
