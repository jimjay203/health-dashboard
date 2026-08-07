import json
import time
import random
from datetime import date, datetime, timedelta
from garminconnect import GarminConnectTooManyRequestsError
from garmin_auth import get_garmin_client
from db import save_garmin_data, upsert_daily_metric, replace_timeseries, upsert_weigh_in, upsert_by_key, get_connection
from training_zones import recompute_zones
from daily_summary import compute_daily_summary
from weekly_summary import compute_weekly_summary


def _epoch_ms_local_to_iso(epoch_ms):
    """Garmins "...TimestampLocal"-Felder sind KEINE echten UTC-Timestamps, sondern UTC-Epoch-
    Millisekunden, die bereits um den lokalen Zeitzonen-Offset verschoben wurden (ground-truth
    verifiziert: sleepStartTimestampLocal - sleepStartTimestampGMT = 7200000ms = 2h = CEST-Offset)
    - utcfromtimestamp() liefert dadurch direkt die korrekte lokale Wanduhrzeit, kein zusätzliches
    Zeitzonen-Handling nötig."""
    if epoch_ms is None:
        return None
    return datetime.utcfromtimestamp(epoch_ms / 1000.0).isoformat()


def _pause():
    # Tempo von garmin_explore.py übernommen, das nachweislich 30 Endpunkte am Stück
    # ohne 429 durchbekommt - kürzere Pausen hatten die Erweiterung ins Wackeln gebracht.
    time.sleep(random.uniform(2, 4))


def _safe_call(client, label, func):
    """Ruft einen einzelnen Garmin-Endpunkt auf. Ein 429 wird durchgereicht und bricht
    den gesamten Sync ab (siehe fetch_and_store_garmin_data); alle anderen Fehler
    (z.B. Endpunkt für dieses Gerät/Konto nicht verfügbar) werden geloggt und übersprungen,
    damit ein einzelner fehlender Datentyp nicht den ganzen Tages-Sync killt.
    """
    try:
        result = func(client)
        _pause()
        return result
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:
        if "429" in str(e):
            raise
        print(f"⚠️  {label} übersprungen: {e}")
        return None


def _primary_device_entry(data_by_device_id):
    """latestTrainingStatusData ist ein Dict keyed by deviceId (String) - bei mehreren
    Geräten/Quellen das als primaryTrainingDevice=True markierte nehmen, sonst das erste.
    None, falls data_by_device_id leer/None ist."""
    if not data_by_device_id:
        return None
    for entry in data_by_device_id.values():
        if entry.get("primaryTrainingDevice"):
            return entry
    return next(iter(data_by_device_id.values()))


def _parse_load_focus_pct(load_balance):
    """Anaerob/Hoch-Aerob/Niedrig-Aerob-Verteilung aus metricsTrainingLoadBalanceDTOMap - Ground-
    Truth-Fund: für dieses Konto bisher in JEDEM synchronisierten Tag null (Garmin liefert diese
    Aufschlüsselung offenbar nicht für jedes Gerät/jeden Kontostand). Feldnamen hier daher NICHT an
    echten befüllten Daten verifizierbar (best effort anhand dokumentierter Garmin-Connect-Felder) -
    gibt (None, None, None) zurück, falls die Map fehlt/leer ist oder die erwarteten Felder nicht
    vorhanden sind, statt etwas zu erfinden. Bei Bedarf anhand echter befüllter Daten nachschärfen,
    sobald Garmin sie für dieses Konto einmal liefert."""
    dto_map = (load_balance or {}).get("metricsTrainingLoadBalanceDTOMap")
    if not dto_map:
        return None, None, None
    entry = _primary_device_entry(dto_map)
    if not entry:
        return None, None, None
    anaerobic = entry.get("monthlyLoadAnaerobic")
    high_aerobic = entry.get("monthlyLoadAerobicHigh")
    low_aerobic = entry.get("monthlyLoadAerobicLow")
    if anaerobic is None or high_aerobic is None or low_aerobic is None:
        return None, None, None
    total = anaerobic + high_aerobic + low_aerobic
    if not total:
        return None, None, None
    return (
        round(anaerobic / total * 100, 1),
        round(high_aerobic / total * 100, 1),
        round(low_aerobic / total * 100, 1),
    )


