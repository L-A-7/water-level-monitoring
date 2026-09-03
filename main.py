import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import alerts
import calibration
import calibration_store
import db
import projection
import sample_filter
from auth import require_admin, require_device_token
from schemas import SENTINEL_CHIP_TEMP_FAIL, SENTINEL_NO_ECHO, AdminConfigIn, AlertConfigIn, DeviceRequest, EraseFieldsIn

DEFAULT_RANGE_DAYS = 7
SUMMARY_LOOKBACK_DAYS = max(projection.TANK_PROJECTION_WINDOW_DAYS, projection.BATTERY_PROJECTION_WINDOW_DAYS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    calibration_store.init_calibration_file()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/watertank/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
# Cache-busting query string for static css/js: fixed per process, so every
# deploy (which requires a service restart to pick up main.py/db.py changes
# anyway) gets a fresh URL and can't serve a stale cached JS/CSS file from
# before the deploy -- see the "checkboxes not exclusive" bug this fixed.
templates.env.globals["static_version"] = int(time.time())


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@app.get("/watertank", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/watertank/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse(request, "about.html")


@app.get("/watertank/admin", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def admin(request: Request):
    return templates.TemplateResponse(request, "admin.html")


@app.get("/watertank/admin/settings", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def admin_settings(request: Request):
    return templates.TemplateResponse(request, "admin_settings.html")


@app.get("/watertank/admin/data-editor", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def admin_data_editor(request: Request):
    return templates.TemplateResponse(request, "admin_data_editor.html")


@app.post("/watertank/api/readings/{token}", dependencies=[Depends(require_device_token)])
def post_readings(token: str, body: DeviceRequest):
    received_at = datetime.now(timezone.utc)
    n = len(body.readings)

    with db.get_connection() as conn:
        request_id = db.insert_request(
            conn,
            received_at=received_at.isoformat(),
            rssi=body.rssi,
            wakeup_period_min=body.config.wakeup_period_min,
            avg_sample_count=body.config.avg_sample_count,
        )

        live_distance_cm = None
        live_battery_mv = None
        live_reading_time = received_at
        for seq, reading in enumerate(body.readings):
            offset_min = (n - 1 - seq) * body.config.wakeup_period_min
            reading_time = received_at - timedelta(minutes=offset_min)
            distance_cm = None if reading.distance_cm == SENTINEL_NO_ECHO else reading.distance_cm
            # distance_std_cm shares distance_cm's sentinel (per device.md).
            distance_std_cm = None if reading.distance_std_cm == SENTINEL_NO_ECHO else reading.distance_std_cm
            chip_temp_c = None if reading.chip_temp_c == SENTINEL_CHIP_TEMP_FAIL else reading.chip_temp_c

            raw_samples_json = None
            if reading.samples_cm:
                raw_samples_json = json.dumps(reading.samples_cm)
                # Raw samples present -> recompute distance_cm/distance_std_cm
                # server-side (MAD-based filter, see sample_filter.py) instead
                # of trusting the device's own on-device-filtered values.
                filtered_distance_cm, filtered_distance_std_cm = sample_filter.filter_samples(reading.samples_cm)
                distance_cm = None if filtered_distance_cm == SENTINEL_NO_ECHO else filtered_distance_cm
                distance_std_cm = None if filtered_distance_std_cm == SENTINEL_NO_ECHO else filtered_distance_std_cm

            db.insert_reading(
                conn,
                request_id=request_id,
                seq=seq,
                reading_time=reading_time.isoformat(),
                distance_cm=distance_cm,
                battery_mv=reading.battery_mv,
                chip_temp_c=chip_temp_c,
                distance_std_cm=distance_std_cm,
                raw_samples_json=raw_samples_json,
            )

            if seq == n - 1:
                # The live reading (current wake, not a backlog entry) -- the
                # only one alerts should evaluate against, since backlog
                # entries are old news by the time they're flushed.
                live_distance_cm = distance_cm
                live_battery_mv = reading.battery_mv
                live_reading_time = reading_time

        desired_wakeup, desired_avg = db.get_desired_config(conn)

        history = calibration_store.load_history()
        live_level_cm, _ = calibration.distance_to_level(history, live_distance_cm, live_reading_time)
        alerts.evaluate_alerts(conn, live_level_cm, live_battery_mv, live_distance_cm, live_reading_time.isoformat())

    response = {}
    if desired_wakeup is not None:
        response["wakeup_period_min"] = desired_wakeup
    if desired_avg is not None:
        response["avg_sample_count"] = desired_avg
    return response


@app.get("/watertank/api/readings")
def get_readings(start: str | None = None, end: str | None = None):
    with db.get_connection() as conn:
        data_start, data_end = db.get_data_bounds(conn)
        if data_start is None or data_end is None:
            return {"start": None, "end": None, "data_start": None, "data_end": None, "readings": []}

        resolved_end = _parse_iso(end) if end else data_end
        resolved_start = (
            _parse_iso(start) if start else max(data_start, resolved_end - timedelta(days=DEFAULT_RANGE_DAYS))
        )

        rows = db.get_readings(conn, resolved_start.isoformat(), resolved_end.isoformat())
        history = calibration_store.load_history()

    readings = []
    for reading_time_str, distance_cm, battery_mv, chip_temp_c, distance_std_cm, rssi in rows:
        reading_time = datetime.fromisoformat(reading_time_str)
        level_cm, volume_liters = calibration.distance_to_level(history, distance_cm, reading_time)
        temp_c = calibration.temp_display(history, chip_temp_c, reading_time)
        readings.append(
            {
                "time": reading_time_str,
                "distance_cm": distance_cm,
                "level_cm": level_cm,
                "volume_liters": volume_liters,
                "battery_mv": battery_mv,
                "chip_temp_c": temp_c,
                "distance_std_cm": distance_std_cm,
                "rssi": rssi,
            }
        )

    return {
        "start": resolved_start.isoformat(),
        "end": resolved_end.isoformat(),
        "data_start": data_start.isoformat(),
        "data_end": data_end.isoformat(),
        "readings": readings,
    }


@app.get("/watertank/api/summary")
def get_summary():
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=SUMMARY_LOOKBACK_DAYS)

    with db.get_connection() as conn:
        rows = db.get_readings(conn, window_start.isoformat(), now.isoformat())
        latest = db.get_latest_reading(conn)
        latest_request = db.get_latest_request(conn)
        history = calibration_store.load_history()
        weak_signal_warning = alerts.is_weak_signal(conn, latest_request[1] if latest_request else None)

    level_points = []
    battery_points = []
    for reading_time_str, distance_cm, battery_mv, _chip_temp_c, _distance_std_cm, _rssi in rows:
        t = datetime.fromisoformat(reading_time_str)
        level_cm, _ = calibration.distance_to_level(history, distance_cm, t)
        if level_cm is not None:
            level_points.append((t, level_cm))
        battery_points.append((t, battery_mv))

    tank_empty_at = projection.estimate_tank_empty_date(level_points, now)
    battery_critical_at = projection.estimate_battery_critical_date(battery_points, now)

    last_reading_time = None
    latest_level_cm = None
    latest_volume_liters = None
    latest_battery_mv = None
    latest_temp_c = None
    latest_distance_cm = None
    if latest:
        latest_time_str, latest_distance_cm, latest_battery_mv, latest_chip_temp_c = latest
        last_reading_time = datetime.fromisoformat(latest_time_str)
        latest_level_cm, latest_volume_liters = calibration.distance_to_level(
            history, latest_distance_cm, last_reading_time
        )
        latest_temp_c = calibration.temp_display(history, latest_chip_temp_c, last_reading_time)

    return {
        "last_reading_time": last_reading_time.isoformat() if last_reading_time else None,
        "level_cm": latest_level_cm,
        "distance_cm": latest_distance_cm,
        "volume_m3": (latest_volume_liters / 1000) if latest_volume_liters is not None else None,
        "battery_mv": latest_battery_mv,
        "battery_v": (latest_battery_mv / 1000) if latest_battery_mv is not None else None,
        "chip_temp_c": latest_temp_c,
        "tank_empty_date": tank_empty_at.date().isoformat() if tank_empty_at else None,
        "tank_empty_days": projection.days_until(tank_empty_at, now),
        "battery_critical_date": battery_critical_at.date().isoformat() if battery_critical_at else None,
        "battery_critical_days": projection.days_until(battery_critical_at, now),
        "rssi": latest_request[1] if latest_request else None,
        "weak_signal_warning": weak_signal_warning,
        "wakeup_period_min": latest_request[2] if latest_request else None,
    }


@app.get("/watertank/api/admin/config", dependencies=[Depends(require_admin)])
def get_admin_config():
    with db.get_connection() as conn:
        desired_wakeup, desired_avg = db.get_desired_config(conn)
        latest = db.get_latest_request(conn)
    reference_offset_cm, chip_temp_offset_c = calibration_store.get_current_calibration()

    device_reported = None
    if latest:
        received_at, rssi, wakeup_period_min, avg_sample_count = latest
        device_reported = {
            "received_at": received_at,
            "rssi": rssi,
            "wakeup_period_min": wakeup_period_min,
            "avg_sample_count": avg_sample_count,
        }

    return {
        "desired": {"wakeup_period_min": desired_wakeup, "avg_sample_count": desired_avg},
        "calibration": {"reference_offset_cm": reference_offset_cm, "chip_temp_offset_c": chip_temp_offset_c},
        "device_reported": device_reported,
    }


@app.put("/watertank/api/admin/config", dependencies=[Depends(require_admin)])
def put_admin_config(body: AdminConfigIn):
    now = datetime.now(timezone.utc)
    with db.get_connection() as conn:
        db.set_desired_config(conn, body.wakeup_period_min, body.avg_sample_count)
    calibration_store.set_calibration(body.reference_offset_cm, body.chip_temp_offset_c, now.isoformat())
    return {
        "desired": {"wakeup_period_min": body.wakeup_period_min, "avg_sample_count": body.avg_sample_count},
        "calibration": {"reference_offset_cm": body.reference_offset_cm, "chip_temp_offset_c": body.chip_temp_offset_c},
    }


@app.get("/watertank/api/admin/edit-readings", dependencies=[Depends(require_admin)])
def get_admin_edit_readings(start: str | None = None, end: str | None = None):
    with db.get_connection() as conn:
        data_start, data_end = db.get_data_bounds(conn)
        if data_start is None or data_end is None:
            return {"start": None, "end": None, "data_start": None, "data_end": None, "readings": []}

        resolved_end = _parse_iso(end) if end else data_end
        resolved_start = (
            _parse_iso(start) if start else max(data_start, resolved_end - timedelta(days=DEFAULT_RANGE_DAYS))
        )

        rows = db.get_readings_for_edit(conn, resolved_start.isoformat(), resolved_end.isoformat())

    readings = [
        {
            "id": id_,
            "time": reading_time_str,
            "distance_cm": distance_cm,
            "distance_std_cm": distance_std_cm,
            "chip_temp_c": chip_temp_c,
            "battery_mv": battery_mv,
            "rssi": rssi,
        }
        for id_, reading_time_str, distance_cm, distance_std_cm, chip_temp_c, battery_mv, rssi in rows
    ]

    return {
        "start": resolved_start.isoformat(),
        "end": resolved_end.isoformat(),
        "data_start": data_start.isoformat(),
        "data_end": data_end.isoformat(),
        "readings": readings,
    }


@app.post("/watertank/api/admin/erase-fields", dependencies=[Depends(require_admin)])
def post_admin_erase_fields(body: EraseFieldsIn):
    if "whole_reading" in body.fields:
        db.backup_before_delete()
        with db.get_connection() as conn:
            updated = db.delete_readings(conn, body.ids)
    else:
        with db.get_connection() as conn:
            updated = db.erase_reading_fields(conn, body.ids, body.fields)
    return {"updated": updated}


@app.get("/watertank/api/admin/raw-samples", dependencies=[Depends(require_admin)])
def get_admin_raw_samples_list():
    with db.get_connection() as conn:
        rows = db.get_raw_sample_readings(conn)
    return [
        {
            "id": reading_id,
            "time": reading_time,
            "distance_cm": distance_cm,
            "distance_std_cm": distance_std_cm,
            "sample_count": len(json.loads(raw_samples_json)),
        }
        for reading_id, reading_time, distance_cm, distance_std_cm, raw_samples_json in rows
    ]


@app.get("/watertank/api/admin/raw-samples/{reading_id}", dependencies=[Depends(require_admin)])
def get_admin_raw_samples_detail(reading_id: int):
    with db.get_connection() as conn:
        row = db.get_raw_samples_for_reading(conn, reading_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No raw samples for this reading")
    reading_id, reading_time, distance_cm, distance_std_cm, raw_samples_json = row
    return {
        "id": reading_id,
        "time": reading_time,
        "distance_cm": distance_cm,
        "distance_std_cm": distance_std_cm,
        "samples_cm": json.loads(raw_samples_json),
    }


@app.get("/watertank/api/admin/alerts", dependencies=[Depends(require_admin)])
def get_admin_alerts():
    with db.get_connection() as conn:
        return db.get_alert_config(conn)


@app.put("/watertank/api/admin/alerts", dependencies=[Depends(require_admin)])
def put_admin_alerts(body: AlertConfigIn):
    with db.get_connection() as conn:
        db.set_alert_config(
            conn,
            body.low_level_threshold_cm,
            body.low_battery_threshold_v,
            body.weak_signal_threshold_dbm,
            body.submersed_threshold_cm,
            body.recipient_email,
            body.subscribe_critical_low_level,
            body.subscribe_low_battery,
            body.subscribe_submersion_risk,
        )
        return db.get_alert_config(conn)
