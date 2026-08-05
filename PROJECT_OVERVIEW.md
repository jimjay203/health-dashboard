# Projekt-Überblick: health-dashboard

Technischer Stand des Repos für die Arbeit mit einem KI-Assistenten (z.B. Claude Chat) außerhalb
von Claude Code — beschreibt, welche Dateien es gibt und welche Logik/Konventionen dahinterstecken,
damit Feature-Diskussionen ohne erneutes Codebase-Exploring starten können. Wird bei jedem
`git commit` mit inhaltlichen Änderungen aktuell gehalten.

**Zweck des Projekts:** Persönliches Trainings-Dashboard für einen Marathon-/Triathlon-Athleten
(SWB Marathon Bremen 13.09.2026, GEWOBA City Triathlon 09.08.2026). Synchronisiert Garmin-Connect-
Daten, speichert sie in SQLite, wertet sie regelbasiert aus, pflegt ein LLM-gestütztes
Wissens-Gedächtnis (Schicht 3) und bietet einen Chat (Schicht 4) mit Datenzugriff und
Workout-Erstellung. Streamlit-Multi-Page-App, Docker-Compose-Betrieb.

## Tech-Stack

Streamlit (Multi-Page, dateibasiertes Routing über `pages/`), SQLite über rohes `sqlite3` (kein
ORM), `garminconnect` (Garmin-API), `google-genai` (Gemini) für Schicht 3/4, Plotly/pydeck für
Charts/Karten, Docker Compose (`.:/app`-Volume-Mount, d.h. Code-Änderungen wirken ohne Rebuild).
Daneben eine **parallele FastAPI+React-App** (`backend/`/`frontend/`, siehe eigener Abschnitt
unten) als geplanter Rebuild - läuft als zweiter, unabhängiger Container neben dem
Streamlit-Service, ersetzt ihn noch nicht. Mittlerweile mehr als ein leeres Grundgerüst: die
Heute-Ansicht (Readiness-Dial, KI-Empfehlung, Metrik-Kacheln, Wochenstreifen) ist das erste echte
Feature dort.

## FastAPI+React-Rebuild

Neuer, komplett paralleler Service `dashboard-v2` (Port 8000) neben dem bestehenden `dashboard`
(Streamlit, Port 8501) - keiner der beiden beeinflusst den anderen, beide teilen sich nur
lesend/schreibend dieselbe SQLite-Datei über ein gemeinsames `./data`-Volume-Mount (nicht den
ganzen Repo-Ordner wie beim Streamlit-Service) sowie den Garmin-Session-Token-Cache über
`./garmin_tokens:/root/.garminconnect` (siehe `auto_sync.py`-Abschnitt unten - vermeidet einen
zweiten, unabhängigen Passwort-Login). `dashboard-v2` braucht dafür auch `env_file: .env`
(Garmin-Zugangsdaten für den seltenen Fallback-Login, falls kein gültiges Token im Cache liegt).

- **`backend/`** (FastAPI): `main.py` + Router in `routers/` (`daily_summary.py`,
  `sync_status.py`, `today.py`, `club_slots.py` - siehe jeweils eigener Abschnitt) und `GET
  /api/health`. **Layout-Besonderheit:** alle Root-Level-Module (`db.py`, `garmin_auth.py`,
  `garmin_service.py`, `auto_sync.py`, `daily_recommendation.py`, `training_slots.py`,
  `context_blocks.py`, ...) werden unverändert aus dem Repo-Root ins Container-Image kopiert
  (`COPY *.py .` im Dockerfile) und landen dort direkt neben `main.py` (nicht als Unterpaket
  importiert) - dadurch funktioniert z.B. `from db import get_connection` ohne jede Anpassung, und
  die relative `DB_PATH`-Auflösung (`"data/dashboard.db"`) passt unverändert, wenn `./data` an
  dieselbe Stelle gemountet wird. `backend/requirements.txt` ist bewusst von der bestehenden
  `requirements.txt` getrennt (eigener Container, aber inzwischen nicht mehr minimal -
  `garminconnect` und `google-genai` sind seit Auto-Sync-Trigger bzw. Heute-Ansicht auch hier
  nötig).