def fetch_and_store_garmin_data(target_date=None, client=None):
    """Holt die Kern-Metriken sowie alle erweiterten Metrik-Gruppen für ein Datum und
    speichert sie in SQLite. Erlaubt die Übergabe eines bestehenden Client-Objekts für Re-Use.
    """
    if not target_date:
        target_date = date.today().isoformat()

    # Wenn kein Client übergeben wurde, gecachten/persistierten Client nutzen
    # statt jedes Mal neu per Passwort einzuloggen.
    if client is None:
        client = get_garmin_client()

    # --- Kern-Metriken (garmin_daily), wie bisher ---
    try:
        stats = client.get_stats(target_date)
        _pause()
        sleep_data = client.get_sleep_data(target_date)
        _pause()
        hrv_data = client.get_hrv_data(target_date)
        _pause()
    except GarminConnectTooManyRequestsError as e:
        raise RuntimeError(f"429 Rate-Limit bei {target_date}: {e}") from e

    # Garmin liefert für Tage ohne Sync/Tragezeit der Uhr manchmal None statt eines dict
    stats = stats or {}

    resting_hr = stats.get("restingHeartRate")
    steps = stats.get("totalSteps")
    stress_avg = stats.get("averageStressLevel")

    sleep_score = None
    sleep_hours = None
    if sleep_data and "dailySleepDTO" in sleep_data:
        dto = sleep_data["dailySleepDTO"]
        sleep_score = ((dto.get("sleepScores") or {}).get("overall") or {}).get("value")
        sleep_seconds = dto.get("sleepTimeSeconds", 0)
        sleep_hours = round(sleep_seconds / 3600.0, 2) if sleep_seconds else None

        # Schlafphasen (REM/Tief/Leicht/Wach) - kommen mit derselben get_sleep_data()-Antwort mit,
        # bisher nur ungenutzt hier verfügbar (Schicht 1 der KI-Chat-Vorbereitung, siehe daily_summary.py).
        sleep_scores = dto.get("sleepScores") or {}
        deep_pct_obj = sleep_scores.get("deepPercentage") or {}
        light_pct_obj = sleep_scores.get("lightPercentage") or {}
        rem_pct_obj = sleep_scores.get("remPercentage") or {}
        # Weitere Qualifier aus derselben sleepScores-Struktur, bisher ebenfalls ungenutzt.
        total_duration_obj = sleep_scores.get("totalDuration") or {}
        stress_qualifier_obj = sleep_scores.get("stress") or {}
        restlessness_obj = sleep_scores.get("restlessness") or {}
        awake_count_obj = sleep_scores.get("awakeCount") or {}
        sleep_need = dto.get("sleepNeed") or {}
        sleep_need_minutes = sleep_need.get("actual")
        sleep_need_baseline_minutes = sleep_need.get("baseline")
        # Schlaf-Seite (siehe backend/routers/sleep.py): Bettzeiten für die Regelmäßigkeits-
        # Auswertung, Garmins eigene Bettzeit-Empfehlung, Overnight-HRV/SpO2/Atmung/Hauttemperatur -
        # restlessMomentsCount/avgOvernightHrv/bodyBatteryChange/avgSkinTempDeviationC liegen als
        # Geschwister von dailySleepDTO auf der obersten Ebene der Antwort, nicht darin.
        upsert_daily_metric("garmin_sleep_phases", {
            "date": target_date,
            "deep_sleep_seconds": dto.get("deepSleepSeconds"),
            "light_sleep_seconds": dto.get("lightSleepSeconds"),
            "rem_sleep_seconds": dto.get("remSleepSeconds"),
            "awake_sleep_seconds": dto.get("awakeSleepSeconds"),
            "deep_pct": deep_pct_obj.get("value"),
            "light_pct": light_pct_obj.get("value"),
            "rem_pct": rem_pct_obj.get("value"),
            "deep_qualifier": deep_pct_obj.get("qualifierKey"),
            "light_qualifier": light_pct_obj.get("qualifierKey"),
            "rem_qualifier": rem_pct_obj.get("qualifierKey"),
            "awake_count": dto.get("awakeCount"),
            "avg_sleep_stress": dto.get("avgSleepStress"),
            "avg_sleep_hr": dto.get("avgHeartRate"),
            "sleep_need_seconds": sleep_need_minutes * 60 if sleep_need_minutes is not None else None,
            "sleep_start_local": _epoch_ms_local_to_iso(dto.get("sleepStartTimestampLocal")),
            "sleep_end_local": _epoch_ms_local_to_iso(dto.get("sleepEndTimestampLocal")),
            "total_duration_qualifier": total_duration_obj.get("qualifierKey"),
            "stress_qualifier": stress_qualifier_obj.get("qualifierKey"),
            "restlessness_qualifier": restlessness_obj.get("qualifierKey"),
            "awake_count_qualifier": awake_count_obj.get("qualifierKey"),
            "sleep_need_baseline_seconds": sleep_need_baseline_minutes * 60 if sleep_need_baseline_minutes is not None else None,
            "sleep_need_hrv_adjustment": sleep_need.get("hrvAdjustment"),
            "sleep_need_training_feedback": sleep_need.get("trainingFeedback"),
            "recommended_bedtime_start_mins": sleep_need.get("recommendedBedtimeStartMins"),
            "recommended_bedtime_end_mins": sleep_need.get("recommendedBedtimeEndMins"),
            "restless_moments_count": sleep_data.get("restlessMomentsCount"),
            "avg_overnight_hrv": sleep_data.get("avgOvernightHrv"),
            "body_battery_change": sleep_data.get("bodyBatteryChange"),
            "avg_skin_temp_deviation_c": sleep_data.get("avgSkinTempDeviationC"),
            "avg_sleep_spo2": dto.get("averageSpO2Value"),
            "lowest_sleep_spo2": dto.get("lowestSpO2Value"),
            "avg_sleep_respiration": dto.get("averageRespirationValue"),
            "sleep_score_feedback": dto.get("sleepScoreFeedback"),
            "sleep_score_insight": dto.get("sleepScoreInsight"),
            "sleep_score_qualifier": (sleep_scores.get("overall") or {}).get("qualifierKey"),
        })

    # hrvSummary enthält neben dem reinen Zahlenwert auch Garmins eigene Status-Einordnung
    # ("BALANCED"/"UNBALANCED"/"LOW"/"NONE" bei Onboarding) + eine Baseline-Range - bisher nur
    # ungenutzt im raw_json-Blob (siehe "Leistung"-Seite/performance.py).
    avg_hrv = None
    hrv_status = None
    hrv_last_night_avg = None
    hrv_baseline_balanced_low = None
    hrv_baseline_balanced_upper = None
    if hrv_data and "hrvSummary" in hrv_data:
        hrv_summary = hrv_data["hrvSummary"] or {}
        avg_hrv = hrv_summary.get("weeklyAvg") or hrv_summary.get("lastNightAvg")
        hrv_status = hrv_summary.get("status")
        hrv_last_night_avg = hrv_summary.get("lastNightAvg")
        baseline = hrv_summary.get("baseline") or {}
        hrv_baseline_balanced_low = baseline.get("balancedLow")
        hrv_baseline_balanced_upper = baseline.get("balancedUpper")

    db_payload = {
        "date": target_date,
        "resting_hr": resting_hr,
        "avg_hrv": avg_hrv,
        "sleep_score": sleep_score,
        "sleep_hours": sleep_hours,
        "body_battery_max": stats.get("bodyBatteryChargedValue"),
        "body_battery_min": stats.get("bodyBatteryDrainedValue"),
        "stress_avg": stress_avg,
        "steps": steps,
        "hrv_status": hrv_status,
        "hrv_last_night_avg": hrv_last_night_avg,
        "hrv_baseline_balanced_low": hrv_baseline_balanced_low,
        "hrv_baseline_balanced_upper": hrv_baseline_balanced_upper,
        "raw_json": json.dumps({"stats": stats, "sleep": sleep_data, "hrv": hrv_data})
    }
    save_garmin_data(db_payload)

    # --- Erweiterte Metrik-Gruppen ---
    _fetch_advanced_health(client, target_date)
    _fetch_trends_and_wellness(client, target_date)
    _fetch_body_composition(client, target_date)
    _fetch_goals_and_performance(client, target_date)

    # Trainingszonen hängen an garmin_lactate_threshold/garmin_cycling_ftp, die beide nur für
    # "heute" befüllt werden (Account-weiter aktueller Stand) - daher hier genauso gated, statt
    # bei jedem Backfill-Tag denselben Snapshot redundant neu zu berechnen.
    if target_date == date.today().isoformat():
        recompute_zones(target_date)

    # daily_summary/weekly_summary laufen bewusst unconditional (auch für Backfill-Tage), anders
    # als recompute_zones oben - Schicht 1+2 der KI-Chat-Vorbereitung sollen für jeden importierten
    # Tag bzw. jede betroffene Woche vorliegen.
    compute_daily_summary(target_date)
    compute_weekly_summary(target_date)

    return db_payload


