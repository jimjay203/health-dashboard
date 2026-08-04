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

    # ai_coach_insights (Gemini-Tagesform-Cache) wurde entfernt - Feature komplett gestrichen,
    # DROP für bereits bestehende Installationen (Daten waren nur ein jederzeit neu generierbarer
    # Cache, kein Nutzer-Rohdatenverlust).
    cursor.execute("DROP TABLE IF EXISTS ai_coach_insights")

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
            -- Achtung: functional_threshold_power/power_to_weight sind LAUF-Leistungswerte
            -- (Garmins Rohantwort taggt das power-Objekt mit "sport": "RUNNING"), KEIN Rad-FTP.
            -- Rad-FTP kommt ausschließlich aus garmin_cycling_ftp (siehe training_zones.py).
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
            most_recent_vo2max_cycling REAL,
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
            power_to_weight REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        # Schlafphasen aus dailySleepDTO (bereits Teil der bestehenden get_sleep_data()-Antwort,
        # kein neuer API-Call) - bisher nur ungenutzt im raw_json-Blob von garmin_daily.
        "garmin_sleep_phases": """
            date TEXT PRIMARY KEY,
            deep_sleep_seconds INTEGER,
            light_sleep_seconds INTEGER,
            rem_sleep_seconds INTEGER,
            awake_sleep_seconds INTEGER,
            deep_pct INTEGER,
            light_pct INTEGER,
            rem_pct INTEGER,
            deep_qualifier TEXT,
            light_qualifier TEXT,
            rem_qualifier TEXT,
            awake_count INTEGER,
            avg_sleep_stress REAL,
            avg_sleep_hr REAL,
            sleep_need_seconds INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        # Schicht 1 der KI-Chat-Vorbereitung: regelbasiert vorverdichtete Tageskennzahlen
        # (siehe daily_summary.py), unconditional bei jedem Sync berechnet (auch Backfill-Tage).
        "daily_summary": """
            date TEXT PRIMARY KEY,
            hrv_vs_7d_avg_pct REAL,
            hrv_vs_28d_avg_pct REAL,
            sleep_vs_7d_avg_pct REAL,
            resting_hr_vs_7d_avg_pct REAL,
            training_load_7d REAL,
            training_load_28d REAL,
            acute_chronic_ratio REAL,
            training_monotony REAL,
            training_strain REAL,
            sleep_debt_cumulative REAL,
            overreach_flag INTEGER,
            days_until_next_race INTEGER,
            weight_vs_avg_pct REAL,
            data_quality_flag TEXT,
            notable_events_text TEXT,
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

    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(garmin_training_status)")}
    if "most_recent_vo2max_cycling" not in existing_columns:
        cursor.execute("ALTER TABLE garmin_training_status ADD COLUMN most_recent_vo2max_cycling REAL")

    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(garmin_cycling_ftp)")}
    if "power_to_weight" not in existing_columns:
        cursor.execute("ALTER TABLE garmin_cycling_ftp ADD COLUMN power_to_weight REAL")

    # Chronic/Acute Training Load (PMC-Modell, siehe daily_summary.py) - Erweiterung der
    # bestehenden daily_summary-Tabelle um EWMA-basierte Fitness-/Frische-Kennzahlen.
    daily_summary_columns = {"ctl": "REAL", "atl": "REAL", "tsb": "REAL"}
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(daily_summary)")}
    for column, coltype in daily_summary_columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE daily_summary ADD COLUMN {column} {coltype}")

    # Journal-Spiegel-Spalten: werden NICHT vom Garmin-Sync (compute_daily_summary) geschrieben,
    # sondern eigenständig beim Speichern des Tagesjournals (siehe daily_summary.sync_journal_
    # columns()) - Reihenfolge-unabhängiges Spalten-Gruppen-Upsert, siehe dortiger Kommentar.
    daily_summary_journal_columns = {
        "journal_rpe": "INTEGER",
        "journal_soreness": "INTEGER",
        "journal_energy_level": "INTEGER",
    }
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(daily_summary)")}
    for column, coltype in daily_summary_journal_columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE daily_summary ADD COLUMN {column} {coltype}")

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
        # Trainingszonen nach Joe Friel, berechnet aus garmin_lactate_threshold/garmin_cycling_ftp
        # (siehe training_zones.py). Ein Zonen-"Snapshot" pro Berechnungsdatum, mehrere Zeilen
        # (eine je Zone) - deshalb dasselbe Delete+Insert-Zeitreihen-Muster wie oben, nicht
        # upsert_daily_metric (das setzt eine Zeile pro Datum voraus).
        "training_zones_running": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            zone TEXT,
            hr_min INTEGER,
            hr_max INTEGER,
            pace_min_sec_per_km REAL,
            pace_max_sec_per_km REAL
        """,
        "training_zones_cycling_hr": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            zone TEXT,
            hr_min INTEGER,
            hr_max INTEGER
        """,
        "training_zones_cycling_power": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            zone TEXT,
            power_min_watts INTEGER,
            power_max_watts INTEGER
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

    # Aktivitäten (Läufe/Rad/Schwimmen etc.) - bewusst NICHT Teil des automatischen Tages-/
    # Backfill-Syncs, sondern nur manuell über die Settings-Seite anstoßbar (siehe garmin_activities.py).
    # Primary Key ist Garmins eigene activity_id. cadence/cadence_unit fassen die je nach Sportart
    # unterschiedlich benannten Felder zusammen (averageRunningCadenceInStepsPerMinute vs.
    # averageBikingCadenceInRevPerMinute vs. averageSwimCadenceInStrokesPerMinute).
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS garmin_activities (
        activity_id INTEGER PRIMARY KEY,
        activity_name TEXT,
        activity_type TEXT,
        start_time_local TEXT,
        start_time_gmt TEXT,
        distance_meters REAL,
        duration_seconds REAL,
        elevation_gain REAL,
        elevation_loss REAL,
        average_speed REAL,
        max_speed REAL,
        calories REAL,
        average_hr REAL,
        max_hr REAL,
        hr_zone_1 REAL,
        hr_zone_2 REAL,
        hr_zone_3 REAL,
        hr_zone_4 REAL,
        hr_zone_5 REAL,
        avg_power REAL,
        max_power REAL,
        norm_power REAL,
        power_zone_1 REAL,
        power_zone_2 REAL,
        power_zone_3 REAL,
        power_zone_4 REAL,
        power_zone_5 REAL,
        cadence REAL,
        cadence_unit TEXT,
        aerobic_training_effect REAL,
        anaerobic_training_effect REAL,
        training_effect_label TEXT,
        vo2max_value REAL,
        start_latitude REAL,
        start_longitude REAL,
        end_latitude REAL,
        end_longitude REAL,
        location_name TEXT,
        device_id INTEGER,
        is_pr INTEGER,
        has_details_synced INTEGER DEFAULT 0,
        activity_training_load REAL,
        raw_json TEXT,
        synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_garmin_activities_start ON garmin_activities(start_time_local)")

    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(garmin_activities)")}
    if "activity_training_load" not in existing_columns:
        cursor.execute("ALTER TABLE garmin_activities ADD COLUMN activity_training_load REAL")

    # Rohe Sekunden-/GPS-Zeitreihe pro Aktivität (aus get_activity_details) - nur für Aktivitäten,
    # für die der Nutzer das explizit über die Settings-Seite angestoßen hat (kann pro Aktivität
    # mehrere hundert Zeilen erzeugen).
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS garmin_activity_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id INTEGER NOT NULL,
        seq INTEGER,
        timestamp INTEGER,
        latitude REAL,
        longitude REAL,
        elevation REAL,
        heart_rate REAL,
        power REAL,
        speed REAL,
        cadence REAL,
        distance REAL,
        respiration_rate REAL,
        body_battery REAL,
        stamina REAL,
        vertical_oscillation REAL,
        ground_contact_time REAL,
        temperature REAL
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_garmin_activity_details_activity_id ON garmin_activity_details(activity_id)")

    # Schicht 1 der KI-Chat-Vorbereitung: regelbasierte Pro-Aktivität-Kennzahlen (siehe
    # activity_analytics.py), berechnet direkt nach dem Laden der Detail-Zeitreihe einer Aktivität.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activity_analytics (
        activity_id INTEGER PRIMARY KEY REFERENCES garmin_activities(activity_id),
        date TEXT,
        decoupling_pct REAL,
        negative_split_bool INTEGER,
        variability_index REAL,
        hr_drift_pct REAL,
        avg_temperature REAL,
        heat_effect_flag INTEGER,
        gap_avg_pace_sec_per_km REAL,
        linked_brick_activity_id INTEGER,
        bike_to_run_pace_drop_pct REAL,
        outlier_flag INTEGER,
        computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Schicht 2 der KI-Chat-Vorbereitung: regelbasierte Wochen-Kennzahlen (siehe weekly_summary.py),
    # aufbauend auf daily_summary/activity_analytics/training_zones_*. PK ist week_id (z.B.
    # "2026-W31") statt eines Datums, damit upsert_by_key() direkt wiederverwendet werden kann.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weekly_summary (
        week_id TEXT PRIMARY KEY,
        year INTEGER,
        iso_week INTEGER,
        week_start_date TEXT,
        week_end_date TEXT,
        volume_running_km REAL,
        volume_cycling_km REAL,
        volume_swimming_km REAL,
        volume_total_minutes REAL,
        zone_distribution_z1_z2_pct REAL,
        zone_distribution_z3_plus_pct REAL,
        cross_training_run_pct REAL,
        cross_training_bike_pct REAL,
        cross_training_swim_pct REAL,
        discipline_limiter TEXT,
        longest_session_km REAL,
        longest_session_vs_4wk_trend_pct REAL,
        training_phase TEXT,
        days_until_next_race INTEGER,
        avg_readiness_7d REAL,
        avg_hrv_7d REAL,
        yoy_same_week_volume_km REAL,
        data_quality_flag TEXT,
        notable_events_text TEXT,
        computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Schicht 3 der KI-Chat-Vorbereitung: LLM-gestütztes Erkenntnis-Gedächtnis (siehe
    # insight_memory.py). insight_memory_raw wird nie von der KI verändert/gelöscht (Archiv).
    # insight_memory_compressed ist bewusst append-only - jede neue Version eine eigene Zeile
    # (hochzählendes version), damit die Entwicklung des verdichteten Textes nachvollziehbar bleibt.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS insight_memory_raw (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        raw_text TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'user' CHECK(source IN ('user', 'claude_import', 'journal'))
    )
    """)

    # SQLite kann CHECK-Constraints nicht per ALTER TABLE ändern - bei bereits bestehenden
    # Installationen (alter Constraint ohne 'journal') Tabelle neu anlegen und Daten migrieren.
    existing_sql = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='insight_memory_raw'"
    ).fetchone()
    if existing_sql and "'journal'" not in existing_sql[0]:
        cursor.execute("ALTER TABLE insight_memory_raw RENAME TO insight_memory_raw_old")
        cursor.execute("""
        CREATE TABLE insight_memory_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw_text TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user' CHECK(source IN ('user', 'claude_import', 'journal'))
        )
        """)
        cursor.execute("""
            INSERT INTO insight_memory_raw (id, created_at, raw_text, source)
            SELECT id, created_at, raw_text, source FROM insight_memory_raw_old
        """)
        cursor.execute("DROP TABLE insight_memory_raw_old")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS insight_memory_compressed (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        compressed_text TEXT,
        version INTEGER NOT NULL
    )
    """)

    # Wieder entfernt: insight_memory sollte nie datenabgeleitete Inhalte enthalten (siehe
    # insight_memory.py-Docstring) - der tägliche Auto-Lauf samt Trigger-Gate-Tabelle
    # insight_memory_daily_run war ein Fehldesign und wurde ersatzlos gestrichen.
    cursor.execute("DROP TABLE IF EXISTS insight_memory_daily_run")

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