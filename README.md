# 🏃‍♂️ Health & Performance Dashboard

Ein persönliches Trainings-Dashboard für Ausdauersportler (Läufer/Triathleten), das Garmin-Connect-Daten automatisch synchronisiert, in SQLite speichert und regelbasiert auswertet — inklusive Renn-Kalender, Trainingsbereitschafts-Einordnung, Leistungs-Trends und einem LLM-gestützten Erkenntnis-Gedächtnis (Google Gemini).

Gebaut als Streamlit-Multi-Page-App, per Docker Compose deploybar.

## ✨ Features

- **Automatischer Garmin-Sync**: Tages-Sync und mehrtägiger Backfill über die UI, mit Token-Caching (kein wiederholter Passwort-Login) und Rate-Limit-Schutz (bricht bei 429 sofort ab, statt weiterzuhämmern)
- **~46 Datentabellen** rund um Schlaf, HRV, Stress, Body Battery, SpO2, Atmung, Trainingsbereitschaft, Endurance-/Hill-Score, Cycling FTP, Gewichtsverlauf, Personal Records, geplante Workouts & Rennen (Kalender) u.v.m. — nur Rohmesswerte und von Garmin selbst berechnete Scores, keine redundanten Aggregate
- **Regelbasierte Auswertungsschichten** (kein LLM): pro Tag (HRV/Schlaf/Ruhepuls vs. Baseline, Trainingslast, Chronic/Acute Training Load nach dem TrainingPeaks-PMC-Modell, Übertrainings-Erkennung), pro Aktivität (Decoupling, HF-Drift, Grade Adjusted Pace, Brick-Erkennung) und pro Woche (Volumen, Trainingszonen-Verteilung, Trainingsphase, Renn-Countdown)
- **🧠 Erkenntnis-Gedächtnis** (Gemini): ein kompaktes, sich selbst verdichtendes Wissens-Gedächtnis für Zusatzinfos, die sich nicht aus den Trainingsdaten ablesen lassen (z.B. feste Wochenroutinen, gesundheitliche Eigenheiten) — gespeist aus manuellen Einträgen und automatisch aus dem Tagesjournal-Freitext
- **🏠 Tagesübersicht**: subjektives Tagesjournal (RPE, Muskelkater, Energie), Garmins eigener Trainingsbereitschafts-Score mit verständlicher Einordnung ("Hauptgrund: Erholungszeit ist aktuell Schlecht"), Trainingslast-/Form-Kennzahlen (ACWR, CTL/ATL/TSB)
- **📊 Health Trends**: fortlaufender Renn-/Workout-Kalender mit sportspezifischen Icons, Endurance-Score-Einordnung anhand von Garmins eigenen Klassifizierungs-Schwellenwerten, HRV/Ruhepuls-, Schlaf-, Gewichts- und Readiness-Trends
- **🏃 Aktivitäten**: manueller Sync von Läufen/Rad/Schwimmen inkl. optionaler Sekunden-Detail-Zeitreihen (GPS/HF/Leistung), Filter, Detailcharts und GPS-Route
- **⚙️ Settings**: Einzel-Sync, Zeitraum-Backfill, Aktivitäten-Sync sowie eine API-Explorationsfunktion, die alle relevanten Garmin-Endpunkte einmal testweise abruft und die rohen JSON-Antworten anzeigt/speichert

## 🧱 Tech Stack

