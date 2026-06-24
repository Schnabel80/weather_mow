# Täglicher GitHub Issue-Report

Tägliche KI-Analyse aller offenen Issues über alle Schnabel80-Repositories, als GitHub Issue in `weather_mow` veröffentlicht.

## Einrichten (neue Session)

Diesen Prompt in Claude Code ausführen (z.B. als Slash-Command oder direkt eingeben):

```
Richte den täglichen GitHub Issue-Report ein:
Erstelle einen CronCreate-Job für täglich 05:00 Uhr mit folgendem Prompt:

Führe den täglichen GitHub Issue-Report für Schnabel80 aus. Heute ist ein neuer Tag.

Schritt 1 – Duplikat-Check:
Prüfe in Schnabel80/weather_mow ob bereits ein offenes Issue mit Label "daily-report" existiert, dessen Titel das heutige Datum (DD.MM.YYYY) enthält. Falls ja: Aufgabe beenden.

Schritt 2 – Issues abrufen:
Hole alle offenen Issues (Pull Requests ignorieren) aus diesen vier Repositories:
- Schnabel80/weather_mow
- Schnabel80/navimow-i105-ha
- Schnabel80/homeassistant-vw-images
- Schnabel80/biterisk-ha

Schritt 3 – KI-Analyse erstellen:
Erstelle einen detaillierten deutschen Bericht. Für jedes Issue:
- Problem: Kurze, klare Zusammenfassung was der Nutzer beschreibt
- Analyse: Welche Komponente/Datei ist betroffen? Was ist die wahrscheinliche Ursache?
- Schweregrad: kritisch / mittel / niedrig (mit Begründung)
- Lösungsansatz: Konkrete erste Maßnahme oder Untersuchungsrichtung
- Handlungsempfehlung: Soll das Issue priorisiert, beobachtet oder geschlossen werden?

Abschluss: Gesamtfazit mit Gesamtzahl offener Issues, welche dringend sind, und empfohlene Bearbeitungsreihenfolge.

Falls keine Issues offen sind: Kurzer positiver Bericht "Alle Repositories sauber — keine offenen Issues."

Schritt 4 – Report veröffentlichen:
Erstelle ein neues GitHub Issue in Schnabel80/weather_mow:
- Titel: Daily Issue Report — DD.MM.YYYY (heutiges Datum)
- Label: daily-report (anlegen falls nicht vorhanden)
- Body: Vollständiger Analysebericht auf Deutsch im Markdown-Format
```

## Repositories

| Repository | Beschreibung |
|---|---|
| `Schnabel80/weather_mow` | Home Assistant Weather Mow Integration |
| `Schnabel80/navimow-i105-ha` | Navimow I105 Home Assistant Integration |
| `Schnabel80/homeassistant-vw-images` | VW Images für Home Assistant |
| `Schnabel80/biterisk-ha` | Biterisk Home Assistant Integration |

## Ausgabe

Der Report erscheint als GitHub Issue in `Schnabel80/weather_mow` mit Label `daily-report`.

## Einschränkungen

- **Session-abhängig**: Der CronCreate-Job läuft nur solange die Claude Code Session aktiv ist
- **7-Tage-Limit**: Nach 7 Tagen läuft der Job ab und muss neu eingerichtet werden
- **Kein API-Key nötig**: Die Analyse erfolgt direkt durch Claude im Pro Account

## Alternative: Vollautomatisch (ohne Session-Abhängigkeit)

Für einen dauerhaft laufenden Workflow ohne aktive Session:
1. Anthropic API-Key erstellen auf console.anthropic.com (kostenlos, ~$0.01 pro Report)
2. Als GitHub Secret `ANTHROPIC_API_KEY` in `Schnabel80/weather_mow` hinterlegen
3. Den GitHub Actions Workflow in `.github/workflows/daily_issue_check.yml` in `develop` mergen
