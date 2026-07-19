import logging
import os
import smtplib
from email.mime.text import MIMEText

import db

logger = logging.getLogger("watertank.alerts")
logger.setLevel(logging.INFO)
if not logger.handlers:
    # Explicit handler so the stub-email log line is visible regardless of
    # whether anything else in the process configured the root logger.
    logger.addHandler(logging.StreamHandler())

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)


def send_alert_email(recipient: str, subject: str, body: str) -> None:
    """Send an alert email, or log it if no SMTP relay is configured yet.

    Falls back to logging rather than raising so a misconfigured/absent SMTP
    relay never breaks the device ingest request that triggered the alert.
    """
    if not SMTP_HOST:
        logger.info("ALERT EMAIL (SMTP not configured, not sent) to=%s subject=%r body=%r", recipient, subject, body)
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or "watertank-monitor@localhost"
    msg["To"] = recipient

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    except OSError:
        logger.exception("Failed to send alert email to=%s subject=%r", recipient, subject)


def evaluate_alerts(conn, level_cm: float | None, battery_mv: int | None, distance_cm: float | None, at_iso: str) -> None:
    """Check the latest reading against admin-configured thresholds and email
    on the inactive->active transition only (edge-triggered), so a condition
    that stays true across many device check-ins doesn't re-send every time.
    """
    config = db.get_alert_config(conn)

    checks = {
        "low_level": (
            config["subscribe_critical_low_level"] and level_cm is not None and level_cm < config["low_level_threshold_cm"],
            f"Water level is {level_cm:.1f} cm, below the {config['low_level_threshold_cm']:.0f} cm alert threshold."
            if level_cm is not None
            else "",
        ),
        "low_battery": (
            config["subscribe_low_battery"]
            and battery_mv is not None
            and (battery_mv / 1000) < config["low_battery_threshold_v"],
            f"Battery voltage is {battery_mv / 1000:.2f} V, below the {config['low_battery_threshold_v']:.1f} V alert threshold."
            if battery_mv is not None
            else "",
        ),
        "submersion_risk": (
            config["subscribe_submersion_risk"]
            and distance_cm is not None
            and distance_cm < config["submersed_threshold_cm"],
            f"Sensor-to-water distance is {distance_cm:.1f} cm, below the {config['submersed_threshold_cm']:.0f} cm "
            "safety threshold -- the sensor may be at risk of submersion (it is not waterproof)."
            if distance_cm is not None
            else "",
        ),
    }

    for alert_type, (is_active, message) in checks.items():
        was_active = db.get_alert_state(conn, alert_type)
        if is_active and not was_active:
            if config["recipient_email"]:
                subject = f"Water tank alert: {alert_type.replace('_', ' ').title()}"
                send_alert_email(config["recipient_email"], subject, message)
            db.set_alert_state(conn, alert_type, True, at_iso)
        elif not is_active and was_active:
            db.set_alert_state(conn, alert_type, False, at_iso)


def is_weak_signal(conn, rssi: int | None) -> bool:
    """UI-only warning (never emailed) -- see admin_settings.html copy."""
    if rssi is None:
        return False
    config = db.get_alert_config(conn)
    return rssi < config["weak_signal_threshold_dbm"]
