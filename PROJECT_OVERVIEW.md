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
Streamlit-Service, ersetzt ihn noch nicht. Mittlerweile deutlich mehr als ein leeres Grundgerüst:
vier echte Seiten (Heute/Woche/Leistung/Einstellungen) mit eigener Sidebar-Navigation, einem
konsistenten Design-System (Typografie-/Radius-Skala, Material-Symbols-Icons, Light/Dark/System-
Theme, responsive für mobile Breiten) und einer umfangreichen Leistungsdiagnostik-Seite (siehe
eigene Abschnitte unten).

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

Erstes echtes Feature der neuen App: Readiness-Dial, KI-Empfehlung mit Begründung. Bewusster
Neuaufbau, kein Wiederherstellen des früher entfernten `ai_coach.py`.

**Seither vereinfacht:** die ursprünglichen vier Metrik-Kacheln mit Sparklines wurden komplett
entfernt (`Sparkline.tsx`, `fetchTrends`/`GET /api/trends/{date}` gelöscht - tote Code-Entfernung,
kein Ersatz gebaut, die relevanten Werte stehen jetzt auf der Leistung-Seite). Das
Rolling-Horizon-Kalender-Widget wurde auf eine eigene **"Woche"-Seite** ausgelagert
(`WeekView.tsx`, eigener Sidebar-Eintrag) statt auf der Heute-Seite mitzulaufen. Die Heute-Seite
zeigt seitdem nur noch zwei Karten nebeneinander: **Trainingsbereitschaft** (Readiness-Gauge +
KI-Empfehlung inkl. Override-Buttons, siehe unten) und **HRV & Ruhepuls** (siehe
Leistung-Seiten-Abschnitt weiter unten - dieselbe `readiness-overview`-Datengrundlage, nur anders
angeordnet).
- **Override-Buttons ("Fühle mich besser/schlechter"):** stoßen `POST /api/daily-override/{date}`
  an, das `daily_recommendation.py::set_override_and_regenerate()` aufruft - Override wird in
  `daily_override` gespeichert, danach wird die komplette Tagesempfehlung mit einem zusätzlichen
  Kontext-Satz ("Der Athlet fühlt sich heute BESSER/SCHLECHTER als die Kennzahlen suggerieren")
  neu bei Gemini angefragt. Kein manuelles Überschreiben des Readiness-Scores selbst (der bleibt
  Garmins berechneter Wert) - nur die Empfehlung reagiert auf das subjektive Feedback. Frontend
  blendet Empfehlungssatz/Begründungs-Bullets während der Neuberechnung auf reduzierte Deckkraft
  ab (1,2s CSS-Transition) und wieder ein, plus ein "wird neu berechnet…"-Hinweis mit drehendem
  Icon - reine UX-Rückmeldung, keine Server-Logik.

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
- **`backend/routers/today.py`**: `GET /api/daily-recommendation/{date}` (Cache-Read, bei Miss
  einmalig **Lazy-Fallback**-Generierung), `POST /api/daily-override/{date}` (Body
  `{override_value}`, gibt die frisch regenerierte Empfehlung direkt zurück), `GET
  /api/week-strip/{date}` (siehe Prioritätslogik unten - aktuell ungenutzt vom Frontend, aber
  nicht entfernt). `GET /api/readiness/{date}` und `GET /api/trends/{date}` wurden entfernt
  (siehe "Heute-Ansicht seither vereinfacht" oben) - Readiness/HRV/Ruhepuls laufen jetzt über
  `backend/routers/performance.py::readiness-overview` (siehe Leistung-Seiten-Abschnitt unten).
  Alle als synchrone `def`-Handler wie
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
- **Frontend** (`frontend/src/`): `api.ts` (typisierte `fetch()`-Wrapper für alle Backend-
  Endpoints), `TodayView.tsx` (Readiness-Gauge jetzt über `ReadinessGauge.tsx`, Chart.js-Doughnut
  statt Hand-SVG, siehe Leistung-Seiten-Abschnitt unten für den Chart.js-Umstieg allgemein;
  Empfehlungs-Panel mit den zwei Override-Buttons - Metrik-Kacheln/Sparklines/Wochenstreifen siehe
  "seither vereinfacht" oben), `ClubSlotsSettings.tsx` (einfache Liste + Formular, lebt bewusst im
  neuen Frontend statt in der alten Streamlit-Settings-Seite - die hat aktuell ohnehin keinerlei
  CRUD-/Formular-Logik dieser Art; mittlerweile als `<tfoot>`-Zeile derselben Tabelle statt eines
  separaten Formulars darunter, siehe Design-System-Abschnitt unten). Styling in `App.css`
  (zuvor nie importiertes Vite-Boilerplate, jetzt durch echte, an den bestehenden
  CSS-Custom-Properties orientierte Styles ersetzt, seitdem mehrfach um ein konsistentes
  Design-System erweitert, siehe eigener Abschnitt unten).
- **Live end-to-end verifiziert (damals):** `generate_daily_recommendation()`/`set_override_and_regenerate()`
  gegen echte Daten, alle Endpoints per `curl` (inkl. Lazy-Fallback bei geleertem Cache, Club-Slot
  landet korrekt im Wochenstreifen am richtigen Wochentag, Renn-Tag behält Priorität), Docker-Build
  inkl. Frontend-Build (`tsc -b && vite build`) fehlerfrei, Streamlit-App/alte Tabellen unverändert
  (`git diff` auf `pages/`/`garmin_service.py`/`app.py` leer). Kein automatisierter Browser-/
  Interaktionstest (kein Browser-Automatisierungswerkzeug verfügbar) - nur indirekt über
  API-Response-Form vs. TypeScript-Interfaces und erfolgreichen Asset-Abruf bestätigt.

## Design-System & Navigation (Frontend)

Späterer, umfangreicher Cleanup-Durchgang über die gesamte React-App (Typografie, Farben, Icons,
Navigation, Responsive) - betrifft `frontend/src/index.css`/`App.css` app-weit, nicht nur einzelne
Seiten.

- **Typografie-/Radius-Skala** (`index.css`): feste CSS-Custom-Property-Stufen statt beliebiger
  px-Werte pro Stelle - `--text-2xs` (11px) bis `--text-xl` (28px), plus `--text-display` (28px,
  für große Kennzahlen wie den Readiness-Score) und `--text-headline` (22px, für die
  Empfehlungs-Kernaussage - bewusst kein eigenes Überschriften-Level). `--radius-sm/md/lg/pill`
  analog. **Überschriften-Hierarchie app-weit fest zugeordnet:** h1 = Seitentitel (TopBar, genau
  einmal pro Seite), h2 = Abschnitts-Überschrift (gruppiert mehrere Karten), h3 = Karten-Titel
  (genau einer pro Karte) - keine Ausnahmen, jede Karte/jedes Settings-Formular nutzt konsequent
  h3, auch wenn sie visuell wie ein Abschnitt wirken (z.B. "Diese Woche" im Kalender-Widget lief
  vorher fälschlich als h2).