- **`frontend/`** (React + TypeScript + Vite, Standard-`react-ts`-Scaffold, kein CSS-Framework,
  keine Routing-Bibliothek): `App.tsx` schaltet per einfachem `useState` zwischen zwei Ansichten um
  (`TodayView`/`ClubSlotsSettings`, siehe "Heute-Ansicht"-Abschnitt unten) - bewusst kein
  `react-router-dom` für nur zwei Ansichten, kann bei mehr Seiten später nachgerüstet werden.
  `vite.config.ts` hat einen Dev-Proxy `/api → localhost:8000` für lokales `npm run dev` (Zugabe,
  im ursprünglichen Auftrag nicht gefordert, aber für die künftige Weiterentwicklung praktisch).
- **`backend/Dockerfile`**: Multi-Stage (Node-Stage baut `frontend/dist`, Python-Stage kopiert das
  Ergebnis nach `./static` und liefert es selbst über FastAPIs `StaticFiles(html=True)` aus - kein
  eigener Nginx-Container). Build-Context ist der Repo-Root (`docker-compose.yml`: `context: .,
  dockerfile: backend/Dockerfile`), damit `db.py` mit ins Image kopiert werden kann.
- **Bekannter, bewusst nicht behobener Punkt:** beide Container können potenziell gleichzeitig auf
  dieselbe SQLite-Datei zugreifen. War anfangs unkritisch (der Service las nur, selten, kurze
  Queries) - seit dem Auto-Sync-Trigger schreibt `dashboard-v2` jetzt aber täglich einmal
  (`auto_sync_status`, plus der volle Sync selbst). Weiterhin kein Deadlock/Korruptions-Risiko
  beobachtet (SQLite serialisiert Schreibzugriffe selbst), aber falls das später zum Problem wird,
  ist `PRAGMA journal_mode=WAL` in `db.py::get_connection()` die Standardlösung, noch nicht
  eingebaut.

### Auto-Sync-Trigger via Schlafdaten-Checker (`auto_sync.py`)

Zwischenschritt vor der künftigen Heute-Ansicht: ein Hintergrund-Task im `dashboard-v2`-Container,
der ab `AUTO_SYNC_START_TIME` (06:00) alle `AUTO_SYNC_CHECK_INTERVAL_SECONDS` (25 Min., bewusst
nicht enger - konsistent mit dem vorsichtigen 429-Handling) leichtgewichtig prüft, ob die heutigen
Schlafdaten vorliegen, und bei Treffer automatisch `fetch_and_store_garmin_data()` auslöst - ohne
sich morgens ans manuelle Anstoßen erinnern zu müssen. Bricht ohne Treffer um `AUTO_SYNC_CUTOFF_
TIME` (12:00) sichtbar ab ("gave_up"). Der bestehende manuelle Sync-Button in den Streamlit-
Settings bleibt unverändert als Fallback bestehen.

- **`check_sleep_data_available(client, target_date)`**: **Ground-Truth-Fund**, live gegen die
  echte API verifiziert - `client.get_sleep_data(date)` liefert **immer** ein `dailySleepDTO`-
  Objekt zurück, auch für Tage ganz ohne Daten, nur mit durchgehend `null`-Feldern. Der Check
  `"dailySleepDTO" in sleep_data` (wie in `garmin_service.py` für einen anderen Zweck genutzt)
  taugt deshalb NICHT als Verfügbarkeits-Signal. Zuverlässig: `dailySleepDTO.sleepTimeSeconds`
  (echter Sekundenwert vs. `None`/`0`) - dieselbe Feld-Konvention, die `garmin_service.py` bereits
  für `sleep_hours` nutzt. Ein 429 wird durchgereicht, alle anderen Fehler als `(False, "<Meldung>
  ")`.
- **`run_auto_sync_loop(...)`**: eine Tages-Schleife, alle Parameter (`start_time`, `cutoff_time`,
  `interval_seconds`, `check_fn`, `sync_fn`, `client_factory`, `now_fn`) mit Produktions-Default,
  aber austauschbar - macht die Funktion ohne Warten auf echte Uhrzeiten testbar (Fake-Uhr,
  Fake-Check-Funktion, siehe `examples/test_auto_sync.py`). Alle blockierenden Garmin-Aufrufe
  laufen über `asyncio.to_thread()`, sonst würde der FastAPI-Event-Loop während eines Syncs
  einfrieren. Ein 429 (egal ob beim Client-Aufbau oder beim eigentlichen Check) bricht die
  **gesamte Tages-Schleife** sofort ab (`_mark_check(..., error="429: ...")`, Status
  `"rate_limited"`) - kein Retry im selben Tag, konsistent mit dem bestehenden 429-Prinzip.
  `run_daily_auto_sync_forever()` ist ein dünner Dauerlauf-Wrapper darum (nötig, weil der
  `restart: unless-stopped`-Container potenziell wochenlang durchläuft) - prüft beim (Neu-)Start,
  ob der heutige Status schon abgeschlossen ist (Container-Neustart mitten am Tag), sonst startet
  er direkt; nach Tagesabschluss wird bis zum nächsten `start_time` geschlafen.
