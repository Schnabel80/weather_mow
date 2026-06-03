"""Stellt sicher, dass jeder translation_key in de.json UND en.json existiert."""

from __future__ import annotations

import json
import re
from pathlib import Path

CC = Path("custom_components/weather_mow")
PLATFORMS = ["sensor", "binary_sensor", "switch", "number", "time", "date", "button"]


def _keys_in_source(platform: str) -> set[str]:
    text = (CC / f"{platform}.py").read_text(encoding="utf-8")
    return set(re.findall(r'translation_key\s*=\s*"([a-z0-9_]+)"', text))


def _load(name: str) -> dict:
    return json.loads((CC / "translations" / name).read_text(encoding="utf-8"))


def test_all_translation_keys_present_de_en():
    de = _load("de.json").get("entity", {})
    en = _load("en.json").get("entity", {})
    missing = []
    for platform in PLATFORMS:
        for key in _keys_in_source(platform):
            for lang_name, lang in (("de", de), ("en", en)):
                node = lang.get(platform, {}).get(key)
                if not node or "name" not in node:
                    missing.append(f"{lang_name}:{platform}.{key}")
    assert not missing, f"Fehlende Übersetzungen: {missing}"


def test_block_reason_states_complete_de_en():
    expected = {
        "mowing_active",
        "mowing_allowed",
        "too_wet",
        "battery_low",
        "waiting_for_favorable",
        "daily_target_reached",
        "emergency_mow_tomorrow_rain",
        "outside_time_window",
        "too_dark_hedgehog",
        "too_hot",
        "disabled",
    }
    for name in ("de.json", "en.json"):
        states = _load(name)["entity"]["sensor"]["block_reason"].get("state", {})
        assert expected <= set(states), f"{name}: fehlende States {expected - set(states)}"
