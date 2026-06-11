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


def test_options_sensor_steps_mirror_config_steps():
    """Issue #7: Die Sensor-Schritte im Options-Flow nutzen dieselben Texte wie
    der Config-Flow. Dieser Test erzwingt, dass beide Abschnitte synchron bleiben —
    wer config.step.X ändert, muss options.step.X mitziehen.
    """
    shared_steps = (
        "device",
        "weather",
        "station",
        "station_ecowitt",
        "station_netatmo",
        "station_other",
        "station_none",
        "radiation_fallback",
    )
    for name in ("de.json", "en.json"):
        data = _load(name)
        config_steps = data["config"]["step"]
        options_steps = data["options"]["step"]
        for step in shared_steps:
            assert step in options_steps, f"{name}: options.step.{step} fehlt"
            assert options_steps[step] == config_steps[step], (
                f"{name}: options.step.{step} weicht von config.step.{step} ab"
            )


def test_options_init_menu_translated():
    """Das Options-Menü (mow_times / sensors) ist in beiden Sprachen übersetzt."""
    for name in ("de.json", "en.json"):
        init = _load(name)["options"]["step"]["init"]
        menu = init.get("menu_options", {})
        assert {"mow_times", "sensors"} <= set(menu), f"{name}: menu_options unvollständig"
        assert "mow_times" in _load(name)["options"]["step"], f"{name}: step mow_times fehlt"


def test_block_reason_states_complete_de_en():
    """N3: Übersetzungen decken exakt die BLOCK_REASONS aus const.py ab."""
    from custom_components.weather_mow.const import BLOCK_REASONS

    expected = set(BLOCK_REASONS)
    for name in ("de.json", "en.json"):
        states = _load(name)["entity"]["sensor"]["block_reason"].get("state", {})
        assert expected == set(states), (
            f"{name}: fehlend {expected - set(states)}, überzählig {set(states) - expected}"
        )
