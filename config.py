TANK_SURFACE_AREA_M2 = 10.0  # approximate, not yet measured

BATTERY_MIN_MV = 3000  # voltage treated as "needs charging", low end of the documented ~3000-4200mV range

# Sensor mounting calibration (reference_offset_cm, chip_temp_offset_c) now
# lives in data/calibration.txt (see calibration_store.py) so it's editable
# by hand or from the admin page without a redeploy.
