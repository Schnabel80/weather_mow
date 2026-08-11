"""Frische-Prüfung der Wetter-/Stationsdaten.

Bewusst frei von Home-Assistant-Importen, damit die Entscheidung eigenständig
per pytest testbar bleibt — analog zu wetness.py, drying.py, growth.py.
"""

from __future__ import annotations


def weather_data_stale(ages_s: list[float | None], threshold_s: float) -> bool:
    """True, wenn die Wetterstation als tot/veraltet gilt.

    ages_s: Pro konfiguriertem Stations-Eingang (Temp/Feuchte/Wind/Strahlung/
            Regen) das Alter seit dem letzten Update in Sekunden — oder ``None``,
            wenn der Sensor konfiguriert ist, aber gerade keinen gültigen Wert
            liefert (unavailable). Nicht konfigurierte Eingänge werden vom
            Aufrufer ausgelassen und tauchen hier nicht auf.

    Regel: nur wenn MINDESTENS ein Eingang existiert UND ALLE veraltet sind
    (älter als die Schwelle oder ``None``) → Station tot. Ein einzelner alter
    Sensor (z. B. Strahlung nachts) löst nichts aus, solange ein anderer noch
    frisch ist. Genau auf der Schwelle zählt noch als frisch (strikt größer).
    """
    if not ages_s:
        return False
    return all(a is None or a > threshold_s for a in ages_s)