- **Material Symbols statt Emoji** (`Icon.tsx`, npm-Paket `material-symbols`, self-hosted -
  bewusst keine Google-Fonts-CDN-Abhängigkeit): Ligature-Icons per `<Icon name="..." />`, ersetzt
  alle bunten Emoji-Zeichen app-weit (Sidebar-Navigation, Sportart-Icons, Renn-/Ruhetag-Icons,
  Theme-Toggle, Sync-Button, Badges). `SPORT_TYPE_ICON` in `api.ts` (vorher `SPORT_TYPE_EMOJI`)
  mappt die festen `SPORT_TYPES`-Werte auf Icon-Namen.
- **Einklappbare Sidebar** (`sidebarCollapsed.ts`, gleiches Hook-Muster wie `theme.ts::useTheme()`,
  localStorage-persistiert): eingeklappt bleiben nur die Icons sichtbar, Toggle-Button unten in der
  Sidebar.
- **Einheitliche Akzentfarbe:** `--accent` ist app-weit (Light/Dark/System/explizit) auf `#3dd68c`
  vereinheitlicht - dieselbe Farbe wie `LEVEL_COLORS.HIGH` im Trainingsbereitschaft-Gauge
  (`ReadinessGauge.tsx`), vorher wich vor allem der Hellmodus (`#16a34a`) sichtbar davon ab.
  Dieselbe Grün/Orange/Rot-Ampel (`--accent` / `#f5a623` / `#e5484d`) wird durchgängig für
  Status-Kacheln, Chart-Farben (siehe Leistung-Seiten-Abschnitt unten) und die Override-Buttons
  verwendet - kein separates Farbschema pro Komponente. Pillen (`.status-pill`, `.day-score-pill`)
  sind auf dieselbe Optik angeglichen (Rand+Text in der Statusfarbe, halbtransparente Füllung
  derselben Farbe als Hintergrund, per `${color}1a`-Hex-Suffix-Technik berechnet, kein
  fixes `--accent-bg` für dynamisch eingefärbte Pillen).
- **Responsive/Mobile:** ein Breakpoint bei 768px - Sidebar erzwingt Icon-only-Darstellung
  (unabhängig vom manuellen Einklapp-Status), reduziertes `.main-content-body`-Padding,
  zweispaltige Kartenreihen brechen auf eine Spalte um, Tabellen (`.club-slots-table`) bekommen
  horizontales Scrollen.
- **"Woche"-Seite** (`WeekView.tsx`, eigener Sidebar-Eintrag): das Rolling-Horizon-Kalender-Widget
  lief anfangs auf der Heute-Seite mit, wurde aber auf eine eigene Seite ausgelagert (siehe
  "Heute-Ansicht seither vereinfacht" oben).
- **Konsistente Rahmen-/Abgrenzung statt Kästen:** Unterabschnitte innerhalb einer Karte (z.B.
  Diagnostik/Ziel-Tracking/Wettkampf-Prognose auf der Leistung-Seite, siehe unten) werden per
  `border-top`-Trennlinie abgegrenzt, nicht per eigenem grauem Hintergrund-Kasten - gleiches
  Prinzip wie die Tier-Trennung im Kalender-Widget (`.calendar-tier`). Die Trennlinie läuft dabei
  über einen negativen Rand bis zum Kartenrand durch (kompensiert das Karten-Padding), statt an der
  inneren Polsterung zu stoppen.

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

## Rolling-Horizon-Wochenplaner (`weekly_planner.py`)

Löst die frühere offene Design-Frage "wie kommt man von Trainingsphase/CTL-ATL-TSB/Erkenntnis-
Gedächtnis zu konkreten Wocheninhalten". Läuft **sonntags**, nachdem der tägliche Auto-Sync
erfolgreich war (siehe `auto_sync.py`-Abschnitt oben), generiert für die **kommenden zwei Wochen**
(Mo-So, jeweils zwei Sonntage im Voraus - siehe Sonntags-Trigger unten) pro Tag einen Vorschlag
inkl. Workout-Entwürfen für Lauf-Tage. Nutzt bewusst nur real vorhandene Signale
(`daily_summary.overreach_flag` statt eines noch nicht gebauten Frühwarnsystems, keine
Ziel-Intensitätsverteilung) - Signal-Sammlung ist klar von der Gemini-Aufruf-Logik getrennt, damit
sich weitere Signale später nachrüsten lassen.

**Vier Kalender-Ebenen** im Frontend (`WeeklyCalendarWidget.tsx`), zunehmend gröber je weiter in
der Zukunft: **Diese Woche** (volle Detailtiefe, mit Workout-Entwürfen), **Nächste Woche** und
**Übernächste Woche** (dieselbe echte, Gemini-generierte `weekly_plan`-Datengrundlage wie "Diese
Woche" - der Sonntags-Trigger bereitet sie ohnehin vor, siehe unten - aber reduziert dargestellt:
Icon + kurzes Stichwort ohne Klammer-Begründung, eine auf Viertel-/Halbstunden-Schritte gerundete
Dauer statt exakter Werte, keine Zone/Distanz, keine Action-Buttons), **ab Woche 4** (ein Balken
pro Woche bis einschließlich der Woche des nächsten Rennens, die letzte Zeile benennt Wettkampf +
Datum statt nur der Trainingsphase - siehe `get_far_weeks_outlook()` unten). Jeder Tag zeigt
zusätzlich sein Kalenderdatum, jede Wochen-Überschrift die ISO-Kalenderwoche (KW) + Datumsbereich
(`formatShortDate()` in `api.ts` - reines String-Slicing auf dem bereits bekannten ISO-Datum, kein
`new Date(isoString)`, siehe Datums-Konvention weiter unten).