- **Neue Tabelle `auto_sync_status`** (PK `date`): `first_check_at`/`last_check_at`/`check_count`/
  `sleep_data_found`/`full_sync_completed_at`/`gave_up_at`/`last_error`. Schreibzugriffe über das
  bestehende `upsert_daily_metric()` (spaltengruppenweise, wie schon bei `daily_summary.journal_*`
  genutzt) - Check-Fortschritt und Abschluss-Zeitstempel sind unabhängige Spaltengruppen.
  `get_status(target_date=None)` liest die Zeile (oder einen "not_started"-Default) für den unten
  genannten Endpoint.
- **`backend/routers/sync_status.py`**: `GET /api/sync-status` (liest `auto_sync.get_status()`,
  plus abgeleitetes `status`-Feld: `not_started`/`checking`/`completed`/`gave_up`/`rate_limited`)
  und `POST /api/sync-trigger` (manueller Sofort-Trigger über die API, Ergänzung - kein Ersatz -
  zum Streamlit-Button). `backend/main.py` startet den Hintergrund-Task über den `lifespan`-
  Kontextmanager (moderne FastAPI-Variante statt veraltetem `on_event`).
- **Live end-to-end verifiziert** (nicht nur Fakes): kompletter Docker-Rebuild, Backend startete
  den Scheduler automatisch ohne manuellen Anstoß, ein echtes 429 während des ersten
  Passwort-Logins (ausgelöst durch gleichzeitigen Neustart beider Container nach der
  Token-Volume-Umstellung) wurde von `garmin_auth.py`s eigener Login-Methoden-Fallback-Kette
  abgefangen, der Sync lief danach automatisch durch und schrieb echte Daten in `garmin_daily`.

### Heute-Ansicht (Schritt 2): Empfehlungs-Engine, Vereins-Slots, Backend/Frontend

Erstes echtes Feature der neuen App: Readiness-Dial, KI-Empfehlung mit Begründung, vier
Metrik-Kacheln mit Sparklines, Wochenstreifen. Bewusster Neuaufbau, kein Wiederherstellen des
früher entfernten `ai_coach.py`.

- **`daily_recommendation.py`** (Repo-Root, kein `streamlit`-Import): `generate_daily_
  recommendation(target_date, override_value=None)` sammelt Kontext (heutige `daily_summary`-Zeile,
  aktuelle `weekly_summary`-Zeile, heutiger `daily_journal`-Eintrag, `insight_memory_compressed`
  nur lesend, heutige `garmin_scheduled_events` über `event_date` - **nicht** die Tabellenspalte
  `date`, die ist laut Schema-Kommentar ein Monats-Partitionsschlüssel) und ruft Gemini mit
  striktem `response_schema` auf (gleiches Muster wie `insight_memory.py::_compress`, plus
  zusätzlich eine `_strip_markdown_fences()`-Vorverarbeitung als Sicherheitsnetz). Ergebnis wird in
  einer **eigenen** Tabelle `daily_recommendation` (PK `date`) gecacht - **schreibt niemals** in
  `insight_memory_raw`/`insight_memory_compressed`, das bleibt ausschließlich für vom Nutzer selbst
  eingetragene Zusatzinfos reserviert (siehe Schicht-3-Abschnitt). `get_cached_recommendation()`
  liest den Cache; `set_override_and_regenerate(target_date, override_value)` schreibt in eine
  zweite neue Tabelle `daily_override` (PK `date`, `worse`/`better`/`neutral`) und generiert sofort
  mit diesem Zusatzkontext neu.
- **`context_blocks.py`** (neu, Repo-Root): `insight_memory_block(cursor)`/`daily_summary_block
  (cursor, target_date)` - aus `chat_engine.py` herausgelöste, wiederverwendbare Kontext-Bausteine
  (beide reine Lesefunktionen auf einem `sqlite3.Cursor`), jetzt von `chat_engine.py` UND
  `daily_recommendation.py` genutzt statt dupliziert.