def _fetch_advanced_health(client, target_date):
    """Advanced Health Metrics: Training Readiness, Fitness-Alter, Max Metrics,
    Atmung, SpO2, Laktatschwelle, Trainingsstatus, Running Tolerance, Intensity Minutes."""

    readiness = _safe_call(client, "get_training_readiness", lambda c: c.get_training_readiness(target_date))
    readiness_entry = readiness[0] if isinstance(readiness, list) and readiness else readiness
    if readiness_entry:
        upsert_daily_metric("garmin_training_readiness", {
            "date": target_date,
            "score": readiness_entry.get("score"),
            "level": readiness_entry.get("level"),
            "feedback_long": readiness_entry.get("feedbackLong"),
            "feedback_short": readiness_entry.get("feedbackShort"),
            "sleep_score": readiness_entry.get("sleepScore"),
            "sleep_score_factor_percent": readiness_entry.get("sleepScoreFactorPercent"),
            "sleep_score_factor_feedback": readiness_entry.get("sleepScoreFactorFeedback"),
            "recovery_time": readiness_entry.get("recoveryTime"),
            "recovery_time_factor_percent": readiness_entry.get("recoveryTimeFactorPercent"),
            "recovery_time_factor_feedback": readiness_entry.get("recoveryTimeFactorFeedback"),
            "acwr_factor_percent": readiness_entry.get("acwrFactorPercent"),
            "acwr_factor_feedback": readiness_entry.get("acwrFactorFeedback"),
            "hrv_factor_percent": readiness_entry.get("hrvFactorPercent"),
            "hrv_factor_feedback": readiness_entry.get("hrvFactorFeedback"),
            "hrv_weekly_average": readiness_entry.get("hrvWeeklyAverage"),
            "sleep_history_factor_percent": readiness_entry.get("sleepHistoryFactorPercent"),
            "sleep_history_factor_feedback": readiness_entry.get("sleepHistoryFactorFeedback"),
            "stress_history_factor_percent": readiness_entry.get("stressHistoryFactorPercent"),
            "stress_history_factor_feedback": readiness_entry.get("stressHistoryFactorFeedback"),
        })

    fitness_age = _safe_call(client, "get_fitnessage_data", lambda c: c.get_fitnessage_data(target_date))
    if fitness_age:
        components = fitness_age.get("components") or {}
        upsert_daily_metric("garmin_fitness_age", {
            "date": target_date,
            "chronological_age": fitness_age.get("chronologicalAge"),
            "fitness_age": fitness_age.get("fitnessAge"),
            "achievable_fitness_age": fitness_age.get("achievableFitnessAge"),
            "previous_fitness_age": fitness_age.get("previousFitnessAge"),
            "rhr_value": (components.get("rhr") or {}).get("value"),
            "bmi_value": (components.get("bmi") or {}).get("value"),
            "vigorous_days_avg": (components.get("vigorousDaysAvg") or {}).get("value"),
            "vigorous_minutes_avg": (components.get("vigorousMinutesAvg") or {}).get("value"),
            "last_updated": fitness_age.get("lastUpdated"),
        })

    max_metrics = _safe_call(client, "get_max_metrics", lambda c: c.get_max_metrics(target_date))
    if max_metrics:
        entry = max_metrics[0] if isinstance(max_metrics, list) else max_metrics
        generic = (entry.get("generic") or {}) if isinstance(entry, dict) else {}
        cycling = (entry.get("cycling") or {}) if isinstance(entry, dict) else {}
        upsert_daily_metric("garmin_max_metrics", {
            "date": target_date,
            "vo2max_running": generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue"),
            "vo2max_cycling": cycling.get("vo2MaxPreciseValue") or cycling.get("vo2MaxValue"),
            "raw_json": json.dumps(max_metrics),
        })

    respiration = _safe_call(client, "get_respiration_data", lambda c: c.get_respiration_data(target_date))
    if respiration:
        upsert_daily_metric("garmin_respiration_summary", {
            "date": target_date,
            "lowest": respiration.get("lowestRespirationValue"),
            "highest": respiration.get("highestRespirationValue"),
            "avg_waking": respiration.get("avgWakingRespirationValue"),
            "avg_sleep": respiration.get("avgSleepRespirationValue"),
        })
        rows = [
            (target_date, ts, val)
            for ts, val in (respiration.get("respirationValuesArray") or [])
        ]
        replace_timeseries("garmin_respiration_timeseries", target_date, ["date", "timestamp", "respiration_value"], rows)

    spo2 = _safe_call(client, "get_spo2_data", lambda c: c.get_spo2_data(target_date))
    if spo2:
        upsert_daily_metric("garmin_spo2", {
            "date": target_date,
            "average_spo2": spo2.get("averageSpO2"),
            "lowest_spo2": spo2.get("lowestSpO2"),
            "last_7d_avg_spo2": spo2.get("lastSevenDaysAvgSpO2"),
            "latest_spo2": spo2.get("latestSpO2"),
            "avg_sleep_spo2": spo2.get("avgSleepSpO2"),
        })

    # get_lactate_threshold(latest=True) ignoriert das Datum komplett und liefert immer
    # Garmins aktuellen Stand - bei einem Backfill über mehrere Tage nur einmal für "heute"
    # abrufen, sonst wird derselbe Wert unter jedem Tag unnötig neu abgefragt und gespeichert.
    if target_date == date.today().isoformat():
        lactate = _safe_call(client, "get_lactate_threshold", lambda c: c.get_lactate_threshold(latest=True))
        if lactate:
            speed_hr = lactate.get("speed_and_heart_rate", {}) or {}
            power = lactate.get("power", {}) or {}
            # Garmin liefert "speed" um Faktor 10 zu klein (verifiziert: Rohwert 0.369 ergäbe eine
            # absurde Pace von ~45 min/km, *10 -> 3.69 m/s -> 4:31 min/km, plausibel für Schwellenpace).
            raw_speed = speed_hr.get("speed")
            corrected_speed = raw_speed * 10 if raw_speed is not None else None
            upsert_daily_metric("garmin_lactate_threshold", {
                "date": target_date,
                "speed": corrected_speed,
                "heart_rate": speed_hr.get("heartRate"),
                "heart_rate_cycling": speed_hr.get("heartRateCycling"),
                "functional_threshold_power": power.get("functionalThresholdPower"),
                "power_to_weight": power.get("powerToWeight"),
            })

    training_status = _safe_call(client, "get_training_status", lambda c: c.get_training_status(target_date))
    if training_status:
        # mostRecentVO2Max ist kein einfacher Zahlenwert, sondern ein verschachteltes Objekt mit
        # getrennten Werten für Laufen ("generic") und Radfahren ("cycling") - an Tagen ohne
        # aktuelle Messung ist es dagegen schlicht null. Beide Fälle abfangen statt den rohen
        # Wert (der dann mal dict, mal None ist) direkt in die REAL-Spalte zu schreiben.
        vo2max_data = training_status.get("mostRecentVO2Max") or {}
        vo2max_generic = vo2max_data.get("generic") or {}
        vo2max_cycling = vo2max_data.get("cycling") or {}

        load_balance = training_status.get("mostRecentTrainingLoadBalance")
        training_status_entry = training_status.get("mostRecentTrainingStatus")
        device_entry = _primary_device_entry(
            (training_status_entry or {}).get("latestTrainingStatusData")
        )
        acute_load_dto = (device_entry or {}).get("acuteTrainingLoadDTO") or {}
        load_focus = _parse_load_focus_pct(load_balance)

        upsert_daily_metric("garmin_training_status", {
            "date": target_date,
            "most_recent_vo2max": vo2max_generic.get("vo2MaxPreciseValue") or vo2max_generic.get("vo2MaxValue"),
            "most_recent_vo2max_cycling": vo2max_cycling.get("vo2MaxPreciseValue") or vo2max_cycling.get("vo2MaxValue"),
            "training_load_balance": json.dumps(load_balance) if load_balance else None,
            "training_status": json.dumps(training_status_entry) if training_status_entry else None,
            # Trainingszustand als Klartext-Label + akute Belastung/Optimalbereich/ACWR-Status -
            # aus demselben, bereits abgerufenen Response geparst (kein zusätzlicher API-Call).
            # Für dieses Konto bisher durchgängig "NO_STATUS_1" beobachtet (Gerät liefert noch
            # keinen echten Trainingszustand) - das ist ein Garmin-seitiger Datenstand, kein Bug.
            "training_status_label": device_entry.get("trainingStatusFeedbackPhrase") if device_entry else None,
            "training_status_code": device_entry.get("trainingStatus") if device_entry else None,
            "acute_training_load": acute_load_dto.get("dailyTrainingLoadAcute"),
            "chronic_training_load": acute_load_dto.get("dailyTrainingLoadChronic"),
            "chronic_load_min": acute_load_dto.get("minTrainingLoadChronic"),
            "chronic_load_max": acute_load_dto.get("maxTrainingLoadChronic"),
            "acwr_status": acute_load_dto.get("acwrStatus"),
            "acwr_ratio": acute_load_dto.get("dailyAcuteChronicWorkloadRatio"),
            "load_focus_anaerobic_pct": load_focus[0],
            "load_focus_high_aerobic_pct": load_focus[1],
            "load_focus_low_aerobic_pct": load_focus[2],
            "raw_json": json.dumps(training_status),
        })

    running_tolerance = _safe_call(
        client, "get_running_tolerance",
        lambda c: c.get_running_tolerance(target_date, target_date)
    )
    tolerance_entry = running_tolerance[0] if isinstance(running_tolerance, list) and running_tolerance else running_tolerance
    if tolerance_entry:
        upsert_daily_metric("garmin_running_tolerance", {
            "date": target_date,
            "total_impact_load": tolerance_entry.get("totalImpactLoad"),
            "total_distance": tolerance_entry.get("totalDistance"),
            "tolerance": tolerance_entry.get("tolerance"),
            "week_index": tolerance_entry.get("weekIndex"),
        })

    intensity = _safe_call(client, "get_intensity_minutes_data", lambda c: c.get_intensity_minutes_data(target_date))
    if intensity:
        upsert_daily_metric("garmin_intensity_minutes", {
            "date": target_date,
            "weekly_moderate": intensity.get("weeklyModerate"),
            "weekly_vigorous": intensity.get("weeklyVigorous"),
            "weekly_total": intensity.get("weeklyTotal"),
            "week_goal": intensity.get("weekGoal"),
            "moderate_minutes": intensity.get("moderateMinutes"),
            "vigorous_minutes": intensity.get("vigorousMinutes"),
        })


