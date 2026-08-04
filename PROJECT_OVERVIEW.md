# Projekt-Überblick: health-dashboard

Technischer Stand des Repos für die Arbeit mit einem KI-Assistenten (z.B. Claude Chat) außerhalb
von Claude Code — beschreibt, welche Dateien es gibt und welche Logik/Konventionen dahinterstecken,
damit Feature-Diskussionen ohne erneutes Codebase-Exploring starten können. Wird bei jedem
`git commit` mit inhaltlichen Änderungen aktuell gehalten.

**Zweck des Projekts:** Persönliches Trainings-Dashboard für einen Marathon-/Triathlon-Athleten
(SWB Marathon Bremen 13.09.2026, GEWOBA City Triathlon 09.08.2026). Synchronisiert Garmin-Connect-
Daten, speichert sie in SQLite, wertet sie regelbasiert aus und pflegt ein LLM-gestütztes
Wissens-Gedächtnis (Schicht 3, siehe unten). Streamlit-Multi-Page-App, Docker-Compose-Betrieb.

## Tech-Stack

Streamlit (Multi-Page, dateibasiertes Routing über `pages/`), SQLite über rohes `sqlite3` (kein
ORM), `garminconnect` (Garmin-API), `google-genai` (Gemini) für Schicht 3, Plotly/pydeck für
Charts/Karten, Docker Compose (`.:/app`-Volume-Mount, d.h. Code-Änderungen wirken ohne Rebuild).

## Sync-Architektur

`garmin_service.py::fetch_and_store_garmin_data(target_date=None, client=None)` ist der **eine
zentrale Einstiegspunkt** für alle Garmin-Kern-/Erweiterungsdaten eines Tages. Wird aufgerufen von:
- Settings-Seite, Einzel-Tages-Sync-Button
- `garmin_backfill.py::run_backfill()`, das ihn chronologisch vorwärts pro Tag im Zeitraum aufruft

Innerhalb dieser Funktion unterscheiden sich zwei Muster:
- **"Nur heute"-gegatet** (`if target_date == date.today().isoformat()`): Account-weite
  Snapshot-Endpunkte, die während Backfill nicht für jeden historischen Tag neu berechnet werden
  sollen (`recompute_zones()` für Trainingszonen).
- **Unconditional, für jeden Tag** (auch Backfill-Tage): `compute_daily_summary()`,
  `compute_weekly_summary()` — sollen für jeden importierten Tag/jede betroffene Woche vorliegen.

**Aktivitäten** (Läufe/Rad/Schwimmen, `garmin_activities.py`) sind bewusst **komplett getrennt**
vom obigen Sync und nur manuell über die Settings-Seite anstoßbar (zweistufig: Aktivitätsliste,
dann optional Sekunden-Detail-Zeitreihen pro Aktivität) — eine volle Historie kann mehrere hundert
Aktivitäten mit je mehreren hundert Detail-Zeilen umfassen.

**429-Rate-Limit-Handling:** `garmin_auth.py` cached Garmin-Session-Tokens unter
`~/.garminconnect`, um wiederholten Passwort-Login (hohes 429-Risiko) zu vermeiden. Jeder
API-Call ist über `_safe_call()`-Wrapper mit randomisierten Pausen (2-4s, bei Backfill 8-15s
zwischen Tagen) abgesichert; ein echtes 429 bricht den laufenden Sync sofort ab, statt weiter zu
hämmern.

**Mehrmals-täglicher Sync:** wurde explizit auditiert (alle Save-Pfade nutzen `ON CONFLICT DO
UPDATE`-Upserts oder Delete+Insert-Zeitreihen-Ersetzung) — sicher gegen Duplikate/Datenverlust,
siehe Konventionen unten.

## Die drei "Schichten" der KI-Chat-Vorbereitung

Aufbauender regelbasierter Kontext für einen künftigen Chat (noch nicht gebaut):

