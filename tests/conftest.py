"""Pytest-Konfiguration für weather_mow Tests.

Die pytest-homeassistant-custom-component fixtures (hass, enable_custom_integrations, …)
werden automatisch via entry_point 'homeassistant' geladen — kein pytest_plugins nötig.
"""

import sys
from pathlib import Path

# Projektstamm auf sys.path, damit 'custom_components.weather_mow' importierbar ist.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