def _fetch_trends_and_wellness(client, target_date):
    """Historical Data & Trends + Hydration & Wellness: Stress/Body-Battery-Zeitreihen,
    Body-Battery-Events, Etagen, Blutdruck, Herzfrequenz-Zeitreihe, Schritte, Atemminuten,
    Hydration, Lifestyle-Logging, Ernährung, All-Day-Events."""

    # get_stress_data und get_all_day_stress liefern identischen Content (verifiziert per diff) -
    # nur einmal abrufen, deckt Stress- UND Body-Battery-Zeitreihe ab.
    all_day_stress = _safe_call(client, "get_all_day_stress", lambda c: c.get_all_day_stress(target_date))
    if all_day_stress:
        stress_rows = [
            (target_date, ts, level)
            for ts, level in (all_day_stress.get("stressValuesArray") or [])
        ]
        replace_timeseries("garmin_stress_timeseries", target_date, ["date", "timestamp", "stress_level"], stress_rows)

        bb_rows = [
            (target_date, entry[0], entry[1], entry[2])
            for entry in (all_day_stress.get("bodyBatteryValuesArray") or [])
        ]
        replace_timeseries(
            "garmin_body_battery_timeseries", target_date,
            ["date", "timestamp", "status", "level"], bb_rows
        )

    bb_events = _safe_call(client, "get_body_battery_events", lambda c: c.get_body_battery_events(target_date))
    if bb_events:
        rows = []
        for item in bb_events:
            event = item.get("event", {}) or {}
            rows.append((
                target_date,
                event.get("eventType"),
                event.get("eventStartTimeGmt"),
                event.get("durationInMilliseconds"),
                event.get("bodyBatteryImpact"),
                item.get("activityName"),
                item.get("activityType"),
                item.get("averageStress"),
            ))
        replace_timeseries(
            "garmin_body_battery_events", target_date,
            ["date", "event_type", "start_time_gmt", "duration_ms", "body_battery_impact",
             "activity_name", "activity_type", "average_stress"],
            rows
        )

    floors = _safe_call(client, "get_floors", lambda c: c.get_floors(target_date))
    if floors:
        rows = [
            (target_date, start, end, up, down)
            for start, end, up, down in (floors.get("floorValuesArray") or [])
        ]
        replace_timeseries(
            "garmin_floors_timeseries", target_date,
            ["date", "start_time_gmt", "end_time_gmt", "floors_ascended", "floors_descended"],
            rows
        )

    heart_rates = _safe_call(client, "get_heart_rates", lambda c: c.get_heart_rates(target_date))
    if heart_rates:
        upsert_daily_metric("garmin_heart_rate_summary", {
            "date": target_date,
            "max_hr": heart_rates.get("maxHeartRate"),
            "min_hr": heart_rates.get("minHeartRate"),
            "resting_hr": heart_rates.get("restingHeartRate"),
            "last_7d_avg_resting_hr": heart_rates.get("lastSevenDaysAvgRestingHeartRate"),
        })
        rows = [
            (target_date, ts, hr)
            for ts, hr in (heart_rates.get("heartRateValues") or [])
        ]
        replace_timeseries("garmin_heart_rate_timeseries", target_date, ["date", "timestamp", "heart_rate"], rows)

    steps = _safe_call(client, "get_steps_data", lambda c: c.get_steps_data(target_date))
    if steps:
        rows = [
            (target_date, s.get("startGMT"), s.get("endGMT"), s.get("steps"),
             s.get("pushes"), s.get("primaryActivityLevel"))
            for s in steps
        ]
        replace_timeseries(
            "garmin_steps_timeseries", target_date,
            ["date", "start_gmt", "end_gmt", "steps", "pushes", "primary_activity_level"],
            rows
        )

    blood_pressure = _safe_call(
        client, "get_blood_pressure",
        lambda c: c.get_blood_pressure(target_date, target_date)
    )
    if blood_pressure:
        summaries = blood_pressure.get("measurementSummaries") or []
        latest = summaries[-1] if summaries else {}
        upsert_daily_metric("garmin_blood_pressure", {
            "date": target_date,
            "systolic": latest.get("systolic"),
            "diastolic": latest.get("diastolic"),
            "pulse": latest.get("pulse"),
            "category": latest.get("category"),
            "raw_json": json.dumps(blood_pressure),
        })

    lifestyle = _safe_call(client, "get_lifestyle_logging_data", lambda c: c.get_lifestyle_logging_data(target_date))
    if lifestyle:
        stats_for_date = next(
            (s for s in (lifestyle.get("completionStats") or []) if s.get("calendarDate") == target_date),
            None
        )
        if stats_for_date:
            upsert_daily_metric("garmin_lifestyle_logging", {
                "date": target_date,
                "total_tracking": stats_for_date.get("totalTracking"),
                "completed_tracking": stats_for_date.get("completedTracking"),
            })

    hydration = _safe_call(client, "get_hydration_data", lambda c: c.get_hydration_data(target_date))
    if hydration:
        upsert_daily_metric("garmin_hydration", {
            "date": target_date,
            "value_ml": hydration.get("valueInML"),
            "goal_ml": hydration.get("goalInML"),
            "daily_average_ml": hydration.get("dailyAverageinML"),
            "sweat_loss_ml": hydration.get("sweatLossInML"),
            "activity_intake_ml": hydration.get("activityIntakeInML"),
        })

    all_day_events = _safe_call(client, "get_all_day_events", lambda c: c.get_all_day_events(target_date))
    if all_day_events:
        rows = [
            (target_date, e.get("activityType"), e.get("activitySubType"),
             e.get("startTimestampGMT"), e.get("endTimestampGMT"), e.get("duration"))
            for e in all_day_events
        ]
        replace_timeseries(
            "garmin_all_day_events", target_date,
            ["date", "activity_type", "activity_sub_type", "start_time_gmt", "end_time_gmt", "duration"],
            rows
        )

    food_log = _safe_call(client, "get_nutrition_daily_food_log", lambda c: c.get_nutrition_daily_food_log(target_date))
    if food_log:
        goals = food_log.get("dailyNutritionGoals", {}) or {}
        upsert_daily_metric("garmin_nutrition_daily", {
            "date": target_date,
            "calories_goal": goals.get("calories"),
            "calories_adjusted": goals.get("adjustedCalories"),
            "raw_json": json.dumps(food_log),
        })

    pregnancy = _safe_call(client, "get_pregnancy_summary", lambda c: c.get_pregnancy_summary())
    if pregnancy:
        upsert_daily_metric("garmin_pregnancy_summary", {
            "date": target_date,
            "raw_json": json.dumps(pregnancy),
        })


