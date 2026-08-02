"""
Gemeinsame Logik zum testweisen Abrufen aller Tier-1/2-Endpunkte,
nutzbar aus der Settings-UI (läuft im selben Prozess wie der funktionierende
Einzel-Sync, um das Token-Problem bei separaten Prozessen zu vermeiden).
"""
import json
import time
import random
from datetime import date, timedelta
from pathlib import Path

from garminconnect import GarminConnectTooManyRequestsError

OUTPUT_DIR = Path("garmin_api_exploration")


def _build_calls():
    today = date.today()
    week_start = today - timedelta(days=7)
    today_str = today.isoformat()
    week_start_str = week_start.isoformat()

    return [
        # # --- Daily Health & Activity ---
        # ("get_stats", lambda c: c.get_stats(today_str)),
        # ("get_steps_data", lambda c: c.get_steps_data(today_str)),
        # ("get_heart_rates", lambda c: c.get_heart_rates(today_str)),
        # ("get_resting_heart_rate", lambda c: c.get_resting_heart_rate(today_str)),
        # ("get_sleep_data", lambda c: c.get_sleep_data(today_str)),
        # ("get_all_day_stress", lambda c: c.get_all_day_stress(today_str)),
        # ("get_lifestyle_logging_data", lambda c: c.get_lifestyle_logging_data(today_str)),

        # # --- Advanced Health Metrics ---
        # ("get_training_readiness", lambda c: c.get_training_readiness(today_str)),
        # ("get_morning_training_readiness", lambda c: c.get_morning_training_readiness(today_str)),
        # ("get_training_status", lambda c: c.get_training_status(today_str)),
        # ("get_respiration_data", lambda c: c.get_respiration_data(today_str)),
        # ("get_spo2_data", lambda c: c.get_spo2_data(today_str)),
        # ("get_max_metrics", lambda c: c.get_max_metrics(today_str)),
        # ("get_hrv_data", lambda c: c.get_hrv_data(today_str)),
        # ("get_fitnessage_data", lambda c: c.get_fitnessage_data(today_str)),
        # ("get_stress_data", lambda c: c.get_stress_data(today_str)),
        # ("get_lactate_threshold", lambda c: c.get_lactate_threshold(latest=True)),
        # ("get_intensity_minutes_data", lambda c: c.get_intensity_minutes_data(today_str)),
        # ("get_running_tolerance", lambda c: c.get_running_tolerance(week_start_str, today_str)),

        # # --- Historical Data & Trends ---
        # ("get_body_battery", lambda c: c.get_body_battery(week_start_str, today_str)),
        # ("get_floors", lambda c: c.get_floors(today_str)),
        # ("get_blood_pressure", lambda c: c.get_blood_pressure(week_start_str, today_str)),
        # ("get_body_battery_events", lambda c: c.get_body_battery_events(today_str)),

        # # --- Body Composition & Weight ---
        # ("get_body_composition", lambda c: c.get_body_composition(today_str)),
        # ("get_weigh_ins", lambda c: c.get_weigh_ins(week_start_str, today_str)),

        # --- Goals & Achievements ---
        ("get_race_predictions", lambda c: c.get_race_predictions()),
        # Hinweis: get_active_goals()/get_future_goals() gibt es in der installierten
        # garminconnect-Version (0.3.6) nicht - stattdessen get_goals(status=...).
        # Dateiname bleibt get_active_goals/get_future_goals, damit er zu dem passt, was wir suchen.
        ("get_active_goals", lambda c: c.get_goals(status="active")),
        ("get_future_goals", lambda c: c.get_goals(status="future")),
        ("get_scheduled_workouts", lambda c: c.get_scheduled_workouts(2026, 9)),

        # # --- Hydration & Wellness ---
        # ("get_hydration_data", lambda c: c.get_hydration_data(today_str)),
        # ("get_pregnancy_summary", lambda c: c.get_pregnancy_summary()),
        # ("get_all_day_events", lambda c: c.get_all_day_events(today_str)),
        # ("get_nutrition_daily_food_log", lambda c: c.get_nutrition_daily_food_log(today_str)),
        # ("get_nutrition_daily_meals", lambda c: c.get_nutrition_daily_meals(today_str)),
        # ("get_nutrition_daily_settings", lambda c: c.get_nutrition_daily_settings(today_str)),

        # --- NEU: alles, was in garminconnect 0.3.6 sonst noch an lesenden (nicht-mutierenden)
        # Endpunkten existiert und bisher weder oben aktiv noch auskommentiert war. add_*/set_*/
        # delete_*/create_*/upload_*/schedule_* wurden bewusst ausgelassen, ebenso alles, was eine
        # spezifische ID braucht, die wir noch nicht kennen (activity_id, gearUUID, device_id,
        # plan_id, workout_id...), und Golf/Menstruations-Endpunkte (nicht relevant hier).

        # --- Profil & Konto ---
        ("get_full_name", lambda c: c.get_full_name()),
        ("get_unit_system", lambda c: c.get_unit_system()),
        ("get_user_profile", lambda c: c.get_user_profile()),
        ("get_userprofile_settings", lambda c: c.get_userprofile_settings()),

        # --- Geräte ---
        ("get_devices", lambda c: c.get_devices()),
        ("get_primary_training_device", lambda c: c.get_primary_training_device()),
        ("get_device_last_used", lambda c: c.get_device_last_used()),
        ("get_device_alarms", lambda c: c.get_device_alarms()),

        # --- Aktivitäten (einmaliger Blick, kein laufender Sync - Tier 3 bleibt manueller .fit-Upload) ---
        ("count_activities", lambda c: c.count_activities()),
        ("get_last_activity", lambda c: c.get_last_activity()),
        ("get_activities", lambda c: c.get_activities()),
        ("get_activity_types", lambda c: c.get_activity_types()),

        # --- Trainingspläne (für den Marathon relevant) ---
        ("get_training_plans", lambda c: c.get_training_plans()),

        # --- Workouts (Liste, keine ID nötig) ---
        ("get_workouts", lambda c: c.get_workouts()),

        # --- Weitere Tages-/Wochen-Aggregat-Varianten, bisher nicht getestet ---
        ("get_user_summary", lambda c: c.get_user_summary(today_str)),
        ("get_stats_and_body", lambda c: c.get_stats_and_body(today_str)),
        ("get_rhr_day", lambda c: c.get_rhr_day(today_str)),
        ("get_daily_weigh_ins", lambda c: c.get_daily_weigh_ins(today_str)),
        ("get_daily_steps", lambda c: c.get_daily_steps(week_start_str, today_str)),
        ("get_weekly_steps", lambda c: c.get_weekly_steps(today_str, weeks=4)),
        ("get_weekly_stress", lambda c: c.get_weekly_stress(today_str, weeks=4)),
        ("get_weekly_intensity_minutes", lambda c: c.get_weekly_intensity_minutes(week_start_str, today_str)),

        # --- Leistungsscores ---
        ("get_endurance_score", lambda c: c.get_endurance_score(week_start_str, today_str)),
        ("get_hill_score", lambda c: c.get_hill_score(week_start_str, today_str)),
        ("get_cycling_ftp", lambda c: c.get_cycling_ftp()),

        # --- Herausforderungen & Abzeichen ---
        ("get_personal_record", lambda c: c.get_personal_record()),
        ("get_earned_badges", lambda c: c.get_earned_badges()),
        ("get_available_badges", lambda c: c.get_available_badges()),
        ("get_in_progress_badges", lambda c: c.get_in_progress_badges()),
        ("get_adhoc_challenges", lambda c: c.get_adhoc_challenges(0, 20)),
        ("get_badge_challenges", lambda c: c.get_badge_challenges(0, 20)),
        ("get_available_badge_challenges", lambda c: c.get_available_badge_challenges(0, 20)),
        ("get_non_completed_badge_challenges", lambda c: c.get_non_completed_badge_challenges(0, 20)),
        ("get_inprogress_virtual_challenges", lambda c: c.get_inprogress_virtual_challenges(0, 20)),
    ]


