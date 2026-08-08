import sqlite3
import os
from datetime import date, datetime

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
        hrv_status TEXT,
        hrv_last_night_avg INTEGER,
        hrv_baseline_balanced_low INTEGER,
        hrv_baseline_balanced_upper INTEGER,
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
        # most_recent_vo2max/most_recent_vo2max_cycling sind Legacy-Spalten, hier NICHT als
        # kanonische VO2max-Quelle verwenden (siehe Ground-Truth-Fund in performance.py-Kommentar):
        # bleiben in diesem API-Response eingebettet oft tagelang unverändert stehen, während
        # garmin_max_metrics deutlich aktueller/zuverlässiger ist - garmin_max_metrics ist die
        # kanonische Quelle für die Leistungsseite.
        "garmin_training_status": """
            date TEXT PRIMARY KEY,
            most_recent_vo2max REAL,
            most_recent_vo2max_cycling REAL,
            training_load_balance TEXT,
            training_status TEXT,
            training_status_label TEXT,
            training_status_code INTEGER,
            acute_training_load REAL,
            chronic_training_load REAL,
            chronic_load_min REAL,
            chronic_load_max REAL,
            acwr_status TEXT,
            acwr_ratio REAL,
            load_focus_anaerobic_pct REAL,
            load_focus_high_aerobic_pct REAL,
            load_focus_low_aerobic_pct REAL,
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
        # Heute-Ansicht (siehe daily_recommendation.py) - Gemini-generierte Tagesempfehlung,
        # als Cache/Snapshot pro Tag gespeichert. NICHT insight_memory - das bleibt ausschließlich
        # für vom Nutzer selbst eingetragene Zusatzinfos reserviert.
        "daily_recommendation": """
            date TEXT PRIMARY KEY,
            recommendation_text TEXT,
            reasoning_bullets_json TEXT,
            generated_at TIMESTAMP
        """,
        # "Fühle mich schlechter/besser als der Score sagt" - siehe daily_recommendation.py::
        # set_override_and_regenerate(). Ein gesetztes Override stößt sofort eine Neugenerierung
        # der obigen daily_recommendation mit Zusatzkontext an.
        "daily_override": """
            date TEXT PRIMARY KEY,
            override_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
        # Schlaf-Seite, "Korrelationen"-Sektion (siehe sleep_insight.py) - Gemini-Einordnung der vier
        # Korrelations-Charts, als Cache/Snapshot pro Tag gespeichert (gleiches Muster wie
        # daily_recommendation - der zugrundeliegende 28-Tage-Trend ändert sich innerhalb eines Tages
        # nicht, ein Neu-Generieren pro Seitenaufruf wäre unnötiger Gemini-Traffic).
        "sleep_correlations_insight": """
            date TEXT PRIMARY KEY,
            insight_text TEXT,
            generated_at TIMESTAMP
        """,
        # Schlaf-Seite, "Trend (28 Tage)"-Sektion (siehe sleep_trend_insight.py) - gleiches Muster
        # wie sleep_correlations_insight, nur für die Schlafdauer/-phasen/-regelmäßigkeit-Charts.
        "sleep_trend_insight": """
            date TEXT PRIMARY KEY,
            insight_text TEXT,
            generated_at TIMESTAMP
        """,
        # Körper-Seite, "Trend (90 Tage)"-Sektion (siehe body_trend_insight.py) - gleiches Muster
        # wie sleep_trend_insight, für die Gewichts-/Körperzusammensetzungs-Charts.
        "body_trend_insight": """
            date TEXT PRIMARY KEY,
            insight_text TEXT,
            generated_at TIMESTAMP
        """,
        # Leistung-Seite, Einschätzung zur Erreichbarkeit der Leistungsziele (siehe
        # performance_insight.py) - gleiches Muster, zusätzlich bei jeder Ziel-Änderung invalidiert
        # (performance_insight.py::invalidate_today_cache), da die Ziele selbst hier auf der Seite
        # bearbeitet werden.
        "performance_goals_insight": """
            date TEXT PRIMARY KEY,
            insight_text TEXT,
            generated_at TIMESTAMP
        """,
        # Rolling-Horizon-Wochenplaner (siehe weekly_planner.py) - PK date statt week_id, da
        # Heute-Ansicht/daily_recommendation.py immer "was ist heute geplant" abfragen (ein
        # SELECT...WHERE date=? statt Wochen-Lookup+Tag-Extraktion). week_id bleibt als Spalte für
        # wochenweite Operationen (Compliance-Vergleich, "ganze Woche neu generieren").
        # week_rationale_text ist auf allen 7 Zeilen einer Woche identisch (Redundanz akzeptiert,
        # vermeidet eine zweite Wochen-Tabelle für einen einzelnen Text).
        "weekly_plan": """
            date TEXT PRIMARY KEY,
            week_id TEXT,
            weekday INTEGER,
            sport_type TEXT,
            session_type TEXT,
            target_zone TEXT,
            target_duration_minutes REAL,
            target_distance_m REAL,
            is_key_session INTEGER,
            is_club_slot INTEGER,
            source TEXT,
            week_rationale_text TEXT,
            data_quality_flag TEXT,
            generated_at TIMESTAMP
        """,
        # Habit-Tracker (Schlaf-Seite) - Faktoren, die Garmin nicht liefert, aber den Schlaf
        # plausibel beeinflussen. Bewusst ein fester, schmaler Satz an Feldern statt eines generischen
        # Key-Value-Modells (passt zum Rest der App - neue Habits kommen bei Bedarf per ALTER TABLE
        # dazu, wie bei allen anderen Tabellen hier auch). last_screen_time/last_meal_time als
        # "HH:MM"-Freitext statt Minuten-Schätzung/vollem Timestamp - eine Uhrzeit ist leichter zu
        # erinnern, die Minuten bis zur Bettzeit werden serverseitig aus sleep_start_local abgeleitet
        # (siehe backend/routers/sleep.py).
        "habit_tracker": """
            date TEXT PRIMARY KEY,
            caffeine_after_noon INTEGER,
            last_screen_time TEXT,
            last_meal_time TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """,
    }
    for table_name, columns_sql in daily_tables.items():
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_sql})")

    # is_key_session (Kern- vs. flexible Einheit, siehe weekly_planner.py SYSTEM_PROMPT) - nachträglich
    # ergänzte Spalte, ALTER TABLE nötig für bereits bestehende Installationen (NULL = unbekannt/
    # Renntag, nicht mit False/flexibel gleichzusetzen).
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(weekly_plan)")}
    if "is_key_session" not in existing_columns:
        cursor.execute("ALTER TABLE weekly_plan ADD COLUMN is_key_session INTEGER")

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

    # Schlaf-Seite: weitere, bisher ungenutzte Felder aus derselben get_sleep_data()-Antwort (siehe
    # garmin_service.py) - kein neuer API-Call, nur zusätzliches Parsing. sleep_start_local/
    # sleep_end_local als ISO-Datetime-Strings (aus Garmins Epoch-Millisekunden umgerechnet).
    # recommended_bedtime_*_mins sind Minuten seit Mitternacht des Vortages (können >1440 sein, wenn
    # das Fenster über Mitternacht reicht - Frontend rechnet das in eine Uhrzeit um).
    sleep_phases_columns = {
        "sleep_start_local": "TEXT",
        "sleep_end_local": "TEXT",
        "total_duration_qualifier": "TEXT",
        "stress_qualifier": "TEXT",
        "restlessness_qualifier": "TEXT",
        "awake_count_qualifier": "TEXT",
        "sleep_need_baseline_seconds": "INTEGER",
        "sleep_need_hrv_adjustment": "TEXT",
        "sleep_need_training_feedback": "TEXT",
        "recommended_bedtime_start_mins": "INTEGER",
        "recommended_bedtime_end_mins": "INTEGER",
        "restless_moments_count": "INTEGER",
        "avg_overnight_hrv": "REAL",
        "body_battery_change": "INTEGER",
        "avg_skin_temp_deviation_c": "REAL",
        "avg_sleep_spo2": "REAL",
        "lowest_sleep_spo2": "REAL",
        "avg_sleep_respiration": "REAL",
        "sleep_score_feedback": "TEXT",
        "sleep_score_insight": "TEXT",
        "sleep_score_qualifier": "TEXT",
    }
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(garmin_sleep_phases)")}
    for column, coltype in sleep_phases_columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE garmin_sleep_phases ADD COLUMN {column} {coltype}")

    # Habit-Tracker: "Alkohol getrunken" wieder entfernt (Nutzer trinkt nicht, Feld war für ihn
    # irrelevant) - DROP COLUMN statt nur in der UI zu verstecken, um keine tote Spalte
    # mitzuschleppen. Erfordert SQLite >= 3.35 (hier: 3.46, siehe Docker-Image).
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(habit_tracker)")}
    if "alcohol" in existing_columns:
        cursor.execute("ALTER TABLE habit_tracker DROP COLUMN alcohol")

    # Bildschirmzeit-Slider (Minuten) durch eine Uhrzeit-Eingabe ersetzt (siehe HabitTrackerCard.tsx-
    # Kommentar) - andere Spalte (Typ + Semantik ändern sich), deshalb Drop+Add statt RENAME COLUMN.
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(habit_tracker)")}
    if "screen_time_before_bed_minutes" in existing_columns:
        cursor.execute("ALTER TABLE habit_tracker DROP COLUMN screen_time_before_bed_minutes")
    if "last_screen_time" not in existing_columns:
        cursor.execute("ALTER TABLE habit_tracker ADD COLUMN last_screen_time TEXT")

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

    # Trainingszustand/Belastungsfokus aus dem bisher nur als Roh-JSON gespeicherten
    # training_status/training_load_balance geparst (siehe garmin_service.py::_fetch_advanced_health,
    # "Leistung"-Seite) - vorher landeten diese Werte nie in eigenen, abfragbaren Spalten.
    training_status_columns = {
        "training_status_label": "TEXT", "training_status_code": "INTEGER",
        "acute_training_load": "REAL", "chronic_training_load": "REAL",
        "chronic_load_min": "REAL", "chronic_load_max": "REAL",
        "acwr_status": "TEXT", "acwr_ratio": "REAL",
        "load_focus_anaerobic_pct": "REAL", "load_focus_high_aerobic_pct": "REAL",
        "load_focus_low_aerobic_pct": "REAL",
    }
    for column, coltype in training_status_columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE garmin_training_status ADD COLUMN {column} {coltype}")

    # HRV-Status (Garmins eigene "Balanced/Unbalanced"-Einordnung, nicht nur der rohe ms-Wert) -
    # wird bereits per get_hrv_data() abgerufen, lag bisher nur ungenutzt im raw_json-Blob.
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(garmin_daily)")}
    hrv_status_columns = {
        "hrv_status": "TEXT", "hrv_last_night_avg": "INTEGER",
        "hrv_baseline_balanced_low": "INTEGER", "hrv_baseline_balanced_upper": "INTEGER",
    }
    for column, coltype in hrv_status_columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE garmin_daily ADD COLUMN {column} {coltype}")

    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(garmin_cycling_ftp)")}
    if "power_to_weight" not in existing_columns:
        cursor.execute("ALTER TABLE garmin_cycling_ftp ADD COLUMN power_to_weight REAL")

    # Datenkorrektur (kein Schema-Wechsel): garmin_service.py korrigiert Garmins Lactate-Threshold-
    # "speed" seit einem bestimmten Zeitpunkt um Faktor 10 (Garmin liefert sie zu klein, verifiziert:
    # Rohwert 0.369 -> absurde Pace ~45 min/km, *10 -> 3.69 m/s -> plausible 4:31 min/km). Zeilen, die
    # VOR diesem Fix synchronisiert wurden, stehen unkorrigiert in der DB und tauchen seit der
    # "früheste verfügbare Messung"-Fortschrittsanzeige (siehe backend/routers/performance.py) erstmals
    # sichtbar auf. speed < 1.0 m/s (="langsamer als 16:40 min/km") ist für einen Schwellentest nicht
    # plausibel und eindeutig dieser Bug, nicht ein echter Messwert - einmalig automatisch korrigiert.
    cursor.execute("UPDATE garmin_lactate_threshold SET speed = speed * 10 WHERE speed IS NOT NULL AND speed < 1.0")

    # Datenkorrektur (kein Schema-Wechsel): weekly_planner.py hat vor der sport_type-abhängigen
    # Normalisierung (siehe dortiger Kommentar) an Ruhetagen (sport_type NULL) teils trotzdem
    # target_zone/-duration/-distance vom Modell übernommen (Ground-Truth-Fund: "Zone 1" auf einem
    # Ruhetag) - führte auf der Woche-Seite zu unsinnigen Anzeigen wie "Ruhetag · Zone 1". Bereits
    # generierte Altzeilen bleiben ohne diese Korrektur betroffen, bis sie neu generiert werden -
    # einmalig automatisch bereinigt statt auf ein manuelles "Woche neu generieren" zu warten.
    cursor.execute(
        "UPDATE weekly_plan SET target_zone = NULL, target_duration_minutes = NULL, target_distance_m = NULL "
        "WHERE sport_type IS NULL AND (target_zone IS NOT NULL OR target_duration_minutes IS NOT NULL "
        "OR target_distance_m IS NOT NULL)"
    )

    # Chronic/Acute Training Load (PMC-Modell, siehe daily_summary.py) - Erweiterung der
    # bestehenden daily_summary-Tabelle um EWMA-basierte Fitness-/Frische-Kennzahlen.
    daily_summary_columns = {"ctl": "REAL", "atl": "REAL", "tsb": "REAL"}
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(daily_summary)")}
    for column, coltype in daily_summary_columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE daily_summary ADD COLUMN {column} {coltype}")

    # 28-Tage-Ruhepuls-Baseline (existierte bisher nur als 7-Tage-Version, siehe
    # resting_hr_vs_7d_avg_pct oben) - analog zur bereits vorhandenen hrv_vs_28d_avg_pct-Spalte,
    # für die neue "Trainingslast am Vorabend vs. Ruhepuls-Abweichung"-Korrelation.
    daily_summary_rhr_28d_columns = {"resting_hr_vs_28d_avg_pct": "REAL"}
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(daily_summary)")}
    for column, coltype in daily_summary_rhr_28d_columns.items():
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

    # Schicht 4: persistenter Chat-Verlauf (siehe chat_engine.py) - bewusst in der DB statt nur
    # Streamlit-session_state, damit beim künftigen FastAPI-Umbau kein State migriert werden muss.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        tool_calls_json TEXT
    )
    """)

    # Status des täglichen Auto-Sync-Triggers (siehe auto_sync.py) - PK date, spaltengruppenweise
    # per upsert_daily_metric() beschrieben (Check-Spalten vs. Abschluss-Spalten unabhängig).
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auto_sync_status (
        date TEXT PRIMARY KEY,
        first_check_at TIMESTAMP,
        last_check_at TIMESTAMP,
        check_count INTEGER DEFAULT 0,
        sleep_data_found INTEGER DEFAULT 0,
        full_sync_completed_at TIMESTAMP,
        gave_up_at TIMESTAMP,
        last_error TEXT
    )
    """)

    # Chronologischer Sync-Verlauf (Einstellungen-Seite), geteilt zwischen Garmin und Withings
    # (provider-Spalte) - anders als auto_sync_status oben (eine Zeile PRO TAG, aggregiert)
    # protokolliert diese Tabelle JEDEN einzelnen Lauf einzeln (append-only, AUTOINCREMENT-id),
    # damit die Historie auch mehrere Läufe desselben Tages einzeln sichtbar macht. sync_type
    # unterscheidet die Auslöser: "check" (nur Garmin - Schlafdaten-Verfügbarkeits-Check, siehe
    # auto_sync.py::check_sleep_data_available), "auto" (automatischer Sync, bei Garmin der aus dem
    # Check ausgelöste volle Tages-Sync, bei Withings der stündliche Token-Keepalive-Sync) und
    # "manual" (TopBar-Button/Einstellungen-Formular).
    cursor.execute("DROP TABLE IF EXISTS garmin_sync_log")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP NOT NULL,
        provider TEXT NOT NULL,
        sync_type TEXT NOT NULL,
        status TEXT NOT NULL,
        detail TEXT
    )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_log_provider_timestamp ON sync_log(provider, timestamp)"
    )

    # Wiederkehrende Vereins-Trainingstermine (siehe training_slots.py) - kein date-PK, mehrere
    # Slots pro Wochentag möglich, daher eigenständige id/AUTOINCREMENT-Tabelle statt Aufnahme in
    # das obige daily_tables-Dict (das ist ausschließlich für date-PK-Tabellen gedacht).
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS club_training_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        weekday INTEGER NOT NULL,
        sport_type TEXT NOT NULL,
        label TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_to TEXT
    )
    """)
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(club_training_slots)")}
    if "typical_character" not in existing_columns:
        # Freitext für den Wochenplaner (siehe weekly_planner.py) - was an diesem Slot realistisch
        # möglich ist (z.B. "Bahntraining: meist Intervalle, 400-1000m Wiederholungen"). Optional,
        # leer lassen ist erlaubt.
        cursor.execute("ALTER TABLE club_training_slots ADD COLUMN typical_character TEXT")

    # Workout-Entwürfe des Wochenplaners (siehe weekly_planner.py) - ein Tag kann keinen, einen
    # Entwurf haben (nur bei sport_type="Laufen", siehe dortige Sport-Abdeckungs-Einschränkung).
    # Speichert bewusst NICHT das gebaute Workout-Objekt, sondern Builder-Name + Parameter - wird
    # bei Bedarf (Upload / Vorbefüllung in pages/6_🏗️_Workout_Builder.py) frisch neu gebaut,
    # robuster als Objekt-Serialisierung und dieselben Parameter dienen direkt als Formular-Default.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weekly_plan_workout_draft (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        builder_name TEXT NOT NULL,
        builder_params_json TEXT NOT NULL,
        uploaded_at TIMESTAMP
    )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_weekly_plan_workout_draft_date ON weekly_plan_workout_draft(date)"
    )

    # Withings-Waagen-Daten (siehe withings_service.py) - direkt bei Withings statt über Garmins
    # lückenhafte Weiterleitung abgeholt. Eigene Tabelle statt Wiederverwendung von
    # garmin_weigh_ins: andere PK-Domäne (Withings' grpid statt Garmins sample_pk), andere
    # Spaltenmenge (keine Garmin-eigenen Herleitungen wie visceral_fat/metabolic_age).
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS withings_weigh_ins (
        grpid INTEGER PRIMARY KEY,
        date TEXT NOT NULL,
        weight REAL,
        body_fat REAL,
        body_water REAL,
        bone_mass REAL,
        muscle_mass REAL,
        fat_mass_kg REAL,
        attrib TEXT,
        timestamp INTEGER
    )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_withings_weigh_ins_date ON withings_weigh_ins(date)"
    )

    # Körper-Seite (siehe body_composition.py): zwei feste, vom Nutzer selbst gepflegte
    # Personenwerte statt eines eigenen Nutzerprofil-Konstrukts - Körpergröße (für FFMI) und
    # Zielgewicht (für den What-if-Simulator). Generischer key/value-Aufbau (statt fester Spalten),
    # da beide Werte dieselbe einfache "ein Zahlenwert, jederzeit überschreibbar"-Semantik haben.
    # source unterscheidet bei height_cm zwischen 'garmin' (täglich automatisch aus
    # get_user_profile() übernommen, siehe garmin_service.py::_fetch_body_composition) und 'manual'
    # (unter Einstellungen überschrieben - ein Garmin-Sync überschreibt einen manuellen Wert dann
    # NICHT mehr, siehe body_composition.py::sync_height_from_garmin). Bei target_weight_kg bleibt
    # source ungenutzt (NULL) - das Zielgewicht hat keine Garmin-Quelle.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS body_settings (
        key TEXT PRIMARY KEY,
        value REAL,
        source TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(body_settings)")}
    if "source" not in existing_columns:
        cursor.execute("ALTER TABLE body_settings ADD COLUMN source TEXT")

    # Körper-Seite: Schmerz-/Verletzungsprotokoll. AUTOINCREMENT-id statt date-PK, da an einem Tag
    # mehrere Beschwerden an unterschiedlichen Körperstellen protokolliert werden können.
    # resolved_at (NULL = noch aktiv) trägt die "aktive Baustellen"-Badges auf der Körper-Seite.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS injury_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        body_part TEXT NOT NULL,
        severity INTEGER NOT NULL,
        pain_type TEXT,
        context TEXT,
        notes TEXT,
        resolved_at TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_injury_log_date ON injury_log(date)"
    )

    # Leistungsziele (siehe "Leistung"-Seite/performance.py) - bewusst zwei getrennte Tabellen
    # statt einer: race_goals sind renn-spezifisch (an einen konkreten Kalendereintrag gebunden),
    # performance_goals sind generische, nicht renn-gebundene Leistungs-Benchmarks für die
    # Vergleiche auf der Leistungsseite (z.B. Marathon-Pace-Ziel). performance_goals-Zeilen bleiben
    # jederzeit manuell editierbar, auch wenn sie ursprünglich aus einem race_goals-Eintrag
    # abgeleitet wurden (derived_from_race_goal_id ist reine Herkunfts-Info, keine Sperre).
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS race_goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL REFERENCES garmin_scheduled_events(id),
        target_time_seconds INTEGER,
        target_splits_json TEXT,
        rationale_text TEXT,
        set_by TEXT NOT NULL DEFAULT 'user' CHECK(set_by IN ('user', 'ai_conversation')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # FTP-Ziel bewusst als W/kg (ftp_w_per_kg), nicht als reine Watt-Zahl - vergleichbar mit dem
    # bereits körpergewichts-normalisierten power_to_weight-Ist-Wert aus garmin_cycling_ftp/
    # garmin_lactate_threshold (siehe performance.py). Kein Ziel-VO2max - das ist ein
    # Trainingsergebnis, kein Wert, auf den gezielt hintrainiert wird wie Pace/Watt.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS performance_goals (
        key TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        target_value REAL NOT NULL,
        unit TEXT NOT NULL,
        derived_from_race_goal_id INTEGER REFERENCES race_goals(id),
        notes TEXT,
        target_date TEXT,
        start_date TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # target_date (Datum, bis zu dem das Ziel erreicht sein soll) und start_date (Datum, ab dem der
    # Fortschritt gemessen wird - siehe backend/routers/performance.py::_metric_value für die
    # zugehörige Ist-Wert-Ableitung aus echten Garmin-Zeitreihen) - beide nachträglich ergänzt,
    # ALTER TABLE nötig für bereits bestehende Installationen.
    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(performance_goals)")}
    if "target_date" not in existing_columns:
        cursor.execute("ALTER TABLE performance_goals ADD COLUMN target_date TEXT")
    if "start_date" not in existing_columns:
        cursor.execute("ALTER TABLE performance_goals ADD COLUMN start_date TEXT")

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
        body_battery_max, body_battery_min, stress_avg, steps,
        hrv_status, hrv_last_night_avg, hrv_baseline_balanced_low, hrv_baseline_balanced_upper,
        raw_json
    ) VALUES (:date, :resting_hr, :avg_hrv, :sleep_score, :sleep_hours,
              :body_battery_max, :body_battery_min, :stress_avg, :steps,
              :hrv_status, :hrv_last_night_avg, :hrv_baseline_balanced_low, :hrv_baseline_balanced_upper,
              :raw_json)
    ON CONFLICT(date) DO UPDATE SET
        resting_hr=excluded.resting_hr,
        avg_hrv=excluded.avg_hrv,
        sleep_score=excluded.sleep_score,
        sleep_hours=excluded.sleep_hours,
        body_battery_max=excluded.body_battery_max,
        body_battery_min=excluded.body_battery_min,
        stress_avg=excluded.stress_avg,
        steps=excluded.steps,
        hrv_status=excluded.hrv_status,
        hrv_last_night_avg=excluded.hrv_last_night_avg,
        hrv_baseline_balanced_low=excluded.hrv_baseline_balanced_low,
        hrv_baseline_balanced_upper=excluded.hrv_baseline_balanced_upper,
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

def log_sync_event(provider, sync_type, status, detail=None):
    """Ein Eintrag im chronologischen Sync-Verlauf (siehe sync_log-Schema in init_db()) -
    provider: "garmin"/"withings", sync_type: "check"/"auto"/"manual"."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO sync_log (timestamp, provider, sync_type, status, detail) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), provider, sync_type, status, detail)
    )
    conn.commit()
    conn.close()


def list_sync_log(provider, limit=50):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, timestamp, provider, sync_type, status, detail FROM sync_log "
        "WHERE provider = ? ORDER BY timestamp DESC, id DESC LIMIT ?",
        (provider, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print("SQLite Datenbank erfolgreich initialisiert!")