def _fetch_body_composition(client, target_date):
    """Body Composition & Weight + Goals & Achievements (Renn-Prognosen).
    get_body_composition liefert nur ein selbst-herleitbares Aggregat über get_weigh_ins hinaus
    (totalAverage) und wird daher nicht separat gespeichert - siehe Projektnotiz zu Redundanzen."""

    weigh_ins = _safe_call(
        client, "get_weigh_ins",
        lambda c: c.get_weigh_ins(target_date, target_date)
    )
    if weigh_ins:
        for summary in weigh_ins.get("dailyWeightSummaries") or []:
            for entry in summary.get("allWeightMetrics") or []:
                sample_pk = entry.get("samplePk")
                if sample_pk is None:
                    continue
                upsert_weigh_in({
                    "sample_pk": sample_pk,
                    "date": entry.get("calendarDate") or target_date,
                    "weight": entry.get("weight"),
                    "bmi": entry.get("bmi"),
                    "body_fat": entry.get("bodyFat"),
                    "body_water": entry.get("bodyWater"),
                    "bone_mass": entry.get("boneMass"),
                    "muscle_mass": entry.get("muscleMass"),
                    "physique_rating": entry.get("physiqueRating"),
                    "visceral_fat": entry.get("visceralFat"),
                    "metabolic_age": entry.get("metabolicAge"),
                    "source_type": entry.get("sourceType"),
                    "timestamp_gmt": entry.get("timestampGMT"),
                })

    # get_race_predictions() kennt kein Datum - liefert immer Garmins aktuelle Prognose.
    # Nur für "heute" abrufen (siehe gleiche Begründung bei get_lactate_threshold oben);
    # Garmin bietet ohnehin keine historische Abfrage dafür an.
    if target_date == date.today().isoformat():
        race_predictions = _safe_call(client, "get_race_predictions", lambda c: c.get_race_predictions())
        if race_predictions:
            upsert_daily_metric("garmin_race_predictions", {
                "date": target_date,
                "time_5k": race_predictions.get("time5K"),
                "time_10k": race_predictions.get("time10K"),
                "time_half_marathon": race_predictions.get("timeHalfMarathon"),
                "time_marathon": race_predictions.get("timeMarathon"),
            })


