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
        DEFAULT_IRRIGATION_MM,
        IRRIGATION_MM_MAX,
        IRRIGATION_MM_STEP,
        FORECAST_DISCOUNT_MM,
        GRACE_PERIOD_MINUTES,
        STORAGE_KEY_WETNESS,
    )
    assert K_SOLAR_MM_PER_UPDATE == 0.030
    assert K_TEMP_MM_PER_UPDATE_C == 0.001
    assert K_WIND_MM_PER_UPDATE_KMH == 0.0005
    assert K_COND_MM_PER_UPDATE_C == 0.003
    assert DEW_OFFSET_C == 3.0
    assert WETNESS_MAX_MM == 20.0
    assert DEFAULT_MOW_THRESHOLD_MM == 0.5
    assert MOW_THRESHOLD_MIN_MM == 0.1
    assert MOW_THRESHOLD_MAX_MM == 3.0
    assert MOW_THRESHOLD_STEP_MM == 0.1
    assert DEFAULT_IRRIGATION_MM == 5.0
    assert IRRIGATION_MM_MAX == 50.0
    assert IRRIGATION_MM_STEP == 0.5
    assert FORECAST_DISCOUNT_MM == 0.3
    assert GRACE_PERIOD_MINUTES == 30

def test_button_in_platforms():
    from const import PLATFORMS
    assert "button" in PLATFORMS
