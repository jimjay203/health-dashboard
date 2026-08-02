# 🏃‍♂️ Health & Performance Dashboard

Ein persönliches Trainings-Dashboard für Ausdauersportler (Läufer/Triathleten), das Garmin-Connect-Daten automatisch synchronisiert, in SQLite speichert und über einen KI-Coach (Google Gemini) täglich auswertet — inklusive Renn-Kalender, Trainingsbereitschafts-Einordnung und Leistungs-Trends.

Gebaut als Streamlit-Multi-Page-App, per Docker Compose deploybar.

## ✨ Features

- **Automatischer Garmin-Sync**: Tages-Sync und mehrtägiger Backfill über die UI, mit Token-Caching (kein wiederholter Passwort-Login) und Rate-Limit-Schutz (bricht bei 429 sofort ab, statt weiterzuhämmern)
- **36 Datentabellen** rund um Schlaf, HRV, Stress, Body Battery, SpO2, Atmung, Trainingsbereitschaft, Endurance-/Hill-Score, Cycling FTP, Gewichtsverlauf, Personal Records, geplante Workouts & Rennen (Kalender) u.v.m. — nur Rohmesswerte und von Garmin selbst berechnete Scores, keine redundanten Aggregate
- **🏠 Tagesübersicht**: subjektives Tagesjournal (RPE, Muskelkater, Energie), Garmins eigener Trainingsbereitschafts-Score mit verständlicher Einordnung ("Hauptgrund: Erholungszeit ist aktuell Schlecht"), KI-Coach mit direkt sichtbaren Handlungsempfehlungen statt Fließtext
- **📊 Health Trends**: fortlaufender Renn-/Workout-Kalender mit sportspezifischen Icons, Endurance-Score-Einordnung anhand von Garmins eigenen Klassifizierungs-Schwellenwerten, HRV/Ruhepuls-, Schlaf-, Gewichts- und Readiness-Trends
- **⚙️ Settings**: Einzel-Sync, Zeitraum-Backfill, sowie eine API-Explorationsfunktion, die alle relevanten Garmin-Endpunkte einmal testweise abruft und die rohen JSON-Antworten anzeigt/speichert
- **KI-Coach** (Gemini): analysiert physiologische Kern- und erweiterte Metriken plus subjektives Befinden, liefert einen eigenen Readiness-Score, einen kurzen Trainingsfokus und 2-4 konkrete Stichpunkt-Empfehlungen (strukturiertes JSON-Schema statt Fließtext-Parsing)

## 🧱 Tech Stack

- [Streamlit](https://streamlit.io/) (Multi-Page App)
- SQLite (über `sqlite3`, kein ORM)
- [garminconnect](https://github.com/cyberjunky/python-garminconnect) für den Garmin-API-Zugriff
- [google-genai](https://github.com/googleapis/python-genai) (Gemini) für den KI-Coach
- Plotly für Charts
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

### Deployment aktualisieren

```bash
./deploy.sh
```

Zieht den neuesten `main`-Branch und baut die Container neu.

## 📂 Projektstruktur

```
app.py                     # Streamlit-Einstiegspunkt / Navigation
pages/
  1_🏠_Home.py              # Tagesübersicht, Journal, KI-Coach
  2_📊_Health_Trends.py     # Kalender & historische Trends
  3_⚙️_Settings.py          # Sync, Backfill, API-Exploration
db.py                      # SQLite-Schema & generische Upsert-Helper
garmin_auth.py             # Login & Token-Caching
garmin_service.py          # Kern-Sync + alle erweiterten Metrik-Gruppen
garmin_backfill.py         # Mehrtägiger Backfill mit 429-Schutz
garmin_explore.py          # Einmaliger Testabruf aller Endpunkte
ai_coach.py                # Gemini-basierte Tagesauswertung
```

## ⚠️ Hinweise

- `data/` (SQLite-Datenbank) und `garmin_api_exploration/` (rohe API-Testdaten mit echten persönlichen Daten wie GPS/Gewicht) sind bewusst in `.gitignore` und werden nicht versioniert.
- Aktivitäten (Läufe, Radfahrten etc.) werden bewusst **nicht** über dieses Dashboard synchronisiert oder importiert — die laufen weiterhin ganz normal über Garmin Connect selbst (inkl. manuellem `.fit`-Upload dort, falls nötig).
- Garmins Rate-Limit (429) ist real und wird ernst genommen: alle Sync-Pfade brechen bei einem 429 sofort ab, statt es erneut zu versuchen.