- **`training_slots.py`** (neu, Repo-Root): CRUD für wiederkehrende Vereins-Trainingstermine
  (Tabelle `club_training_slots`, PK `id` AUTOINCREMENT, mehrere Slots pro Wochentag möglich).
  Handgeschriebenes SQL nach dem Vorbild von `insight_memory.py::add_raw_entry`/`delete_raw_entry`
  (kein `db.py`-Generic-Helper - die bestehenden Upsert-Helfer sind auf "ein Datensatz pro
  natürlichem Schlüssel" ausgelegt, nicht auf id-basiertes CRUD). `sport_type` ist auf eine feste
  Werteliste beschränkt (`Schwimmen`/`Laufen`/`Rad`/`Krafttraining`/`Mobility`) - validiert per
  Pydantic `Literal` in `backend/routers/club_slots.py::SportType` (kein SQLite-`CHECK`, das lässt
  sich nicht per `ALTER TABLE` nachträglich ändern, siehe Konventionen unten). Emoji-Zuordnung fürs
  Wochenstreifen-Icon lebt bewusst im Frontend (`api.ts::SPORT_TYPE_EMOJI`), nicht im Backend - rein
  präsentatorisch. `GET /api/week-strip` liefert bei `category="club"` zusätzlich das `sport_type`
  des Slots mit, damit das Frontend das passende Icon statt eines generischen Club-Symbols zeigt.
- **Auto-Sync-Integration:** `run_auto_sync_loop()` (siehe oben) ruft nach erfolgreichem Sync
  best-effort `recommendation_fn(target_date)` auf (Default `generate_daily_recommendation`, neuer
  austauschbarer Parameter im selben DI-Muster wie `check_fn`/`sync_fn`) - ein Gemini-Fehler kippt
  den bereits erfolgreichen Sync-Status nicht, wird nur geloggt. Ohne diesen Parameter würde
  `examples/test_auto_sync.py`s Fake-Orchestrierungstest bei jedem Lauf einen echten Gemini-Call
  auslösen; das Testskript nutzt daher einen Fake-`recommendation_fn`.
- **`backend/routers/today.py`** (neu, bündelt alle 5 Endpoints - einzeln zu klein für je eine
  eigene Datei): `GET /api/readiness/{date}` (liest `garmin_training_readiness`), `GET
  /api/trends/{date}?days=14` (liest `garmin_daily`: `avg_hrv`/`sleep_hours`/`resting_hr`/
  `body_battery_max` - **nur** `body_battery_max`, nicht `_min`, konsistent mit den anderen drei
  Kacheln als je ein Tageswert), `GET /api/daily-recommendation/{date}` (Cache-Read, bei Miss
  einmalig **Lazy-Fallback**-Generierung), `POST /api/daily-override/{date}` (Body
  `{override_value}`, gibt die frisch regenerierte Empfehlung direkt zurück), `GET
  /api/week-strip/{date}` (siehe Prioritätslogik unten). Alle als synchrone `def`-Handler wie
  `daily_summary.py` - FastAPI führt sie automatisch im Threadpool aus, kein
  `asyncio.to_thread()` nötig (anders als in `auto_sync.py`, das selbst im Event-Loop läuft).
- **Wochenstreifen-Priorität** (`GET /api/week-strip/{date}`, Mo-So-Fenster lokal per
  `isocalendar()` berechnet): pro Tag genau eine Kategorie nach fester Priorität - `race`
  (`garmin_scheduled_events`, `is_race=1`, `event_date`) schlägt `completed` (`garmin_activities`,
  `date(start_time_local)` - was tatsächlich passiert ist, ist informativer als der Plan) schlägt
  `club` (`club_training_slots`, passender `weekday` + `valid_from`/`valid_to`-Fenster) schlägt
  `rest` (Fallback). `is_today` ist ein **unabhängiges** Boolean-Feld, nicht Teil der Kette.
- **`backend/routers/club_slots.py`** (neu): `GET`/`POST`/`PUT /{slot_id}`/`DELETE /{slot_id}` auf
  `/api/club-slots`, dünne Pydantic-Wrapper um `training_slots.py`.
- **Frontend** (`frontend/src/`): `api.ts` (typisierte `fetch()`-Wrapper für alle 9 Endpoints),
  `TodayView.tsx` (Readiness-Dial als Inline-SVG mit `stroke-dasharray`, Zonenfarbe nach `level`;
  Empfehlungs-Panel mit den zwei Override-Buttons; vier Metrik-Kacheln mit handgerollten
  Inline-SVG-Sparklines aus `/api/trends`, kein Chart-Framework; Wochenstreifen mit Icon/
  Hervorhebung), `ClubSlotsSettings.tsx` (einfache Liste + Formular, lebt bewusst im neuen
  Frontend statt in der alten Streamlit-Settings-Seite - die hat aktuell ohnehin keinerlei
  CRUD-/Formular-Logik dieser Art). Styling in `App.css` (zuvor nie importiertes Vite-Boilerplate,
  jetzt durch echte, an den bestehenden CSS-Custom-Properties orientierte Styles ersetzt).
- **Live end-to-end verifiziert:** `generate_daily_recommendation()`/`set_override_and_regenerate()`
  gegen echte Daten, alle 9 Endpoints per `curl` (inkl. Lazy-Fallback bei geleertem Cache, Club-Slot
  landet korrekt im Wochenstreifen am richtigen Wochentag, Renn-Tag behält Priorität), Docker-Build
  inkl. Frontend-Build (`tsc -b && vite build`) fehlerfrei, Streamlit-App/alte Tabellen unverändert
  (`git diff` auf `pages/`/`garmin_service.py`/`app.py` leer). Kein automatisierter Browser-/
  Interaktionstest (kein Browser-Automatisierungswerkzeug verfügbar) - nur indirekt über
  API-Response-Form vs. TypeScript-Interfaces und erfolgreichen Asset-Abruf bestätigt.

## Sync-Architektur

`garmin_service.py::fetch_and_store_garmin_data(target_date=None, client=None)` ist der **eine
zentrale Einstiegspunkt** für alle Garmin-Kern-/Erweiterungsdaten eines Tages. Wird aufgerufen von:
- Settings-Seite, Einzel-Tages-Sync-Button
- `garmin_backfill.py::run_backfill()`, das ihn chronologisch vorwärts pro Tag im Zeitraum aufruft
- `auto_sync.py::run_auto_sync_loop()` (automatischer Trigger, sobald der leichtgewichtige
  Schlafdaten-Check "vorhanden" meldet - siehe eigener Abschnitt oben) und `POST /api/sync-trigger`
  (manueller API-Trigger, gleicher Codepfad)

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

## Withings-Integration (`withings_auth.py`/`withings_service.py`)

Garmin bekommt Waagen-Daten von einer Withings-Waage nur lückenhaft weitergeleitet - **live
verifiziert, kein Verdacht**: für mehrere Tage stand in `garmin_weigh_ins.weight` ein Wert wie
`82836` statt `82.836` (Faktor 1000, vermutlich ein Einheiten-Bug in Garmins Weiterleitung), exakt
für die Tage, an denen Withings selbst den korrekten Wert lieferte. Deshalb werden Waagen-Daten
jetzt zusätzlich **direkt bei Withings** abgeholt (eigene, vollständigere Werte: Körperfett %,
Muskelmasse, Wasseranteil, Knochenmasse, Fettmasse in kg - Dinge, die Garmin gar nicht oder falsch
durchreicht).

- **Ground-Truth-Fund, der die Umsetzung verändert hat:** die naheliegende Bibliothek
  `withings-api` (PyPI) verlangt `pydantic<2`, kollidiert damit hart mit `google-genai`
  (`pydantic>=2.12.5`) - ein Testinstall im laufenden Container hat `google.genai`
  tatsächlich unimportierbar gemacht (sofort erkannt und rückgängig gemacht). Withings wird
  deshalb **ohne SDK**, direkt per `requests` angesprochen - keine neue Abhängigkeit, kein
  Konflikt. Die exakten Endpunkte/Parameter/Antwortformate wurden trotzdem nicht geraten, sondern
  aus dem tatsächlich funktionierenden `withings-api`-Quellcode (GitHub) übernommen, nur ohne die
  Bibliothek selbst zu installieren.
- **`withings_auth.py`** (Repo-Root, kein `streamlit`-Import): OAuth2-Token-Caching unter
  `~/.withings_api/credentials.json` (analog zu `garmin_auth.py`s `~/.garminconnect`, geteiltes
  Docker-Volume `./withings_tokens`). `get_withings_tokens()` refresht abgelaufene Access-Tokens
  automatisch (Withings gibt bei jedem Refresh einen **neuen** `refresh_token` mit - der alte wird
  ungültig, daher wird bei jedem Refresh die komplette Datei neu geschrieben). Erst-Autorisierung
  ist ein einmaliger, zwingend interaktiver Schritt (Nutzer-Login+Zustimmung im Browser) - siehe
  `examples/withings_authorize.py`.
- **`withings_service.py`**: `fetch_and_store_withings_data(target_date)` holt Messwerte über
  `GET wbsapi.withings.net/measure` (bewusst der ältere Pfad ohne `/v2/`-Präfix - exakt der, den
  die Referenzbibliothek für Messwerte nutzt). Fragt das Zeitfenster einen Tag breiter als nötig
  an (Withings' `startdate`/`enddate` sind UTC-Unix-Zeitstempel, das lokale Tagesfenster kennt man
  erst aus der Antwort) und ordnet Messgruppen anhand der von Withings selbst gelieferten
  `timezone` dem richtigen Kalendertag zu. Messgruppen, bei denen keiner unserer erfassten
  Messtypen vorkommt (z.B. Herzfrequenz einer Impedanzwaage), werden übersprungen statt als
  leere Zeile gespeichert.
- Neue Tabelle `withings_weigh_ins` (PK Withings' `grpid`, eigene Tabelle statt Wiederverwendung
  von `garmin_weigh_ins` - andere PK-Domäne, andere Spaltenmenge, keine Garmin-eigenen
  Herleitungen wie `visceral_fat`/`metabolic_age` erfunden).
- **`daily_summary.py::_weight_vs_avg_pct`**: liest jetzt über `_weight_for_date()`/
  `_weight_series_for_range()` **Withings bevorzugt, Garmin als Fallback** - pro Tag genau ein
  Wert (vermeidet Doppelzählung an Tagen, an denen beide Quellen dieselbe physische Messung
  haben).
- **Sync-Trigger:** bewusst erstmal nur ein manueller Button in den Streamlit-Settings (wie der
  Aktivitäten-Sync) - noch nicht Teil des täglichen `auto_sync.py`-Loops.

## Die vier "Schichten" der KI-Chat-Vorbereitung

Aufbauender Kontext für den Chat (Schicht 4, siehe eigener Abschnitt unten):

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
  dauerhafte Athleten-Erkenntnisse zu sammeln. Die Gemini-generierte Tagesempfehlung der
  Heute-Ansicht (`daily_recommendation.py`, siehe "Heute-Ansicht"-Abschnitt oben) ist bewusst
  **kein** Teil von Schicht 3 - eigene Tabelle, liest `insight_memory_compressed` nur, schreibt nie
  hinein.

- **Schicht 4** (`chat_engine.py`): der eigentliche Chat, baut auf Schicht 1-3 und
  `workout_builder.py` auf. Siehe eigener Abschnitt unten.

`gemini_client.py` bündelt die Gemini-Konfiguration (API-Key, Modell, Client-Erzeugung) - Nutzer
sind `insight_memory.py` und `chat_engine.py`.

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

## Chat (`chat_engine.py`, Schicht 4)

`ChatEngine` (kein `streamlit`-Import) - ein Objekt = eine Konversation. `send_message(text) -> str`
ist der einzige öffentliche Einstiegspunkt, intern eine Gemini-Function-Calling-Schleife (max. 8
Runden) mit drei Tools:

- **`run_readonly_query(sql)`**: SELECT-only gegen eine feste Tabellen-Whitelist (`daily_summary`,
  `weekly_summary`, `insight_memory_compressed`, `garmin_activities`, alle drei
  `training_zones_*`-Tabellen) - separate Read-Only-Connection (`sqlite3.connect(...,
  mode=ro, uri=True)`), kein Semikolon/Chaining, Row-Limit 100, Wall-Clock-Timeout per
  `set_progress_handler`, `garmin_activities.raw_json` wird in der Ausgabe immer ausgeblendet. Bei
  jedem Fehler (verbotene Tabelle, Syntax, Timeout) ein verständlicher String statt Crash.
- **`propose_workout(...)`/`confirm_and_upload_workout(proposal_id)`**: dünne Wrapper um
  `build_interval_running_workout()`/`upload_workout()` aus `workout_builder.py`. **Turn-Trennung
  ist die kritischste Design-Entscheidung**: ein `_turn_counter` (erhöht sich NUR in
  `send_message()`, nie innerhalb der internen Function-Calling-Schleife) stempelt jeden
  `propose_workout`-Vorschlag; `confirm_and_upload_workout` lehnt jeden Versuch strukturell ab,
  bei dem `turn_id` des Vorschlags == aktueller `turn_id` ist - unabhängig vom System-Prompt-Text
  und unabhängig davon, ob Gemini parallele Function-Calls in einer Antwort probiert. Live
  verifiziert: `types.Tool(function_declarations=[...])` (Schema-Objekte statt echter Python-
  Callables) löst kein automatisches SDK-Chaining aus, war aber laut Team-Entscheidung trotzdem
  nicht als alleinige Absicherung ausreichend.
- Vorschläge (`_pending_proposals`) leben bewusst nur im `ChatEngine`-Objekt (Session-Zustand,
  nicht DB) - anders als `chat_history` (Konversation selbst, PK `id`, append-only, `role`
  `user`/`assistant`, `tool_calls_json`), die bewusst in der DB liegt, damit beim künftigen
  FastAPI-Umbau kein Streamlit-`session_state` migriert werden muss.

Kontext pro Nachricht (System Instruction, bei jedem `send_message()` neu zusammengesetzt, da
Gemini-Calls zustandslos sind): kompakte Tabellen-Beschreibung der Whitelist (Spalten live per
`PRAGMA table_info`, Beschreibungstext hartkodiert), kompletter `insight_memory_compressed`-Text,
heutige `daily_summary`-Zeile falls vorhanden - explizit NICHT die volle Datenhistorie (dafür ist
`run_readonly_query` da). UI: `pages/7_💬_Chat.py` (hält die `ChatEngine` in `st.session_state`,
zeigt `tool_calls_json` je Antwort in einem Debug-Expander). CLI-Alternative: `examples/chat_cli.py`.

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
| `chat_engine.py` | Schicht 4: `ChatEngine` mit Function-Calling (Query-Tool, Workout-Vorschlag/-Upload) |
| `auto_sync.py` | Automatischer Sync-Trigger: leichtgewichtiger Schlafdaten-Checker + Tages-Loop, löst `fetch_and_store_garmin_data()` und `generate_daily_recommendation()` aus |
| `context_blocks.py` | Wiederverwendbare Gemini-Kontext-Bausteine, geteilt von chat_engine.py und daily_recommendation.py |
| `daily_recommendation.py` | Heute-Ansicht: Gemini-generierte Tagesempfehlung inkl. Override-Regenerierung |
| `training_slots.py` | CRUD für wiederkehrende Vereins-Trainingstermine (club_training_slots) |
| `withings_auth.py` | Withings-OAuth2-Token-Caching per requests (kein SDK, siehe Ground-Truth-Fund oben) |
| `withings_service.py` | Holt Withings-Waagen-Messwerte direkt (Körperfett/Muskelmasse/Wasseranteil/Knochenmasse) |
| `examples/test_workout_builder.py` | Beispiel: einfaches Intervall-Workout (build_interval_running_workout), `python3 -m examples.test_workout_builder` |
| `examples/test_workout_marathon_tempo.py` | Beispiel: mehrsegmentiges Workout mit Low-Level-Bausteinen |
| `examples/chat_cli.py` | Terminal-Testskript für chat_engine.py, `python3 -m examples.chat_cli` |
| `examples/test_auto_sync.py` | Testskript für auto_sync.py: echter API-Ground-Truth-Test + Fake-Orchestrierungstest, `python3 -m examples.test_auto_sync` |
| `examples/withings_authorize.py` | Einmaliger interaktiver OAuth2-Autorisierungs-Flow, `python3 -m examples.withings_authorize` |
| `pages/1_🏠_Home.py` | Tagesjournal (löst Journal-Integration aus), Trainingsbereitschaft, Schicht-1/2-Kennzahlen |
| `pages/2_📊_Health_Trends.py` | Renn-/Workout-Kalender, Endurance-Score, Trends nach Sportart |
| `pages/3_⚙️_Settings.py` | Sync (Einzel/Backfill), API-Exploration, Aktivitäten-Sync, Withings-Sync |
| `pages/4_🏃_Aktivitäten.py` | Aktivitäts-Liste/-Filter/-Detailcharts inkl. GPS-Route |
| `pages/5_🧠_Erkenntnisse.py` | UI für Schicht 3 (Einträge hinzufügen/löschen, aktueller Stand) |
| `pages/6_🏗️_Workout_Builder.py` | Formular zum Erstellen/Hochladen strukturierter Workouts |
| `pages/7_💬_Chat.py` | UI für Schicht 4 (ChatEngine in st.session_state, Tool-Aufruf-Debug-Expander) |
| `backend/main.py` | FastAPI-Rebuild Schritt 1: Einstiegspunkt, bindet Router + StaticFiles, startet den Auto-Sync-Hintergrund-Task |
| `backend/routers/daily_summary.py` | `GET /api/daily-summary/{date}` (liest daily_summary direkt) |
| `backend/routers/sync_status.py` | `GET /api/sync-status`, `POST /api/sync-trigger` (siehe auto_sync.py) |
| `backend/routers/today.py` | Heute-Ansicht: readiness/trends/daily-recommendation/daily-override/week-strip (5 Endpoints) |
| `backend/routers/club_slots.py` | CRUD auf /api/club-slots (siehe training_slots.py) |
| `frontend/src/App.tsx` | Ansichtsumschalter (Heute/Einstellungen), kein Routing |
| `frontend/src/TodayView.tsx` | Heute-Ansicht: Readiness-Dial, Empfehlungs-Panel, Metrik-Kacheln, Wochenstreifen |
| `frontend/src/ClubSlotsSettings.tsx` | Einfache Liste + Formular für Vereins-Trainingstermine |
| `frontend/src/api.ts` | Typisierte fetch()-Wrapper für alle Backend-Endpoints |

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
  `sample_pk`), `withings_weigh_ins` (PK Withings' `grpid`, siehe Withings-Integration-Abschnitt
  oben), `garmin_personal_records`/`garmin_goals`/`garmin_training_plans` (PK Garmins `id`)