- [Streamlit](https://streamlit.io/) (Multi-Page App)
- SQLite (über `sqlite3`, kein ORM)
- [garminconnect](https://github.com/cyberjunky/python-garminconnect) für den Garmin-API-Zugriff
- [google-genai](https://github.com/googleapis/python-genai) (Gemini) für das Erkenntnis-Gedächtnis
- Plotly/pydeck für Charts & Karten
- Docker Compose für den Betrieb

## 🚀 Setup

### Voraussetzungen

- Docker & Docker Compose
- Ein Garmin-Connect-Konto
- Ein [Google Gemini API Key](https://aistudio.google.com/)

### 1. Repository klonen & konfigurieren

```bash
git clone git@github.com:jimjay203/health-dashboard.git
cd health-dashboard
cp .env.example .env
```

`.env` benötigt:

```dotenv
# Garmin Zugangsdaten
GARMIN_EMAIL=deine@email.de
GARMIN_PASSWORD=dein-passwort

# Google Gemini API Key (aus Google AI Studio)
GEMINI_API_KEY=dein-api-key
```

> Die Garmin-Zugangsdaten werden nur für den *ersten* Login benötigt — danach übernimmt `garmin_auth.py` das Token-Caching unter `~/.garminconnect`, sodass kein wiederholter Passwort-Login (und damit kein unnötiges 429-Rate-Limit-Risiko) entsteht.

### 2. Starten

```bash
docker compose up -d --build
```

Das Dashboard läuft danach unter [http://localhost:8501](http://localhost:8501).

### 3. Erste Daten holen

In der App unter **⚙️ Settings**:
1. Einzel-Sync für heute ausführen (Login + erste Datenbefüllung)
2. Optional: Backfill über einen Zeitraum starten, um Historie nachzuladen
3. Optional: Aktivitäten-Sync starten (Läufe/Rad/Schwimmen, bewusst manuell/getrennt vom Tages-Sync)

### Deployment aktualisieren

```bash
./deploy.sh
```

Zieht den neuesten `main`-Branch und baut die Container neu.

## 📂 Projektstruktur

```
app.py                       # Streamlit-Einstiegspunkt / Navigation
pages/
  1_🏠_Home.py                # Tagesübersicht, Journal
  2_📊_Health_Trends.py       # Kalender & historische Trends
  3_⚙️_Settings.py            # Sync, Backfill, API-Exploration, Aktivitäten-Sync
  4_🏃_Aktivitäten.py         # Aktivitäts-Liste, Filter, Detailcharts, GPS-Route
  5_🧠_Erkenntnisse.py        # UI fürs Erkenntnis-Gedächtnis
db.py                        # SQLite-Schema & generische Upsert-/Zeitreihen-Helper
garmin_auth.py                # Login & Token-Caching
garmin_service.py            # Kern-Sync + alle erweiterten Metrik-Gruppen
garmin_backfill.py           # Mehrtägiger Backfill mit 429-Schutz
garmin_explore.py            # Einmaliger Testabruf aller Endpunkte
garmin_activities.py         # Manueller Aktivitäten-Sync (Liste + Sekunden-Details)
daily_summary.py             # Regelbasierte Tages-Kennzahlen (u.a. CTL/ATL/TSB, Journal-Integration)
activity_analytics.py        # Regelbasierte Pro-Aktivität-Kennzahlen
training_zones.py            # Friel-Trainingszonen aus Schwellenwerten
weekly_summary.py            # Regelbasierte Wochen-Kennzahlen
insight_memory.py            # LLM-gestütztes Erkenntnis-Gedächtnis
gemini_client.py             # Gemeinsame Gemini-Konfiguration
backfill_2026.py             # Stand-alone-CLI-Skript für einmaligen historischen Backfill
```

Ein technischer Gesamtüberblick (Architektur, Konventionen, Datenbank-Kategorien) steht in
[`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md).

## ⚠️ Hinweise

- `data/` (SQLite-Datenbank) und `garmin_api_exploration/` (rohe API-Testdaten mit echten persönlichen Daten wie GPS/Gewicht) sind bewusst in `.gitignore` und werden nicht versioniert.
- Aktivitäten-Sync ist bewusst **manuell** und komplett getrennt vom automatischen Tages-/Backfill-Sync — eine volle Historie kann mehrere hundert Aktivitäten mit je mehreren hundert Detail-Zeilen umfassen.
- Garmins Rate-Limit (429) ist real und wird ernst genommen: alle Sync-Pfade brechen bei einem 429 sofort ab, statt es erneut zu versuchen.
