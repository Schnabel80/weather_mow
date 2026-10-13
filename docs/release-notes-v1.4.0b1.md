## 🇩🇪 v1.4.0b1

### Neu: Mehrere Rasenflächen mit einem Mäher (#19)

Bedient ein Mäher mehrere Rasenflächen, legst du **eine WeatherMow-Instanz pro Fläche** an —
jede mit eigenem Verschattungsregler, Mähfenster und Tagesziel. Neu ist, dass jede Instanz
jetzt weiß, **auf welcher Fläche der Mäher gerade ist**, und nur dann Mähzeit, `last_mowed`
und Stopp-Signale (Auto-Resume-Schutz) zählt. Vorher hat jede Instanz jede Mähsession sich
selbst zugeschrieben.

**Einrichtung:**
1. Lege eine Zahl-Entität an, z. B. einen Helfer `input_number.maeher_zone` (Min 0, Max 20,
   Schritt 1). Sie enthält die Nummer der Fläche, die der Mäher gerade mäht.
2. Öffne in **jeder** Instanz *Einstellungen → Geräte & Dienste → WeatherMow → Konfigurieren*
   (Schritt *Gerät*) und trage ein:
   - **Mähzonen-Entität (optional):** dieselbe Entität in allen Instanzen
   - **Zonen-Nummer dieser Rasenfläche:** pro Instanz eine eigene Zahl (Fläche 1 = 1, Fläche 2 = 2, …)
3. Setze die Zahl per **Automation vor dem Mähstart** auf die Fläche, die der Mäher anfahren soll.
   Wird sie erst nach dem Start gesetzt, gilt die laufende Session noch als fremd.

**Verhalten:**
- Eine Instanz zählt Mähdauer, `last_mowed` und Stopp-Signale nur, solange die Zahl ihrer
  Zonen-Nummer entspricht. Sessions in einer anderen Zone ignoriert sie.
- Ohne Mähzonen-Entität verhält sich alles **exakt wie bisher** — bestehende Installationen
  müssen nichts tun.
- Ist die Zonen-Entität nicht verfügbar oder keine Zahl, wird die Session keiner Fläche
  zugeordnet.
- Bei konfigurierter Zonen-Entität wird die Mähdauer nach einem Neustart nicht aus dem
  Recorder rekonstruiert (der Mäherverlauf sagt nichts über die Zone), sondern aus dem
  gespeicherten Stand übernommen.
- Ein Wechsel der Zahl mitten in einer laufenden Session wird nicht verfolgt.
- Welche Fläche der Mäher anfährt, entscheidet weiter deine Automation bzw. die Mäher-App —
  WeatherMow sagt pro Fläche nur, ob gemäht werden darf.

Danke an [@17Halbe](https://github.com/17Halbe) für den Impuls in Issue #19. Rückmeldungen
zur Beta gern direkt im Issue.

---

## 🇬🇧 v1.4.0b1

### New: Multiple lawns with a single mower (#19)

If one mower serves several lawns, create **one WeatherMow instance per lawn** — each with
its own shading control, mowing window and daily target. New: every instance now knows
**which lawn the mower is currently on** and only counts mowing time, `last_mowed` and stop
signals (auto-resume guard) for its own lawn. Previously every instance credited every
mowing session to itself.

**Setup:**
1. Create a number entity, e.g. a helper `input_number.mower_zone` (min 0, max 20, step 1).
   It holds the number of the lawn the mower is currently working on.
2. In **each** instance open *Settings → Devices & Services → WeatherMow → Configure*
   (step *Device*) and set:
   - **Mowing-zone entity (optional):** the same entity in all instances
   - **Zone number of this lawn:** a unique number per instance (lawn 1 = 1, lawn 2 = 2, …)
3. Set the number with an **automation before the mower starts**, to the lawn it should
   mow. If it is set only after the start, the running session still counts as foreign.

**Behavior:**
- An instance counts mowing time, `last_mowed` and stop signals only while the number
  equals its zone number. It ignores sessions in other zones.
- Without a mowing-zone entity everything behaves **exactly as before** — existing
  installations need no changes.
- If the zone entity is unavailable or not a number, the session is attributed to no lawn.
- With a zone entity configured, today's mowing time is not rebuilt from the recorder after
  a restart (the mower history says nothing about the zone) but taken from the stored state.
- Changing the number in the middle of a running session is not tracked.
- Which lawn the mower drives to is still decided by your automation or the mower app —
  WeatherMow only says per lawn whether mowing is allowed.

Thanks to [@17Halbe](https://github.com/17Halbe) for the input in issue #19. Feedback on
the beta is welcome right in the issue.
