from pydantic import BaseModel, Field, field_validator

SENTINEL_NO_ECHO = -1.00


class ConfigIn(BaseModel):
    wakeup_period_min: int = Field(ge=1, le=1440)
    avg_sample_count: int = Field(ge=1, le=1000)


class ReadingIn(BaseModel):
    distance_cm: float
    battery_mv: int = Field(ge=0, le=5000)

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
