import re

from pydantic import BaseModel, Field, field_validator

SENTINEL_NO_ECHO = -1.00

# Lightweight sanity check, not full RFC 5322 validation -- avoids pulling in
# the email-validator dependency for a single admin-entered address.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ConfigIn(BaseModel):
    wakeup_period_min: int = Field(ge=1, le=1440)
    avg_sample_count: int = Field(ge=1, le=1000)


class ReadingIn(BaseModel):
    distance_cm: float
    battery_mv: int = Field(ge=0, le=5000)
    # Raw ESP32C6 internal chip temperature. Optional: older firmware
    # (before this field existed) sends no chip_temp_c at all, which
    # pydantic defaults to None here — treated as "unknown" downstream.
    chip_temp_c: float | None = Field(default=None, ge=-40, le=125)

    @field_validator("distance_cm")
    @classmethod
    def validate_distance(cls, v: float) -> float:
        if v == SENTINEL_NO_ECHO:
            return v
        if not (0 <= v <= 500):
            raise ValueError(f"distance_cm {v} out of plausible range (0-500, or sentinel -1.00)")
        return v


class DeviceRequest(BaseModel):
    config: ConfigIn
    rssi: int = Field(ge=-120, le=0)
    readings: list[ReadingIn] = Field(min_length=1, max_length=192)


class AdminConfigIn(BaseModel):
    """Desired device settings, pushed to the device on its next check-in.

    Ranges match device.md's response-side validation table; None means
    "no override for this field".
    """

    wakeup_period_min: int | None = Field(default=None, ge=1, le=1440)
    avg_sample_count: int | None = Field(default=None, ge=1, le=100)
    # Sensor calibration: always a concrete value (no "no override" case
    # like the two fields above), takes effect immediately on save.
    reference_offset_cm: float = Field(ge=0, le=1000)
    chip_temp_offset_c: float = Field(ge=-20, le=20)


class AlertConfigIn(BaseModel):
    """Alert thresholds + email delivery settings, all admin-editable.

    No subscribe flag for weak signal -- it's a UI-only dashboard warning,
    never emailed (see device.md-style rationale in admin_settings.html).
    """

    low_level_threshold_cm: float = Field(ge=0, le=1000)
    low_battery_threshold_v: float = Field(ge=0, le=5)
    weak_signal_threshold_dbm: int = Field(ge=-120, le=0)
    submersed_threshold_cm: float = Field(ge=0, le=1000)
    recipient_email: str | None = Field(default=None, max_length=254)
    subscribe_critical_low_level: bool = True
    subscribe_low_battery: bool = True
    subscribe_submersion_risk: bool = True

    @field_validator("recipient_email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        if not EMAIL_PATTERN.match(v):
            raise ValueError(f"recipient_email {v!r} doesn't look like a valid email address")
        return v