- **Schicht 1** (`daily_summary.py`, `activity_analytics.py`, `training_zones.py`): pro Tag bzw.
  pro Aktivität vorverdichtete Kennzahlen — HRV/Schlaf/Ruhepuls vs. Baseline, Trainingslast (7/28
  Tage, Monotonie/Strain), **CTL/ATL/TSB** (Chronic/Acute Training Load, EWMA-Modell analog
  TrainingPeaks PMC, rekursiv aus dem Vortageswert), Übertrainings-Flag, Decoupling/HF-Drift/GAP
  pro Aktivität, Friel-Trainingszonen (Lauf-HF/Pace, Rad-HF/Leistung). Rein SQL/Python, kein LLM.
  `daily_summary` hat außerdem drei Journal-Spiegel-Spalten (`journal_rpe`/`journal_soreness`/
  `journal_energy_level`), die **unabhängig** vom Garmin-Sync über `sync_journal_columns()`
  gepflegt werden (siehe "Journal-Integration" unten) — Reihenfolge-unabhängiges
  Spalten-Gruppen-Upsert: Garmin-Sync und Journal-Save dürfen die jeweils andere Spalten-Gruppe
  nie überschreiben, egal welcher Trigger zuerst läuft.
- **Schicht 2** (`weekly_summary.py`): eine Zeile pro ISO-Kalenderwoche — Volumen nach Sportart,
  Zonen-Verteilung (präzise Sekunden-Bucketing wo Detaildaten vorliegen, sonst Garmins 5-Zonen-
  Fallback), Trainingsphase (Base/Build/Peak/Taper), Discipline-Limiter (VO2max-Trend-Vergleich
  Lauf vs. Rad), Renn-Countdown. Ebenfalls rein regelbasiert.
- **Schicht 3** (`insight_memory.py`): LLM-gestütztes "Erkenntnis-Gedächtnis" — **ausschließlich**
  vom Nutzer selbst eingetragene Zusatzinfos in normaler Sprache, die sich nicht aus den Daten
  ablesen lassen (z.B. feste Wochenroutinen wie Vereinstraining, Hitzeempfindlichkeit). Jeder neue
  Eintrag wird sofort per Gemini verdichtet (Präzisierung ersetzt Altes, Redundantes wird
  ignoriert) und als neue, unveränderliche Version gespeichert (`insight_memory_compressed`,
  append-only, `insight_memory_raw` als nie verändertes Archiv, Spalte `source` ∈
  `user`/`claude_import`/`journal`). **Enthält bewusst keine aus Trainingsdaten abgeleiteten
  Inhalte** — ein früherer Ansatz, der täglich automatisch Kennzahlen einmischte, wurde wieder
  verworfen, weil das Gedächtnis dadurch nur ein Trainingstagebuch dupliziert hätte statt echte,
  dauerhafte Athleten-Erkenntnisse zu sammeln.

`gemini_client.py` bündelt die Gemini-Konfiguration (API-Key, Modell, Client-Erzeugung) - aktuell
einziger Nutzer ist `insight_memory.py`.

## Journal-Integration

