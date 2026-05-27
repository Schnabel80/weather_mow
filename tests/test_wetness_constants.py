import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "weather_mow"))

def test_k_constants_exist():
    from const import (
        K_SOLAR_MM_PER_UPDATE,
        K_TEMP_MM_PER_UPDATE_C,
        K_WIND_MM_PER_UPDATE_KMH,
        K_COND_MM_PER_UPDATE_C,
        DEW_OFFSET_C,
        WETNESS_MAX_MM,
        DEFAULT_MOW_THRESHOLD_MM,
        MOW_THRESHOLD_MIN_MM,
        MOW_THRESHOLD_MAX_MM,
        MOW_THRESHOLD_STEP_MM,
        IRRIGATION_FIXED_MM,
        WETNESS_DELTA_CAP_MM,
        FORECAST_DISCOUNT_MM,
        GRACE_PERIOD_MINUTES,
        STORAGE_KEY_WETNESS,
    )
    assert K_SOLAR_MM_PER_UPDATE == 0.030
    assert K_TEMP_MM_PER_UPDATE_C == 0.001
    assert K_WIND_MM_PER_UPDATE_KMH == 0.0005
    assert K_COND_MM_PER_UPDATE_C == 0.003
    assert DEW_OFFSET_C == 3.0
    assert WETNESS_MAX_MM == 2.0
    assert DEFAULT_MOW_THRESHOLD_MM == 0.5
    assert MOW_THRESHOLD_MIN_MM == 0.1
    assert MOW_THRESHOLD_MAX_MM == 3.0
    assert MOW_THRESHOLD_STEP_MM == 0.1
    assert IRRIGATION_FIXED_MM == 2.0
    assert WETNESS_DELTA_CAP_MM == 2.0
    assert FORECAST_DISCOUNT_MM == 0.3
    assert GRACE_PERIOD_MINUTES == 30

def test_button_in_platforms():
    from const import PLATFORMS
    assert "button" in PLATFORMS