def _add_months(year, month, offset):
    total = (year * 12 + (month - 1)) + offset
    return total // 12, total % 12 + 1


def _fetch_goals_and_performance(client, target_date):
    """Goals & Achievements (erweitert): Endurance/Hill Score, Cycling FTP, Personal Records,
    Goals, Trainingspläne, geplante Events/Rennen (Kalender)."""

    endurance = _safe_call(client, "get_endurance_score", lambda c: c.get_endurance_score(target_date, target_date))
    if endurance:
        dto = endurance.get("enduranceScoreDTO") or {}
        entry_date = dto.get("calendarDate") or target_date
        upsert_daily_metric("garmin_endurance_score", {
            "date": entry_date,
            "overall_score": dto.get("overallScore"),
            "classification": dto.get("classification"),
            "feedback_phrase": dto.get("feedbackPhrase"),
            "gauge_lower_limit": dto.get("gaugeLowerLimit"),
            "gauge_upper_limit": dto.get("gaugeUpperLimit"),
            "classification_intermediate": dto.get("classificationLowerLimitIntermediate"),
            "classification_trained": dto.get("classificationLowerLimitTrained"),
            "classification_well_trained": dto.get("classificationLowerLimitWellTrained"),
            "classification_expert": dto.get("classificationLowerLimitExpert"),
            "classification_superior": dto.get("classificationLowerLimitSuperior"),
            "classification_elite": dto.get("classificationLowerLimitElite"),
        })

    hill = _safe_call(client, "get_hill_score", lambda c: c.get_hill_score(target_date, target_date))
    if hill:
        hill_entry = next(
            (h for h in (hill.get("hillScoreDTOList") or []) if h.get("calendarDate") == target_date),
            None
        )
        if hill_entry:
            upsert_daily_metric("garmin_hill_score", {
                "date": target_date,
                "strength_score": hill_entry.get("strengthScore"),
                "endurance_score": hill_entry.get("enduranceScore"),
                "overall_score": hill_entry.get("overallScore"),
                "classification_id": hill_entry.get("hillScoreClassificationId"),
                "feedback_phrase_id": hill_entry.get("hillScoreFeedbackPhraseId"),
                "vo2_max": hill_entry.get("vo2MaxPreciseValue") or hill_entry.get("vo2Max"),
            })

    # Die folgenden Endpunkte kennen kein Datum bzw. liefern immer den aktuellen Gesamtstand
    # (Account-weite Bestzeiten, Ziele, Pläne, FTP) - wie bei get_race_predictions nur für
    # "heute" abrufen, sonst wird derselbe Stand bei jedem Backfill-Tag unnötig neu geholt.
    if target_date != date.today().isoformat():
        return

    ftp = _safe_call(client, "get_cycling_ftp", lambda c: c.get_cycling_ftp())
    if ftp:
        # Garmins get_cycling_ftp() liefert kein W/kg mit (anders als der Lauf-Leistungswert in
        # garmin_lactate_threshold, der ein eigenes powerToWeight-Feld hat) - hier selbst aus dem
        # aktuellsten bekannten Körpergewicht berechnen, statt es dem Nutzer vorzuenthalten.
        ftp_watts = ftp.get("functionalThresholdPower")
        power_to_weight = None
        if ftp_watts is not None:
            conn = get_connection()
            weight_row = conn.execute(
                "SELECT weight FROM garmin_weigh_ins WHERE weight IS NOT NULL ORDER BY date DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if weight_row and weight_row["weight"]:
                weight_kg = weight_row["weight"] / 1000.0
                power_to_weight = ftp_watts / weight_kg

        upsert_daily_metric("garmin_cycling_ftp", {
            "date": target_date,
            "functional_threshold_power": ftp_watts,
            "measured_date": ftp.get("calendarDate"),
            "is_stale": int(ftp.get("isStale")) if ftp.get("isStale") is not None else None,
            "power_to_weight": power_to_weight,
        })

    personal_records = _safe_call(client, "get_personal_record", lambda c: c.get_personal_record())
    if personal_records:
        for pr in personal_records:
            pr_id = pr.get("id")
            if pr_id is None:
                continue
            upsert_by_key("garmin_personal_records", "id", {
                "id": pr_id,
                "type_id": pr.get("typeId"),
                "activity_id": pr.get("activityId"),
                "activity_name": pr.get("activityName"),
                "activity_type": pr.get("activityType"),
                "value": pr.get("value"),
                "activity_start_date": pr.get("actStartDateTimeInGMTFormatted"),
                "pr_date": pr.get("prStartTimeGmtFormatted"),
            })

    for status in ("active", "future"):
        goals = _safe_call(client, f"get_goals[{status}]", lambda c, s=status: c.get_goals(status=s))
        if goals:
            for goal in goals:
                goal_id = goal.get("goalId") or goal.get("id")
                if goal_id is None:
                    continue
                upsert_by_key("garmin_goals", "id", {
                    "id": goal_id,
                    "status": status,
                    "raw_json": json.dumps(goal),
                })

    training_plans = _safe_call(client, "get_training_plans", lambda c: c.get_training_plans())
    if training_plans:
        for plan in training_plans.get("trainingPlanList") or []:
            plan_id = plan.get("trainingPlanId") or plan.get("id")
            if plan_id is None:
                continue
            upsert_by_key("garmin_training_plans", "id", {
                "id": plan_id,
                "raw_json": json.dumps(plan),
            })

    # Geplante Events/Rennen: aktueller Monat + die zwei folgenden - reicht, um bevorstehende
    # Rennen (z.B. den Marathon) zuverlässig zu sehen, ohne jeden Monat der Zukunft abzufragen.
    today = date.today()
    for offset in range(0, 3):
        year, month = _add_months(today.year, today.month, offset)
        period = f"{year:04d}-{month:02d}"
        scheduled = _safe_call(
            client, f"get_scheduled_workouts[{period}]",
            lambda c, y=year, m=month: c.get_scheduled_workouts(y, m)
        )
        if scheduled is None:
            continue
        rows = []
        for item in scheduled.get("calendarItems") or []:
            completion_target = item.get("completionTarget") or {}
            distance_meters = completion_target.get("value") if completion_target.get("unit") == "meter" else None
            rows.append((
                period,
                item.get("date"),
                item.get("itemType"),
                item.get("activityTypeId"),
                item.get("title"),
                int(bool(item.get("isRace"))),
                distance_meters,
                item.get("location"),
                item.get("url"),
                item.get("shareableEventUuid"),
                item.get("workoutId"),
                item.get("trainingPlanId"),
            ))
        replace_timeseries(
            "garmin_scheduled_events", period,
            ["date", "event_date", "item_type", "activity_type_id", "title", "is_race",
             "distance_meters", "location", "url", "shareable_event_uuid", "workout_id", "training_plan_id"],
            rows
        )


if __name__ == "__main__":
    print("Teste Garmin-Import für heute...")
    res = fetch_and_store_garmin_data()
    print("Erfolgreich importiert:", res)