def run_exploration(client, on_progress=None, save_to_disk=True):
    """Ruft alle Testendpunkte einmal auf.

    on_progress: optionales Callback(name, index, total, status, data_or_error),
    status ist "ok", "error" oder "rate_limited".

    Gibt ein dict {name: {"success": bool, "data": ..., "error": str|None}} zurück.
    Bricht bei einem 429 sofort komplett ab (stoppt weitere Calls).
    """
    calls = _build_calls()
    total = len(calls)
    results = {}

    if save_to_disk:
        OUTPUT_DIR.mkdir(exist_ok=True)

    for i, (name, func) in enumerate(calls, start=1):
        try:
            data = func(client)
            results[name] = {"success": True, "data": data, "error": None}
            if save_to_disk:
                filepath = OUTPUT_DIR / f"{name}.json"
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str, ensure_ascii=False)
            if on_progress:
                on_progress(name, i, total, "ok", data)
            time.sleep(random.uniform(2, 4))
        except GarminConnectTooManyRequestsError as e:
            results[name] = {"success": False, "data": None, "error": str(e)}
            if on_progress:
                on_progress(name, i, total, "rate_limited", str(e))
            break
        except Exception as e:
            if "429" in str(e):
                results[name] = {"success": False, "data": None, "error": str(e)}
                if on_progress:
                    on_progress(name, i, total, "rate_limited", str(e))
                break
            results[name] = {"success": False, "data": None, "error": str(e)}
            if on_progress:
                on_progress(name, i, total, "error", str(e))
            time.sleep(random.uniform(2, 4))

    return results