- **Bugfix - Trainingsphase pro Woche einzeln berechnet:** "Nächste Woche"/"Übernächste Woche"
  zeigten anfangs fälschlich dieselbe Phase wie "Diese Woche" (ein einziger, geteilter `phase`-Wert
  wurde an alle Tiers durchgereicht). `get_week_phase(reference_date)` (neu in `weekly_planner.py`,
  Kernlogik in `_week_phase(cursor, week_start)` für interne Wiederverwendung) berechnet die Phase
  jetzt **pro Woche einzeln**, anhand des **eigenen Wochenstarts** dieser Woche als Referenz für
  die "nächstes Rennen ab hier"-Suche (`weekly_summary.py::_days_until_next_race()` wiederverwendet,
  nicht dupliziert) - Taper/Peak wie gehabt datumsbasiert projizierbar; jenseits beider Schwellen
  bewusst **"Build" als Default** (anders als `get_far_weeks_outlook()`, das dort `None` zeigt - für
  den nahen Horizont von Woche 2-3 ist "Aufbauwoche" eine vernünftige Standardannahme, für den viel
  unsichereren Horizont ab Woche 4 nicht). `WeeklyPlanResponse` bekam dafür ein `training_phase`-
  Feld, das jede der drei Wochen-Ebenen für ihre eigene Woche abfragt. Live verifiziert: KW32
  (Diese Woche) Taper, KW33 (Nächste Woche) Build, KW34 (Übernächste Woche) Peak.
- **Bugfix/Erweiterung - Phase beeinflusst jetzt tatsächlich die generierten Inhalte:** vor diesem
  Fix bekam das Modell die Trainingsphase gar nicht explizit mitgeteilt (nur indirekt über den
  Renn-Countdown erschließbar) - aufeinanderfolgende Wochen mit unterschiedlicher Phase erzeugten
  dadurch nahezu wortgleiche Vorschläge (z.B. identischer Long Run in einer Build- und einer
  Peak-Woche). Neuer Kontext-Block `_training_phase_block()` nennt die Phase jetzt explizit samt
  konkreter Handlungsanweisung (`PHASE_GUIDANCE`-Dict: Build = Umfang/Long-Run gezielt steigern,
  Peak = renn-spezifische Tempoabschnitte einbauen, Taper = Umfang reduzieren, Base = durchgehend
  Zone 1-2), SYSTEM_PROMPT verlangt jetzt explizit erkennbare Unterschiede zwischen Wochen
  unterschiedlicher Phase. Live verifiziert: KW33 (Build) generierte einen 120min/20km
  Zone-2-Dauerlauf, KW34 (Peak) einen 130min/22km langen Lauf **mit Marathon-Pace-Intervallen** in
  Zone 3 - klar unterscheidbare, nachvollziehbare Progression statt der vorherigen fast identischen
  Vorschläge.
- **Erweiterung - Kern- vs. flexible Einheiten (`is_key_session`):** neue optionale
  `weekly_plan`-Spalte (`NULL` = Wettkampftag/nicht bewertbar, sonst vom Modell im selben
  Gemini-Aufruf mitgeneriert, kein zusätzlicher Call). Einstufungskriterien bewusst phasenabhängig
  statt hart an Sportart/Session-Typ festgemacht (siehe SYSTEM_PROMPT): der lange Lauf/die
  renn-spezifische Qualitätseinheit ist in Build-/Peak-Wochen meist Kern, in Base-Wochen oder weit
  vor dem Rennen oft flexibler; Regenerations-/Technik-Einheiten sind unabhängig von der Phase in
  aller Regel flexibel; auch feste Vereinstermine können Kern sein, wenn die Phase genau darauf
  aufbaut (z.B. Bahntraining in einer Intervall-fokussierten Phase) - vom Modell eingeschätzt, nicht
  hart verdrahtet. Visuell zurückhaltend umgesetzt: in der reduzierten Ansicht (Nächste/Übernächste
  Woche) wird die komplette Tages-Karte (Icon+Stichwort+Dauer) in Akzentfarbe statt der gedämpften
  Sekundärfarbe dargestellt; in "Diese Woche" ein dezentes Badge (⭐ Kern-Einheit), gleicher Stil wie
  das bestehende "✅ Hochgeladen"-Badge.