- **KI-bezogen:** `insight_memory_raw`, `insight_memory_compressed` (append-only), `daily_journal`
  (subjektive Nutzereingaben, PK `date`), `chat_history` (Schicht-4-Konversation, append-only)
- **Auto-Sync:** `auto_sync_status` (PK `date`, siehe `auto_sync.py`-Abschnitt oben)
- **Heute-Ansicht:** `daily_recommendation`/`daily_override` (PK `date`), `club_training_slots`
  (PK `id` AUTOINCREMENT, siehe "Heute-Ansicht"-Abschnitt oben)

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

- `pages/7_💬_Chat.py` hält die `ChatEngine`-Instanz in `st.session_state` (Turn-Zähler/
  Vorschläge sind Objektzustand, siehe oben) - ein Browser-Reload startet also eine neue
  Konversation im Sinne von `_pending_proposals`/`_turn_counter`, auch wenn `chat_history` in der
  DB weiterhin den alten Verlauf anzeigt. Bekannte, akzeptierte Eigenschaft, kein Bug.
- FastAPI+React-Rebuild hat mit der Heute-Ansicht das erste echte Feature (siehe eigener Abschnitt
  oben), ist aber weiterhin nur ein Ausschnitt der gesamten Streamlit-App. `dashboard-v2` ersetzt
  den Streamlit-Service noch nicht.
- Gleichzeitiger DB-Zugriff beider Container ist unkritisch, aber noch nicht mit WAL-Modus
  abgesichert (siehe FastAPI-Abschnitt oben) - Vorschlag steht im Raum, noch nicht umgesetzt.
- Frontend-Navigation ist ein einfacher `useState`-Umschalter ohne Routing-Bibliothek (siehe
  FastAPI-Abschnitt oben) - bewusste Entscheidung für aktuell zwei Ansichten, sollte bei weiteren
  Seiten auf `react-router-dom` o.ä. umgestellt werden.
- Die Heute-Ansicht wurde nicht in einem echten Browser visuell getestet (kein
  Browser-Automatisierungswerkzeug in dieser Session verfügbar) - nur indirekt über
  API-Response-Form vs. TypeScript-Interfaces, erfolgreichen Docker-Frontend-Build und
  Asset-Abruf bestätigt. Manueller Blick ins Frontend unter localhost:8000 steht noch aus.