Das Tagesjournal (`daily_journal`, Slider für RPE/Muskelkater/Energie + Freitext) auf der
Home-Seite löst beim Speichern zwei automatische Folgeaktionen aus:
1. `daily_summary.sync_journal_columns()` — spiegelt RPE/Soreness/Energy in `daily_summary`
   (siehe oben, Reihenfolge-unabhängig zum Garmin-Sync) und aktualisiert `notable_events_text`,
   falls bereits ein `overreach_flag` aus einem vorherigen Sync vorliegt (unterscheidet "objektive
   Warnsignale, subjektiv noch nicht erfasst" von "bestätigtes Übertrainingsrisiko").
2. Ist das Freitextfeld nicht leer: automatischer Eintrag in `insight_memory_raw` mit
   `source="journal"`, der wie jeder manuelle Eintrag sofort Schicht 3 auslöst.

Ein früherer separater KI-Coach (`ai_coach.py`, Gemini-Tagesform-Score/-Empfehlung per
Knopfdruck, Tabelle `ai_coach_insights`) wurde **komplett entfernt** (Datei, Tabelle, UI,
zugehöriger Chart auf der Health-Trends-Seite).

## Workout Builder (`workout_builder.py`)

Erstellt strukturierte Garmin-Workouts (Warmup/Intervalle/Erholung/Cooldown) programmatisch und
lädt sie hoch - reine Python-Logik, kein `streamlit`-Import (gleiches Portabilitäts-Prinzip wie
`daily_summary.py`/`insight_memory.py`). `build_interval_running_workout(...)` baut ein
`RunningWorkout`-Objekt (kein Upload); `upload_workout(workout, client, schedule_date=None)` lädt
es separat hoch. Pace-/Zonen-Ziele kommen aus `training_zones_running` (kein Freitext-Parsing -
das ist einer späteren Chat-Schicht vorbehalten). UI unter `pages/6_🏗️_Workout_Builder.py`.

**Wichtige Ground-Truth-Funde (live gegen Garmins Server verifiziert, nicht aus Doku):** Das
installierte `garminconnect==0.3.2` hat mehrere falsche Konstanten in `garminconnect/workout.py`:
`ConditionType.DISTANCE` ist fälschlich `1` (tatsächlich `"lap.button"`, echte Distanz-ID ist
`3`), `TargetType.OPEN` ist fälschlich `6` (tatsächlich `"pace.zone"`, kein offenes Ziel). Pace-
Ziele werden intern immer in **m/s** übertragen; `speed.zone` (ID 5, km/h-Anzeige) und `pace.zone`
(ID 6, min/km-Anzeige) unterscheiden sich zusätzlich in der Reihenfolge von `targetValueOne`/Two
(bei `pace.zone`: One = schnellere, Two = langsamere Grenze - umgekehrt zu `speed.zone`).
`workout_builder.py` verwendet ausschließlich `pace.zone`. Für mehrsegmentige Workouts, die nicht
in die generische Signatur passen, werden die Low-Level-Bausteine (`_build_step`,
`_zone_pace_bounds_m_s`, `_zone_range_pace_bounds_m_s` für Ziele über mehrere Zonen hinweg wie
"5b bis 5c") direkt in einem Testskript wiederverwendet (siehe `examples/test_workout_marathon_tempo.py`).

## Datei-Übersicht

| Datei | Zweck |
|---|---|
| `app.py` | Streamlit-Startseite (Begrüßung/Navigation, kein eigener Inhalt) |
| `db.py` | Zentrales Schema (`init_db()`, ~46 Tabellen) + generische Upsert-/Zeitreihen-Helper |
| `garmin_auth.py` | Token-gecachter Garmin-Login |
| `garmin_service.py` | Zentraler Tages-Sync (Kern- + alle Erweiterungsmetriken) |
| `garmin_backfill.py` | Mehrtägiger Backfill, ruft `garmin_service` pro Tag chronologisch auf |
| `garmin_explore.py` | Testweiser Abruf aller Tier-1/2-Endpunkte (Settings-UI, Debug/Exploration) |
| `garmin_activities.py` | Manueller Aktivitäten-Sync (Liste + optionale Sekunden-Details) |
| `activity_analytics.py` | Schicht 1, pro-Aktivität-Kennzahlen (Decoupling, HF-Drift, GAP, Brick-Erkennung) |
| `daily_summary.py` | Schicht 1, pro-Tag-Kennzahlen (Baselines, Trainingslast, CTL/ATL/TSB, Overreach) |
| `training_zones.py` | Friel-Trainingszonen (Lauf-HF/Pace, Rad-HF/Leistung) aus Schwellenwerten |
| `weekly_summary.py` | Schicht 2, pro-Woche-Kennzahlen |
| `insight_memory.py` | Schicht 3, nutzergeschriebenes Erkenntnis-Gedächtnis |
| `gemini_client.py` | Gemeinsame Gemini-Konfiguration (Key/Modell/Client) |
| `workout_builder.py` | Erstellt/lädt strukturierte Garmin-Workouts (Pace-/Zonen-Ziele) |
| `examples/test_workout_builder.py` | Beispiel: einfaches Intervall-Workout (build_interval_running_workout), `python3 -m examples.test_workout_builder` |
| `examples/test_workout_marathon_tempo.py` | Beispiel: mehrsegmentiges Workout mit Low-Level-Bausteinen |
| `pages/1_🏠_Home.py` | Tagesjournal (löst Journal-Integration aus), Trainingsbereitschaft, Schicht-1/2-Kennzahlen |
| `pages/2_📊_Health_Trends.py` | Renn-/Workout-Kalender, Endurance-Score, Trends nach Sportart |
| `pages/3_⚙️_Settings.py` | Sync (Einzel/Backfill), API-Exploration, Aktivitäten-Sync |
| `pages/4_🏃_Aktivitäten.py` | Aktivitäts-Liste/-Filter/-Detailcharts inkl. GPS-Route |
| `pages/5_🧠_Erkenntnisse.py` | UI für Schicht 3 (Einträge hinzufügen/löschen, aktueller Stand) |
| `pages/6_🏗️_Workout_Builder.py` | Formular zum Erstellen/Hochladen strukturierter Workouts |

## Datenbank (Auszug nach Kategorie, `db.py`)

- **Tages-Tabellen** (PK `date`, Upsert): `garmin_daily`, `garmin_training_readiness`,
  `garmin_max_metrics`, `garmin_sleep_phases`, `garmin_cycling_ftp`, `garmin_lactate_threshold`,
  `daily_summary` u.v.m. — rund 20 weitere Tier-1/2-Metrik-Tabellen (SpO2, Atmung, Hydration,
  Blutdruck, Endurance-/Hill-Score, Fitness-Alter, Rennprognosen, ...)
- **Zeitreihen-Tabellen** (mehrere Zeilen/Tag, Delete+Insert bei jedem Sync): Stress-, Body-
  Battery-, Herzfrequenz-, Atem-, Schritte-Zeitreihen, geplante Events/Rennen, Friel-Zonen-Snapshots
- **Aktivitäten:** `garmin_activities` (PK `activity_id`), `garmin_activity_details`
  (Sekunden-Zeitreihe), `activity_analytics`
- **Wochen/Sonstiges:** `weekly_summary` (PK `week_id`), `garmin_weigh_ins` (PK Garmins
  `sample_pk`), `garmin_personal_records`/`garmin_goals`/`garmin_training_plans` (PK Garmins `id`)
- **KI-bezogen:** `insight_memory_raw`, `insight_memory_compressed` (append-only), `daily_journal`
  (subjektive Nutzereingaben, PK `date`)

## Wichtige Konventionen

- **Upsert-Sicherheit:** jeder Save-Pfad nutzt `upsert_daily_metric()`/`upsert_by_key()`/
  `upsert_weigh_in()` (`ON CONFLICT DO UPDATE`) oder `replace_timeseries()` (Delete-by-date dann
  Insert) — nie ein nacktes `INSERT` ohne Konflikt-Behandlung. Dadurch ist mehrfacher Sync pro Tag
  sicher gegen Duplikate.
- **"Heute"-Gate vs. unconditional:** Account-weite Snapshots nur bei echtem Sync von "heute"
  neu berechnen (kein Sinn bei Backfill-Wiederholung); Tages-/Wochen-Kennzahlen dagegen immer.
- **Kein LLM in Schicht 1/2** — nur Schicht 3 ruft Gemini auf.
- **Aktivitäten-Sync ist bewusst manuell**, nie Teil des automatischen Tages-Syncs.
- **SQLite-CHECK-Constraints** lassen sich nicht per `ALTER TABLE` ändern - bei Bedarf (siehe
  `insight_memory_raw.source`) Tabelle umbenennen, neu anlegen, Daten kopieren, alte löschen.
- Deutsch als Code-Kommentar-/UI-Sprache durchgängig.

## Bekannte offene Baustellen / in Diskussion

- "Schicht 4" (der eigentliche KI-Chat auf Basis von Schicht 1-3) ist noch nicht begonnen.