- **Nächste Woche zeigt wieder die echte, Gemini-generierte `weekly_plan`-Datengrundlage** (eine
  frühere Zwischenversion hatte "Nächste Woche"/"Übernächste Woche" testweise auf eine rein
  heuristische, phasen-blinde "häufigstes historisches Muster"-Andeutung umgestellt
  (`get_week_outlook()`/`_typical_weekday_pattern()`, kein Gemini-Call) - das erklärte auch, warum
  KW33/KW34 zuvor wortgleiche Inhalte zeigten: die Heuristik kennt gar keine Wochen-/Phasen-
  Unterscheidung, sondern liefert für einen Wochentag immer dasselbe historische Muster. Diese
  Funktionen wurden wieder entfernt (inkl. `GET /api/week-outlook/{date}` und `GET
  /api/training-outlook`, siehe unten) - der konkrete Gemini-Plan inkl. Workout-Entwürfen wird vom
  Sonntags-Trigger ohnehin zwei Sonntage im Voraus vorbereitet (siehe unten), jetzt wird er auch
  direkt (reduziert) angezeigt, statt ungenutzt in der DB zu liegen, bis die Woche zu "Diese Woche"
  wird.

- **Ground-Truth-Fund:** `weekly_summary` wird ausschließlich rückwirkend befüllt (ein
  Wochen-Eintrag entsteht erst, sobald mind. ein Tag dieser Woche synchronisiert wurde) - für die
  kommende Woche existiert beim Sonntags-Lauf noch kein Eintrag. Der Planer liest deshalb die
  **zuletzt abgeschlossene** Woche (Ist-Zustand) und überlässt die Projektion "welche Phase
  sollte die kommende Woche haben" dem Gemini-Kontext (Renn-Countdown + CTL/ATL/TSB-Trend) -
  keine erfundene "Phase der kommenden Woche".
- **Signal-Sammlung** (`_gather_weekly_context`): zuletzt abgeschlossene `weekly_summary`,
  14-Tage-CTL/ATL/TSB-Trend, aktuellstes `overreach_flag`, feste Club-Slots der kommenden Woche
  (inkl. optionalem `typical_character`-Freitext, siehe unten), `insight_memory_block()` aus
  `context_blocks.py` (wiederverwendet, nicht dupliziert), Renn-Countdown. **Compliance-Vergleich
  Vorwoche** (geplant aus `weekly_plan` vs. tatsächlich aus `garmin_activities`) wird bei
  fehlendem Vorwochen-Plan bewusst ausgelassen (kein Nullen-Fallback) - z.B. beim allerersten Lauf.
- **Club-Slot-Tage sind nicht ausgeschlossen:** Sportart und "dass überhaupt eine Einheit
  stattfindet" sind fix (`is_club_slot=1`), Session-Typ/Fokus bestimmt das Modell trotzdem selbst,
  passend zum `typical_character`-Hinweis (z.B. "Bahntraining: meist Intervalle") UND zum
  aktuellen Kontext (z.B. in einer Taper-Woche trotz Bahntraining nur eine kurze
  Aktivierungseinheit) - exakt das Prinzip aus `daily_recommendation.py`, nur eine Woche im
  Voraus. `club_training_slots` hat dafür eine neue optionale `typical_character`-Spalte
  (Settings-UI in `ClubSlotsSettings.tsx` entsprechend ergänzt).
- **Antwort-Validierung, zwei live gefundene Lücken behoben:** das Modell gab anfangs
  `target_zone="Z4-Z5"` (Bereich mit "Z"-Präfix, passt nicht zu `training_zones_running.zone`)
  und `sport_type="Radfahren"` (Synonym statt der festen `SPORT_TYPES`-Werte) zurück - beide
  Werte werden im System-Prompt jetzt explizit auf die exakte, in der App verwendete
  Werteliste beschränkt.
- **Wettkampftage bekommen nie ein Training vorgeschlagen** (`_race_days_for`/Override in
  `generate_weekly_plan`) - **Code-Garantie, nicht nur Prompt-Anweisung**: unabhängig davon, was
  das Modell für einen Renntag zurückgibt, wird die Zeile programmatisch auf `sport_type=None`,
  `session_type="Wettkampf: <Titel>"`, `source="race"` überschrieben (dadurch automatisch auch
  kein Workout-Entwurf, da `_build_workout_drafts` nur bei `sport_type="Laufen"` baut). Der
  Renntag wird dem Modell trotzdem im Kontext genannt, damit die umliegenden Tage (Taper davor,
  Regeneration danach) sinnvoll mitgeplant werden. Live am echten Renntermin (14. GEWOBA City
  Triathlon, 09.08.2026) verifiziert.
- **Workout-Entwürfe** (`weekly_plan_workout_draft`, nur für `sport_type="Laufen"` - siehe
  Sport-Abdeckung von `workout_builder.py` unten): einfache Stichwort-Heuristik
  (intervall/tempo/schwellen/wiederholung im `session_type`-Text) entscheidet zwischen
  `build_interval_running_workout()` (feste, sinnvolle Default-Struktur: 5x1000m, der Wochenplan
  liefert nur ein Gesamt-Zielvolumen, keine Intervall-Feinstruktur) und der neuen
  `build_steady_running_workout()` (ein einzelner Schritt ohne Warmup/Cooldown - es gab dafür
  bisher **keine** Funktion in `workout_builder.py`, nur Templates mit erzwungenem
  Warmup+Intervalle+Cooldown; die meisten Lauf-Tage sind aber lockere Dauerläufe, keine
  Intervalle). **Speichert bewusst nicht das gebaute Workout-Objekt**, sondern
  `builder_name`+`builder_params_json` - wird bei Upload/Vorbefüllung frisch neu gebaut
  (robuster als Objekt-Serialisierung, dieselben Parameter dienen direkt als Formular-Vorbefüllung).
  Rad/Schwimm/Krafttraining/Mobility/Ruhetage bekommen bewusst keinen Entwurf (kein
  Support in `workout_builder.py`).
- **Sonntags-Trigger, deckt zwei Wochen ab:** kein neuer Scheduler -
  `auto_sync.py::run_daily_auto_sync_forever()` bekommt nach einem erfolgreichen Tages-Sync eine
  zusätzliche Sonntags-Prüfung (`_maybe_run_weekly_planner`), die **beide** anstehenden Wochen
  (kommende + übernächste) prüft/generiert. Idempotenz-Check pro Woche direkt gegen `weekly_plan`
  selbst (kein zusätzliches Tracking nötig) - dadurch bekommt jede Woche genau einmal einen Plan,
  zwei Sonntage vor ihrem Montag, statt kurz davor noch einmal überschrieben zu werden (würde
  sonst bereits hochgeladene/angepasste Entwürfe verwerfen). Best effort wie der bestehende
  `recommendation_fn`-Aufruf.
- **`pages/6_🏗️_Workout_Builder.py` erweitert:** unterstützte bisher nur Intervall-Workouts -
  jetzt zusätzlich ein "Durchgehend"-Modus (`build_steady_running_workout`). Liest
  `st.query_params.get("draft_id")` für die Vorbefüllung aus einem Wochenplaner-Entwurf.
  **Wichtiger Architektur-Fund:** React-Frontend (Port 8000) und Streamlit (Port 8501) sind
  komplett getrennte Prozesse - `st.session_state` kann nicht zwischen ihnen geteilt werden.
  "Workout anpassen" im Kalender-Widget ist deshalb ein einfacher Link zu
  `http://<host>:8501/Workout_Builder?draft_id=<id>` (volle Browser-Navigation), keine
  API-Vermittlung nötig. Nach Upload über diesen Weg wird der Entwurf als hochgeladen markiert,
  damit das Kalender-Widget den Status korrekt zeigt.
- **"Hochladen" plant auch gleich in den Garmin-Kalender ein:** `POST /api/workout-draft/
  {id}/upload` ruft `upload_workout(workout, client, schedule_date=<Entwurfsdatum>)` auf (vorher
  ohne `schedule_date` - nur Upload ohne Termin). Reine Logik-Änderung, der Button heißt weiterhin
  "Hochladen".
- **`backend/routers/weekly_plan.py`**: `GET /api/weekly-plan/{date}` (Cache-dann-Lazy-Generieren,
  gleiches Muster wie `GET /api/daily-recommendation/{date}` - bedient jetzt alle drei konkreten
  Wochen-Ebenen: Diese/Nächste/Übernächste Woche, inkl. `week_id`/KW und per `get_week_phase()`
  berechneter `training_phase`), `GET /api/workout-draft/{date}`, `POST /api/workout-draft/
  {draft_id}/upload`, `GET /api/far-weeks-outlook/{date}` (ab Woche 4, siehe
  `get_far_weeks_outlook()` unten). Die früheren Endpoints `GET /api/week-outlook/{date}` und `GET
  /api/training-outlook` wurden entfernt (siehe "Nächste Woche zeigt wieder..." oben) - "nächster
  Wettkampf" bleibt weiterhin bewusst einfach das nächste Rennen aus `garmin_scheduled_events`,
  Garmin liefert keine A/B/C-Priorität, siehe dortiger Schema-Check.
- **`get_far_weeks_outlook(reference_date)`** (neu in `weekly_planner.py`): iteriert wochenweise
  von Woche 4 (3 Wochen nach der Woche von `reference_date`) bis zur Woche des nächsten Rennens ab
  diesem Punkt (`garmin_scheduled_events.event_date >= week4_start`, `ORDER BY event_date ASC LIMIT
  1`) - gibt `[]` zurück, falls kein solches Rennen existiert (dann endet die Anzeige nach
  "Übernächste Woche", wie vom Nutzer vorgegeben). **Trainingsphase pro Woche ist bewusst nur
  teilweise berechnet:** Taper (`days_until_race <= TAPER_DAYS_THRESHOLD`) und Peak (`<=
  PEAK_DAYS_THRESHOLD`) sind in `weekly_summary.py::_training_phase` reine Datums-Schwellenwerte
  und daher sicher auf beliebige zukünftige Wochen projizierbar (Konstanten von dort importiert,
  nicht dupliziert); Build/Base hängen dagegen von echtem synchronisiertem Trainingsvolumen der
  jeweiligen Woche ab, das für die Zukunft nicht existiert - für Wochen jenseits des
  Peak-Schwellenwerts bleibt `training_phase` deshalb bewusst `None` (Frontend zeigt "–") statt
  eine Phase zu erfinden. Die letzte Woche (die des Rennens selbst) bekommt zusätzlich
  `race_title`/`race_date` gesetzt (sonst `None`) - dort wird der Wettkampf inkl. genauem Datum
  explizit benannt statt nur Trainingsphase/Datumsbereich zu zeigen, wie vom Nutzer gewünscht.
  Live gegen echte Daten verifiziert (Stand 05.08.2026): die Liste reicht bis KW 37
  (07.-13.09.2026), der Woche des SWB Marathon Bremen am 13.09.2026, letzter Balken zeigt
  "swb-Marathon Bremen (13.09.)" statt einer Trainingsphase - exakt wie erwartet.
- **Frontend:** `WeeklyCalendarWidget.tsx` (lebt mittlerweile auf einer eigenen "Woche"-Seite,
  siehe Design-System-Abschnitt oben, nicht mehr auf der Heute-Seite) zeigt die vier oben
  beschriebenen Ebenen, alle auf derselben `fetchWeeklyPlan()`-Datengrundlage. `PlanDay` (volle
  Detailtiefe, "Diese Woche") und `CompactPlanDay` (reduziert, Nächste/Übernächste Woche) sind zwei
  getrennte Komponenten auf demselben `WeeklyPlanDay`-Typ; `shortSessionLabel()` schneidet für die
  kompakte Ansicht die Klammer-Begründung vom `session_type`-Text ab (`"Langer Lauf
  (Marathon-Vorbereitung)"` -> `"Langer Lauf"`), `roundedDurationLabel()` (in `api.ts`) rundet
  `target_duration_minutes` auf eine feste Viertel-/Halbstunden-Leiter (20/30/45min, dann
  30min-Schritte). `daily_recommendation.py::_gather_context` bekommt einen neuen
  `weekly_plan_block`-Baustein (in `context_blocks.py`, geteilt) - prüft zuerst, ob heute ein
  Club-Slot ist (dann kein zusätzlicher Wochenplan-Kontext nötig), sonst der generierte
  Wochenplan-Vorschlag für heute.
- **Manuelles "Woche neu generieren"** (`POST /api/weekly-plan/{date}/regenerate`): eine Woche
  wurde bisher nur **einmalig** generiert und dann dauerhaft gecacht (`get_week_plan()`-Treffer
  verhindert jede weitere Generierung) - nachträglich angelegte Vereins-Trainingstermine flossen
  dadurch nur in noch nie generierte Wochen ein, nicht in bereits bestehende. Der neue Endpoint
  erzwingt eine Neu-Generierung unabhängig vom Cache-Zustand (`generate_weekly_plan()` schreibt
  ohnehin per `upsert_daily_metric()` über `date` als PK, kein vorheriges Löschen von `weekly_plan`
  nötig). Zählt vorher, wie viele `weekly_plan_workout_draft`-Zeilen der Woche bereits
  `uploaded_at IS NOT NULL` haben, und gibt das als `already_uploaded_count` zurück - das Frontend
  (Refresh-Icon-Button neben jeder der drei Wochen-Ebenen) warnt dann sichtbar, dass zwar der
  lokale Entwurf ersetzt wurde, der bereits bestehende Garmin-Termin selbst aber unangetastet
  bleibt (kein automatisches Zurückziehen alter Uploads).

## Leistung-Seite (`backend/routers/performance.py`, `PerformanceView.tsx`)

Vierte Sidebar-Seite ("Leistung") - Trainingsdiagnostik-KPIs, wöchentliche Belastungssteuerung und
Leistungsziele an einem Ort. Zentrale Backend-Datei `backend/routers/performance.py` (drei Blöcke:
tägliche Bereitschaft, Wochen-Steuerung/Belastung, Leistungsdiagnostik & Schwellenwerte inkl. Ziele)
- alle Endpoints unter `/api/performance/*`, lesend, kein eigener Sync-Trigger. Karten sind zwei
  Breitenklassen (`performance-card-narrow`/`-wide`), von HrvCard/ReadinessGauge auf der Heute-Seite
  mitverwendet (siehe dortiger Abschnitt).

- **Trainingszustand (CTL/ATL/TSB, TrainingPeaks-PMC-Stil):** ersetzt Garmins eigene Trainingszustand-
  Klassifizierung vollständig. **Ground-Truth-Fund:** `garmin_training_status` (Garmins
  `get_training_status()`-Endpoint) erwies sich als grundsätzlich unzuverlässig für dieses Konto -
  zwei unabhängige Syncs desselben Kontos am selben Tag lieferten einmal `"NO_STATUS_1"`, einmal
  komplett `null` (`mostRecentVO2Max`/`mostRecentTrainingLoadBalance`/`mostRecentTrainingStatus`
  allesamt leer). Ursache vermutlich: das Konto hat **zwei** als `primaryTrainingCapable` markierte
  Geräte (Forerunner 970 Uhr + Edge 850 Radcomputer), was Garmins Backend bei der Zuordnung
  offenbar verwirrt. Statt auf dieses eine wacklige Feld zu bauen, berechnet `_classify_training_state
  (tsb)` die Einordnung selbst aus `daily_summary.ctl`/`atl`/`tsb` (bereits unconditional für jeden
  synchronisierten Tag berechnet, siehe Schicht-1-Abschnitt) über eine fünfstufige `TSB_BANDS`-
  Tabelle (Hohes Ermüdungsrisiko/Produktiv/Erhaltend/Frisch/Formverlust-Risiko) - dieselbe fachliche
  Grundlage wie Garmins eigene Klassifizierung, nur ohne die Abhängigkeit vom einzelnen Endpoint.
  `TrainingStateRow` (`PerformanceView.tsx`, Strava-Stil) zeigt CTL/ATL/TSB je mit farbigem Punkt +
  Label nebeneinander; `CtlTrendChart` (Chart.js Line, `GET /api/performance/ctl-trend`, 180 Tage)
  zeigt den Verlauf - CTL sichtbar, ATL/TSB per `hidden: true` erstmal ausgeblendet, über die
  Chart.js-Legende manuell zuschaltbar.
- **Belastungsfokus-Verteilung (Niedrig-/Hoch-Aerob/Anaerob):** gleicher Grund wie oben -
  **Ground-Truth-Fund:** Garmins `metricsTrainingLoadBalanceDTOMap` war für dieses Konto in **jedem**
  bisher synchronisierten Tag `null`. `_compute_load_focus()` berechnet die Verteilung stattdessen
  selbst aus `garmin_activities.hr_zone_1..5` über ein rollierendes 28-Tage-Fenster
  (`LOAD_FOCUS_WINDOW_DAYS`, gleiche Fensterlänge wie `daily_summary.training_load_28d`) - Z1+Z2 =
  Niedrig-Aerob, Z3 = Hoch-Aerob, Z4+Z5 = Anaerob (dieselbe 3-Zonen-Polarisierungslogik wie
  `weekly_summary.py`). Bleibt nur dann `None`, wenn im Fenster wirklich keine Aktivität mit
  HF-Zonen-Daten vorliegt. `LoadFocusBars` stellt die drei Werte als farbige Balken dar (Grün/Orange/
  Rot, dieselbe Ampel wie überall sonst, siehe Design-System-Abschnitt) mit einer Zielmarkierung bei
  `POLARIZATION_MIN_Z1_Z2_PCT`.
- **Pro-Sportart-Karten** (`RunPerformanceCard`/`BikePerformanceCard`/`SwimPerformanceCard`), jede in
  drei per `border-top`-Linie getrennte Unterabschnitte (`Subsection`, siehe Design-System-Abschnitt):
  - **Diagnostik:** aktuelle Schwellenwerte aus `GET /api/performance/thresholds` (kontostandsweite
    "aktuellste Zeile", kein bestimmtes Datum - Lauf-Schwellenpace/-HF aus `garmin_lactate_threshold`
    (Pace aus der bereits ×10-korrigierten `speed`-Spalte, siehe Bugfix unten), Rad-Schwellen-HF aus
    derselben Tabelle, FTP + W/kg aus `garmin_cycling_ftp`, VO2max Laufen/Rad **bewusst aus
    `garmin_max_metrics`, nicht `garmin_training_status.most_recent_vo2max*`** - Ground-Truth-Fund:
    Letzteres blieb in der Garmin-Antwort oft tagelang eingefroren auf einen Wert, inkl. eines
    verdächtig identischen Lauf-/Rad-Werts, während `garmin_max_metrics` deutlich aktueller ist.
    Schwimmen bekommt eine eigene `GET /api/performance/swim-diagnostics` (SWOLF + Pace/100m der
    letzten `lap_swimming`-Aktivität) - SWOLF hat keine eigene Spalte, wird per `json_extract(raw_json,
    '$.averageSwolf')` gelesen statt einer neuen Sync-Spalte+Backfill.
  - **Ziel-Tracking & Fortschritt:** siehe Leistungsziele-Formular unten, gefiltert auf zur Sportart
    passende `key`s.
  - **Wettkampf-Prognose**, bewusst zwei unterschiedliche Ansätze je nach Datenlage:
    - **Laufen:** echter Garmin-Race-Predictor, `GET /api/performance/race-predictions` liest die
      neueste `garmin_race_predictions`-Zeile (5k/10k/Halbmarathon/Marathon-Zeiten) unverändert durch
      - keine eigene Modellierung nötig, Garmin liefert das bereits.
    - **Rad:** **kein Garmin-Pendant** zum Lauf-Race-Predictor. `GET /api/performance/cycling-
      prediction` schätzt stattdessen datengetrieben statt physikalisch: ein persönlicher
      Wirkungsgrad (km/h pro Watt), gemittelt über die eigenen Rad-Aktivitäten mit Leistungs- UND
      Geschwindigkeitsdaten, gefiltert auf **flaches Profil** (`CYCLING_FLAT_ELEVATION_GAIN_PER_KM =
      10.0` m Höhenmeter/km - ground-truth an den eigenen 8 Aktivitäten geprüft: 6 klar darunter
      (1-4 m/km), 2 klar darüber (12-13 m/km), keine Grenzfälle) - hügelige Fahrten würden den
      Wirkungsgrad sonst verzerren, da gleiche Watt bergauf weniger km/h ergeben. Angewendet auf zwei
      feste Szenarien (`CYCLING_PREDICTION_SCENARIOS`: Sprint 20km@95%FTP, Olympisch 40km@88%FTP).
      `sample_size` wird transparent mit ausgegeben, damit sichtbar bleibt, dass die Schätzung mit
      mehr Fahrten belastbarer wird - bewusst kein Wind-/Aerodynamik-Modell, das bleibt eine grobe
      Tendenz.
    - **Schwimmen:** keine Wettkampf-Prognose - es gibt keine vergleichbare Datenquelle (weder
      CSS-Pace noch eine kritische Schwimm-Herzfrequenz werden synchronisiert), bewusst nicht
      erfunden statt geraten (siehe Anti-Fabrikations-Prinzip, offene Baustelle unten).
- **Leistungsziele-Formular** (`performance_goals.py`, Repo-Root, kein `streamlit`-Import; CRUD-
  Endpoints in `backend/routers/performance.py`, UI in `PerformanceGoalsSettings.tsx` auf der
  Einstellungen-Seite): `performance_goals` hat einen natürlichen TEXT-`key` (z.B.
  `marathon_pace`) statt einer AUTOINCREMENT-`id` - Zeilen bleiben jederzeit manuell editierbar. Der
  Key wird im Formular bewusst als **feste Dropdown-Liste** (`KNOWN_GOAL_KEYS`) statt Freitext
  angeboten - ein Tippfehler im Key machte das Ziel vorher unbemerkt wirkungslos, da er der
  Join-Schlüssel zu `GOAL_METRIC_SOURCES` ist. Eingabeformate sind pro Einheit unterschiedlich und
  weichen bewusst vom internen Speicherformat ab: Pace-Ziele (`sec/km`/`sec/100m`) werden als
  `mm:ss` eingegeben/angezeigt (`parsePaceToSeconds`/`formatSecondsToPace`), `W/kg` mit deutschem
  Komma (`parseGermanDecimal`/`formatGermanDecimal`) - beide Helfer + `isPaceUnit`/`unitDisplayLabel`/
  `formatGoalValue` liegen zentral in `api.ts`, geteilt zwischen Formular und Anzeige.
  `GOAL_METRIC_SOURCES` (Dict in `backend/routers/performance.py`) mappt vier der fünf Key-Presets
  auf eine echte, laufend synchronisierte Garmin-Quelle (`run_threshold_pace`→
  `garmin_lactate_threshold.speed`, `ftp_w_per_kg`→`garmin_cycling_ftp.power_to_weight`,
  `marathon_pace`/`halbmarathon_pace`→`garmin_race_predictions`-Zeiten/Distanz) - `swim_pace_100m`
  ist bewusst **nicht** darin (andere Tabellenform, kein `date`-PK, mehrere/keine Aktivitäten pro
  Tag), bekommt eine eigene `_swim_pace_value()`-Funktion mit identischer Fallback-Logik.
  **Impliziter Start-Fortschritt:** `_enrich_goal()` ruft `_metric_value(conn, key, before_date=
  goal.get("start_date") or "0001-01-01")` - das Sentinel-Datum löst den bestehenden "vor der
  ersten Messung → nimm die allererste" Fallback aus, sodass ein Ziel **auch ohne explizit gesetztes
  Startdatum** eine Fortschrittsanzeige bekommt (früheste verfügbare Messung als impliziter Start).
  Bewusst als separates `start_value_date`-Response-Feld gehalten statt `start_date` selbst zu
  überschreiben - ein impliziter Fallback soll beim nächsten Speichern nicht versehentlich als
  "manuell gesetztes Startdatum" persistiert werden. `GoalProgressBar` (`PerformanceView.tsx`) zeigt
  "(früheste verfügbare Messung)" als Hinweis, wenn `start_date !== start_value_date`.

**Zwei Backend-Bugfixes im Rahmen dieser Seite gefunden:**
- **`dashboard-v2` rief `init_db()` nie auf:** auf einem frischen Mac-mini-Deploy (kein Streamlit-
  Seitenaufruf vorher) fehlten sämtliche Tabellen ("no such table: weekly_plan") - `dashboard-v2`
  verließ sich implizit auf Streamlits seitenaufruf-zeitpunktbedingte Schema-Erstellung über dasselbe
  `./data`-Volume. Fix: `init_db()` wird jetzt zusätzlich in FastAPIs `lifespan`-Handler
  (`backend/main.py`) aufgerufen, bevor der Auto-Sync-Task startet.
- **Selbstheilende Migration für historisch falsche Lactate-Threshold-`speed`-Werte:** Garmins
  Rohwert war für `garmin_lactate_threshold.speed` intermittierend um Faktor 10 zu klein (bekannter,
  in `garmin_service.py` bereits für künftige Syncs korrigierter Bug - historische Zeilen blieben
  aber unkorrigiert). `db.py::init_db()` bekam einen einmaligen, bei jedem Container-Start
  ausgeführten Migrations-Block: `UPDATE garmin_lactate_threshold SET speed = speed * 10 WHERE speed
  IS NOT NULL AND speed < 1.0` (1.0 m/s ≈ 16:40 min/km, plausibel unterhalb jeder realen Lauf-
  Schwellenpace) - korrigiert unkorrigierte Altzeilen automatisch, ohne manuellen SQL-Eingriff.
  Verifiziert mit einer synthetisch eingefügten Testzeile (`0.369` → nach `init_db()` `3.69`).

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
| `workout_builder.py` | Erstellt/lädt strukturierte Garmin-Workouts (Pace-/Zonen-Ziele, Intervall + durchgehend) |
| `weekly_planner.py` | Rolling-Horizon-Wochenplaner: Signal-Sammlung, Gemini-Wochenplan, Workout-Entwürfe |
| `chat_engine.py` | Schicht 4: `ChatEngine` mit Function-Calling (Query-Tool, Workout-Vorschlag/-Upload) |
| `auto_sync.py` | Automatischer Sync-Trigger: leichtgewichtiger Schlafdaten-Checker + Tages-Loop, löst `fetch_and_store_garmin_data()` und `generate_daily_recommendation()` aus |
| `context_blocks.py` | Wiederverwendbare Gemini-Kontext-Bausteine (u.a. `strip_markdown_fences`), geteilt von chat_engine.py/daily_recommendation.py/weekly_planner.py |
| `daily_recommendation.py` | Heute-Ansicht: Gemini-generierte Tagesempfehlung inkl. Override-Regenerierung |
| `training_slots.py` | CRUD für wiederkehrende Vereins-Trainingstermine (club_training_slots) |
| `performance_goals.py` | CRUD für Leistungsziele (performance_goals, TEXT-Key statt id) |
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
| `backend/routers/today.py` | Heute-Ansicht: daily-recommendation/daily-override/week-strip (readiness/trends entfernt, siehe performance.py) |
| `backend/routers/club_slots.py` | CRUD auf /api/club-slots (siehe training_slots.py) |
| `backend/routers/weekly_plan.py` | Wochenplaner-Endpoints: weekly-plan (Diese/Nächste/Übernächste Woche)/workout-draft/far-weeks-outlook/regenerate (siehe weekly_planner.py) |
| `backend/routers/performance.py` | Leistung-Seite: readiness-overview/load-status/ctl-trend/thresholds/race-predictions/cycling-prediction/swim-diagnostics/goals (siehe eigener Abschnitt oben) |
| `frontend/src/App.tsx` | Vier-Seiten-Umschalter (Heute/Woche/Leistung/Einstellungen) über Sidebar+useState, kein Routing |
| `frontend/src/Sidebar.tsx` | Einklappbare Seitenleiste, Material-Symbols-Navigation (siehe Design-System-Abschnitt) |
| `frontend/src/TopBar.tsx` | Seitentitel/-untertitel je View, Uhrzeit, Sync-Pille (manueller Trigger), Theme-Toggle |
| `frontend/src/theme.ts` | `useTheme()`-Hook, Hell/Dunkel/System, localStorage-persistiert |
| `frontend/src/sidebarCollapsed.ts` | `useSidebarCollapsed()`-Hook, gleiches Persistenz-Muster wie theme.ts |
| `frontend/src/useCssVar.ts` | Liest eine CSS-Custom-Property als aufgelösten Wert aus (Canvas/Chart.js kann var() nicht selbst auflösen) |
| `frontend/src/Icon.tsx` | Material-Symbols-Ligature-Icon-Wrapper, ersetzt app-weit Emoji |
| `frontend/src/TodayView.tsx` | Heute-Ansicht: Trainingsbereitschaft-Karte (ReadinessGauge + Empfehlung inkl. Override-Buttons) + HRV & Ruhepuls-Karte |
| `frontend/src/ReadinessGauge.tsx` | Chart.js-Doughnut-Gauge für den Readiness-Score (ersetzt frühere Hand-SVG) |
| `frontend/src/HrvCard.tsx` | "HRV & Ruhepuls"-Karte: Wochenschnitt-Werte + Statuspillen + HrvTrendPanel |
| `frontend/src/HrvTrendPanel.tsx` | 28-Tage-Bilanz: drei gestapelte Chart.js-Small-Multiples (HRV+Baseline, RHR-Abweichung, Trainings-Load) |
| `frontend/src/WeekView.tsx` | Eigene "Woche"-Seite, rendert WeeklyCalendarWidget |
| `frontend/src/WeeklyCalendarWidget.tsx` | Rolling-Horizon-Kalender: Diese Woche/Nächste Woche/Wochen 3-4, inkl. "Woche neu generieren" |
| `frontend/src/PerformanceView.tsx` | Leistung-Seite: Trainingszustand/Belastungsfokus/CTL-Trend + drei Sportart-Karten (Diagnostik/Ziele/Wettkampf-Prognose) |
| `frontend/src/ClubSlotsSettings.tsx` | Liste + Formular für Vereins-Trainingstermine (Einstellungen-Seite) |
| `frontend/src/PerformanceGoalsSettings.tsx` | Liste + Formular für Leistungsziele (Einstellungen-Seite, siehe Leistung-Seiten-Abschnitt oben) |
| `frontend/src/api.ts` | Typisierte fetch()-Wrapper + geteilte Formatier-Helfer (Pace/Dezimal/Zieldatum) für alle Backend-Endpoints |

## Datenbank (Auszug nach Kategorie, `db.py`)

- **Tages-Tabellen** (PK `date`, Upsert): `garmin_daily`, `garmin_training_readiness`,
  `garmin_max_metrics`, `garmin_sleep_phases`, `garmin_cycling_ftp`, `garmin_lactate_threshold`,
  `daily_summary` u.v.m. — rund 20 weitere Tier-1/2-Metrik-Tabellen (SpO2, Atmung, Hydration,
  Blutdruck, Endurance-/Hill-Score, Fitness-Alter, `garmin_race_predictions` (5k/10k/Halbmarathon/
  Marathon-Finishzeiten, siehe Leistung-Seiten-Abschnitt oben), `garmin_training_status` (weiterhin
  synchronisiert, aber auf der Leistung-Seite bewusst NICHT mehr gelesen - siehe Ground-Truth-Fund
  im Leistung-Seiten-Abschnitt oben), ...)
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
  (PK `id` AUTOINCREMENT, mit optionaler `typical_character`-Spalte, siehe "Heute-Ansicht"- bzw.
  "Rolling-Horizon-Wochenplaner"-Abschnitt oben)
- **Wochenplaner:** `weekly_plan` (PK `date`, eine Zeile pro Tag statt pro Woche - siehe
  Begründung im "Rolling-Horizon-Wochenplaner"-Abschnitt oben; `is_key_session INTEGER` als
  nachträglich ergänzte Spalte, `NULL` = Wettkampftag/nicht bewertbar), `weekly_plan_workout_draft`
  (PK `id` AUTOINCREMENT, speichert Builder-Name+Parameter statt eines Workout-Objekts)
- **Leistungsziele:** `performance_goals` (PK `key` TEXT, siehe Leistung-Seiten-Abschnitt oben -
  `derived_from_race_goal_id` verweist optional auf `race_goals`, ist aber reine Herkunfts-Info,
  keine Sperre), `race_goals` (renn-spezifische Zielzeiten - Schreibzugriff bewusst nicht Teil der
  `performance_goals`-CRUD-API, gehört zu einem separaten, noch offenen Auftrag/KI-Zielgespräch)

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
- Kein Browser-Automatisierungswerkzeug in dieser Session verfügbar - Frontend-Änderungen
  (Heute-, Woche- und Leistung-Ansicht, inkl. Kalender-Widget, Chart.js-Panels, Sportart-Karten)
  wurden durchgängig nur indirekt verifiziert: API-Response-Form vs. TypeScript-Interfaces,
  erfolgreicher Docker-Frontend-Build (`tsc -b && vite build`) und erfolgreicher Asset-Abruf. Ein
  manueller Blick ins echte Frontend unter localhost:8000 steht weiterhin aus.
- **Schwimmen hat keine Wettkampf-Prognose** (Leistung-Seite) - es gibt keine synchronisierte
  Datenquelle, aus der sich eine belastbare Schätzung ableiten ließe (weder CSS-Pace noch eine
  kritische Schwimm-Herzfrequenz) - bewusst nicht erfunden, siehe Leistung-Seiten-Abschnitt oben.
- **Die Rad-Wettkampf-Schätzung bleibt eine grobe Tendenz**, keine physikalische Modellierung -
  persönlicher Wirkungsgrad aus einer noch einstelligen Anzahl flacher Fahrten gemittelt, ohne
  Wind-/Aerodynamik-Korrektur. `sample_size` macht das transparent, wird mit mehr Fahrten
  automatisch belastbarer (siehe Leistung-Seiten-Abschnitt oben).
- `POST /api/workout-draft/{id}/upload` (lädt hoch UND plant jetzt auch für den Entwurfstag im
  Garmin-Kalender ein) wurde strukturell (404-Fall, Docker-Build) geprüft, aber noch nicht gegen
  einen echten Garmin-Upload getestet - bewusst zurückgehalten (429-Vorsicht), steht mit dem
  Nutzer zusammen noch aus.
- Die Intervall-Workout-Entwürfe des Wochenplaners nutzen eine feste Default-Struktur (5x1000m,
  10min Warmup/Cooldown Zone 1, 2min Erholung) statt einer vom Modell vorgeschlagenen
  Feinstruktur (`weekly_plan` speichert nur ein Gesamt-Zielvolumen, keine Intervall-Details) -
  der Entwurf ist als Ausgangspunkt für "Workout anpassen" gedacht, keine Endfassung.
