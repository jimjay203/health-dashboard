import sqlite3
import os
from datetime import date

DB_PATH = os.getenv("DB_PATH", "data/dashboard.db")

def get_connection():
    # Stellt sicher, dass das Datenverzeichnis existiert
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialisiert das SQLite Datenbankschema."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Garmin Daily Health Data Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS garmin_daily (
        date TEXT PRIMARY KEY,
        resting_hr INTEGER,
        avg_hrv REAL,
        sleep_score INTEGER,
        sleep_hours REAL,
        body_battery_max INTEGER,
        body_battery_min INTEGER,
        stress_avg INTEGER,
        steps INTEGER,
        raw_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. Daily Journal & Subjektive Notizen Formular
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_journal (
        date TEXT PRIMARY KEY,
        rpe_score INTEGER,         -- Rate of Perceived Exertion (1-10)
        muscle_soreness INTEGER,   -- Muskelkater/Gefühl (1-5)
        energy_level INTEGER,      -- Energielevel subjektiv (1-5)
        notes TEXT,                -- Freitext Notizen/Tagesjournal
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 3. AI Coach Cache Table (Speichert generierte Empfehlungen)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_coach_insights (
        date TEXT PRIMARY KEY,
        readiness_score INTEGER,   -- KI-berechneter Score (0-100)
        status_summary TEXT,       -- Kurzer Status
        coaching_advice TEXT,      -- Ausführliche KI-Empfehlung
        model_used TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

def save_garmin_data(data_dict):
    """Speichert oder aktualisiert Garmin Tageswerte in SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO garmin_daily (
        date, resting_hr, avg_hrv, sleep_score, sleep_hours, 
        body_battery_max, body_battery_min, stress_avg, steps, raw_json
    ) VALUES (:date, :resting_hr, :avg_hrv, :sleep_score, :sleep_hours, 
              :body_battery_max, :body_battery_min, :stress_avg, :steps, :raw_json)
    ON CONFLICT(date) DO UPDATE SET
        resting_hr=excluded.resting_hr,
        avg_hrv=excluded.avg_hrv,
        sleep_score=excluded.sleep_score,
        sleep_hours=excluded.sleep_hours,
        body_battery_max=excluded.body_battery_max,
        body_battery_min=excluded.body_battery_min,
        stress_avg=excluded.stress_avg,
        steps=excluded.steps,
        raw_json=excluded.raw_json;
    """, data_dict)
    conn.commit()
    conn.close()

def save_journal_entry(date_str, rpe, soreness, energy, notes):
    """Speichert manuelle Formulareingaben ab."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO daily_journal (date, rpe_score, muscle_soreness, energy_level, notes)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(date) DO UPDATE SET
        rpe_score=excluded.rpe_score,
        muscle_soreness=excluded.muscle_soreness,
        energy_level=excluded.energy_level,
        notes=excluded.notes;
    """, (date_str, rpe, soreness, energy, notes))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("SQLite Datenbank erfolgreich initialisiert!")