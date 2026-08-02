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
        training_focus TEXT,       -- Kurzer Trainingsfokus (z.B. "Aktive Erholung"), auf einen Blick lesbar
        key_recommendations TEXT,  -- JSON-Liste kurzer, konkreter Handlungsempfehlungen
        coaching_advice TEXT,      -- Ausführliche Begründung/Empfehlung (Details, nicht auf den ersten Blick)
        model_used TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(ai_coach_insights)")}
    for column, coltype in {"training_focus": "TEXT", "key_recommendations": "TEXT"}.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE ai_coach_insights ADD COLUMN {column} {coltype}")

    # --- Erweiterte Metrik-Tabellen (Advanced Health, Trends, Körperkomposition, Hydration) ---
    # Tages-Tabellen: eine Zeile pro Datum, upsert über upsert_daily_metric()
    daily_tables = {
        "garmin_race_predictions": """
            date TEXT PRIMARY KEY,
            time_5k INTEGER,
            time_10k INTEGER,
            time_half_marathon INTEGER,
            time_marathon INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_fitness_age": """
            date TEXT PRIMARY KEY,
            chronological_age INTEGER,
            fitness_age REAL,
            achievable_fitness_age REAL,
            previous_fitness_age REAL,
            rhr_value INTEGER,
            bmi_value REAL,
            vigorous_days_avg REAL,
            vigorous_minutes_avg REAL,
            last_updated TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_max_metrics": """
            date TEXT PRIMARY KEY,
            vo2max_running REAL,
            vo2max_cycling REAL,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_training_readiness": """
            date TEXT PRIMARY KEY,
            score INTEGER,
            level TEXT,
            feedback_long TEXT,
            feedback_short TEXT,
            sleep_score INTEGER,
            sleep_score_factor_percent INTEGER,
            sleep_score_factor_feedback TEXT,
            recovery_time INTEGER,
            recovery_time_factor_percent INTEGER,
            recovery_time_factor_feedback TEXT,
            acwr_factor_percent INTEGER,
            acwr_factor_feedback TEXT,
            hrv_factor_percent INTEGER,
            hrv_factor_feedback TEXT,
            hrv_weekly_average INTEGER,
            sleep_history_factor_percent INTEGER,
            sleep_history_factor_feedback TEXT,
            stress_history_factor_percent INTEGER,
            stress_history_factor_feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_hydration": """
            date TEXT PRIMARY KEY,
            value_ml REAL,
            goal_ml REAL,
            daily_average_ml REAL,
            sweat_loss_ml REAL,
            activity_intake_ml REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_intensity_minutes": """
            date TEXT PRIMARY KEY,
            weekly_moderate INTEGER,
            weekly_vigorous INTEGER,
            weekly_total INTEGER,
            week_goal INTEGER,
            moderate_minutes INTEGER,
            vigorous_minutes INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_lactate_threshold": """
            date TEXT PRIMARY KEY,
            speed REAL,
            heart_rate INTEGER,
            heart_rate_cycling INTEGER,
            functional_threshold_power INTEGER,
            power_to_weight REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_running_tolerance": """
            date TEXT PRIMARY KEY,
            total_impact_load INTEGER,
            total_distance REAL,
            tolerance INTEGER,
            week_index INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_spo2": """
            date TEXT PRIMARY KEY,
            average_spo2 REAL,
            lowest_spo2 INTEGER,
            last_7d_avg_spo2 REAL,
            latest_spo2 INTEGER,
            avg_sleep_spo2 REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_blood_pressure": """
            date TEXT PRIMARY KEY,
            systolic INTEGER,
            diastolic INTEGER,
            pulse INTEGER,
            category TEXT,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_training_status": """
            date TEXT PRIMARY KEY,
            most_recent_vo2max REAL,
            training_load_balance TEXT,
            training_status TEXT,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_nutrition_daily": """
            date TEXT PRIMARY KEY,
            calories_goal INTEGER,
            calories_adjusted INTEGER,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_lifestyle_logging": """
            date TEXT PRIMARY KEY,
            total_tracking INTEGER,
            completed_tracking INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_pregnancy_summary": """
            date TEXT PRIMARY KEY,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_heart_rate_summary": """
            date TEXT PRIMARY KEY,
            max_hr INTEGER,
            min_hr INTEGER,
            resting_hr INTEGER,
            last_7d_avg_resting_hr INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_respiration_summary": """
            date TEXT PRIMARY KEY,
            lowest REAL,
            highest REAL,
            avg_waking REAL,
            avg_sleep REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_endurance_score": """
            date TEXT PRIMARY KEY,
            overall_score INTEGER,
            classification INTEGER,
            feedback_phrase INTEGER,
            gauge_lower_limit INTEGER,
            gauge_upper_limit INTEGER,
            classification_intermediate INTEGER,
            classification_trained INTEGER,
            classification_well_trained INTEGER,
            classification_expert INTEGER,
            classification_superior INTEGER,
            classification_elite INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_hill_score": """
            date TEXT PRIMARY KEY,
            strength_score INTEGER,
            endurance_score INTEGER,
            overall_score INTEGER,
            classification_id INTEGER,
            feedback_phrase_id INTEGER,
            vo2_max REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        "garmin_cycling_ftp": """
            date TEXT PRIMARY KEY,
            functional_threshold_power INTEGER,
            measured_date TEXT,
            is_stale INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
    }
    for table_name, columns_sql in daily_tables.items():
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_sql})")

    # Nachträgliche Spalten für bereits bestehende Installationen (CREATE TABLE IF NOT EXISTS
    # legt bei existierenden Tabellen keine neuen Spalten an).
    training_readiness_columns = {
        "sleep_score_factor_percent": "INTEGER",
        "sleep_score_factor_feedback": "TEXT",
        "recovery_time_factor_percent": "INTEGER",
        "recovery_time_factor_feedback": "TEXT",
        "acwr_factor_feedback": "TEXT",
        "hrv_factor_feedback": "TEXT",
        "sleep_history_factor_feedback": "TEXT",
        "stress_history_factor_feedback": "TEXT",
    }
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(garmin_training_readiness)")}
    for column, coltype in training_readiness_columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE garmin_training_readiness ADD COLUMN {column} {coltype}")

    endurance_score_columns = {
        "classification_intermediate": "INTEGER",
        "classification_trained": "INTEGER",
        "classification_well_trained": "INTEGER",
        "classification_expert": "INTEGER",
        "classification_superior": "INTEGER",
        "classification_elite": "INTEGER",
    }
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(garmin_endurance_score)")}
    for column, coltype in endurance_score_columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE garmin_endurance_score ADD COLUMN {column} {coltype}")

    # Zeitreihen-Tabellen: mehrere Zeilen pro Datum, komplett ersetzt über replace_timeseries()
    timeseries_tables = {
        "garmin_stress_timeseries": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            timestamp INTEGER,
            stress_level INTEGER
        """,
        "garmin_body_battery_timeseries": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            timestamp INTEGER,
            status TEXT,
            level INTEGER
        """,
        "garmin_body_battery_events": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            event_type TEXT,
            start_time_gmt TEXT,
            duration_ms INTEGER,
            body_battery_impact INTEGER,
            activity_name TEXT,
            activity_type TEXT,
            average_stress REAL
        """,
        "garmin_floors_timeseries": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            start_time_gmt TEXT,
            end_time_gmt TEXT,
            floors_ascended INTEGER,
            floors_descended INTEGER
        """,
        "garmin_heart_rate_timeseries": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            timestamp INTEGER,
            heart_rate INTEGER
        """,
        "garmin_respiration_timeseries": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            timestamp INTEGER,
            respiration_value REAL
        """,
        "garmin_steps_timeseries": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            start_gmt TEXT,
            end_gmt TEXT,
            steps INTEGER,
            pushes INTEGER,
            primary_activity_level TEXT
        """,
        "garmin_all_day_events": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            activity_type TEXT,
            activity_sub_type TEXT,
            start_time_gmt TEXT,
            end_time_gmt TEXT,
            duration INTEGER
        """,
        # Kalender-Events/geplante Workouts (get_scheduled_workouts) - hier zweckentfremdet:
        # 'date' ist hier kein Kalendertag, sondern der Monats-Partitionsschlüssel "YYYY-MM"
        # (ein Monat wird komplett ersetzt), das eigentliche Tagesdatum steht in event_date.
        "garmin_scheduled_events": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            event_date TEXT,
            item_type TEXT,
            activity_type_id INTEGER,
            title TEXT,
            is_race INTEGER,
            distance_meters REAL,
            location TEXT,
            url TEXT,
            shareable_event_uuid TEXT,
            workout_id INTEGER,
            training_plan_id INTEGER
        """,
    }
    for table_name, columns_sql in timeseries_tables.items():
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_sql})")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_date ON {table_name}(date)")

    # Weigh-Ins: eigene Tabelle, Primary Key ist Garmins stabile sample_pk (mehrere Messungen/Tag möglich)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS garmin_weigh_ins (
        sample_pk INTEGER PRIMARY KEY,
        date TEXT NOT NULL,
        weight REAL,
        bmi REAL,
        body_fat REAL,
        body_water REAL,
        bone_mass REAL,
        muscle_mass REAL,
        physique_rating REAL,
        visceral_fat REAL,
        metabolic_age INTEGER,
        source_type TEXT,
        timestamp_gmt INTEGER
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_garmin_weigh_ins_date ON garmin_weigh_ins(date)")

    # Personal Records: Primary Key ist Garmins eigene PR-id (wird bei neuer Bestzeit aktualisiert)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS garmin_personal_records (
        id INTEGER PRIMARY KEY,
        type_id INTEGER,
        activity_id INTEGER,
        activity_name TEXT,
        activity_type TEXT,
        value REAL,
        activity_start_date TEXT,
        pr_date TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Goals: aktuell für diesen Account leer (weder "active" noch "future"), Struktur schon
    # vorbereitet - raw_json, da die reale Feldstruktur erst bei echten Zielen bekannt ist.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS garmin_goals (
        id INTEGER PRIMARY KEY,
        status TEXT,
        raw_json TEXT,
        synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Trainingspläne: aktuell leer (kein strukturierter Garmin-Trainingsplan hinterlegt)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS garmin_training_plans (
        id INTEGER PRIMARY KEY,
        raw_json TEXT,
        synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

def upsert_daily_metric(table, data):
    """Generisches Upsert für Tages-Tabellen mit 'date' als Primary Key."""
    columns = list(data.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c != "date")
    conn = get_connection()
    conn.execute(f"""
        INSERT INTO {table} ({", ".join(columns)}) VALUES ({placeholders})
        ON CONFLICT(date) DO UPDATE SET {updates}
    """, data)
    conn.commit()
    conn.close()

def replace_timeseries(table, date_str, columns, rows):
    """Ersetzt alle Zeilen eines Tages in einer Zeitreihen-Tabelle (Delete+Insert),
    damit ein erneuter Sync desselben Tages keine Duplikate erzeugt."""
    conn = get_connection()
    conn.execute(f"DELETE FROM {table} WHERE date = ?", (date_str,))
    if rows:
        placeholders = ", ".join("?" for _ in columns)
        conn.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            rows
        )
    conn.commit()
    conn.close()

def upsert_weigh_in(data):
    """Upsert für Weigh-Ins über die stabile sample_pk von Garmin."""
    columns = list(data.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c != "sample_pk")
    conn = get_connection()
    conn.execute(f"""
        INSERT INTO garmin_weigh_ins ({", ".join(columns)}) VALUES ({placeholders})
        ON CONFLICT(sample_pk) DO UPDATE SET {updates}
    """, data)
    conn.commit()
    conn.close()

def upsert_by_key(table, key_column, data):
    """Generisches Upsert für Tabellen mit einer beliebigen (nicht 'date'/'sample_pk') Primary Key-Spalte."""
    columns = list(data.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c != key_column)
    conn = get_connection()
    conn.execute(f"""
        INSERT INTO {table} ({", ".join(columns)}) VALUES ({placeholders})
        ON CONFLICT({key_column}) DO UPDATE SET {updates}
    """, data)
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