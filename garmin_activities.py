"""
Aktivitäten-Sync (Läufe, Rad, Schwimmen etc.) - bewusst getrennt von garmin_service.py. Ein
großer, seltener Ein-/Nachholbedarf (volle Historie, hunderte Aktivitäten mit je hunderten
Detail-Zeilen) bleibt manuell über die Settings-Seite angestoßen (siehe
pages/3_⚙️_Settings.py bzw. DataSyncSettings.tsx). Das laufende Tagesgeschäft (die 1-2 neuen
Aktivitäten seit gestern) läuft dagegen automatisch mit kleinen Limits als Teil des täglichen
Auto-Syncs mit (siehe auto_sync.py::_sync_activities_once).
"""
import json
import time
import random
from garminconnect import GarminConnectTooManyRequestsError
from db import get_connection, upsert_by_key
from activity_analytics import compute_activity_analytics

# Cadence heißt je nach Sportart unterschiedlich - erster Treffer gewinnt.
CADENCE_FIELDS = {
    "averageRunningCadenceInStepsPerMinute": "Schritte/Min",
    "averageBikingCadenceInRevPerMinute": "U/Min",
    "averageSwimCadenceInStrokesPerMinute": "Züge/Min",
}

# Gleiches Problem in der Detail-Zeitreihe (metricDescriptors) - Kandidaten der Reihe nach probieren.
DETAIL_CADENCE_KEYS = ["directRunCadence", "directBikeCadence", "directSwimCadence", "directDoubleCadence"]


def _pause():
    time.sleep(random.uniform(2, 4))


def _safe_call(label, func):
    try:
        result = func()
        _pause()
        return result
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:
        if "429" in str(e):
            raise
        print(f"⚠️  {label} übersprungen: {e}")
        return None


def _extract_summary(activity):
    cadence, cadence_unit = None, None
    for field, unit in CADENCE_FIELDS.items():
        if activity.get(field) is not None:
            cadence, cadence_unit = activity[field], unit
            break

    return {
        "activity_id": activity["activityId"],
        "activity_name": activity.get("activityName"),
        "activity_type": (activity.get("activityType") or {}).get("typeKey"),
        "start_time_local": activity.get("startTimeLocal"),
        "start_time_gmt": activity.get("startTimeGMT"),
        "distance_meters": activity.get("distance"),
        "duration_seconds": activity.get("duration"),
        "elevation_gain": activity.get("elevationGain"),
        "elevation_loss": activity.get("elevationLoss"),
        "average_speed": activity.get("averageSpeed"),
        "max_speed": activity.get("maxSpeed"),
        "calories": activity.get("calories"),
        "average_hr": activity.get("averageHR"),
        "max_hr": activity.get("maxHR"),
        "hr_zone_1": activity.get("hrTimeInZone_1"),
        "hr_zone_2": activity.get("hrTimeInZone_2"),
        "hr_zone_3": activity.get("hrTimeInZone_3"),
        "hr_zone_4": activity.get("hrTimeInZone_4"),
        "hr_zone_5": activity.get("hrTimeInZone_5"),
        "avg_power": activity.get("avgPower"),
        "max_power": activity.get("maxPower"),
        "norm_power": activity.get("normPower"),
        "power_zone_1": activity.get("powerTimeInZone_1"),
        "power_zone_2": activity.get("powerTimeInZone_2"),
        "power_zone_3": activity.get("powerTimeInZone_3"),
        "power_zone_4": activity.get("powerTimeInZone_4"),
        "power_zone_5": activity.get("powerTimeInZone_5"),
        "cadence": cadence,
        "cadence_unit": cadence_unit,
        "aerobic_training_effect": activity.get("aerobicTrainingEffect"),
        "anaerobic_training_effect": activity.get("anaerobicTrainingEffect"),
        "training_effect_label": activity.get("trainingEffectLabel"),
        "vo2max_value": activity.get("vO2MaxValue"),
        "start_latitude": activity.get("startLatitude"),
        "start_longitude": activity.get("startLongitude"),
        "end_latitude": activity.get("endLatitude"),
        "end_longitude": activity.get("endLongitude"),
        "location_name": activity.get("locationName"),
        "device_id": activity.get("deviceId"),
        "is_pr": int(bool(activity.get("pr"))),
        "activity_training_load": activity.get("activityTrainingLoad"),
        "raw_json": json.dumps(activity),
    }


def sync_activity_list(client, limit=20, start=0, on_progress=None):
    """Holt eine Seite der Aktivitätsliste (neueste zuerst) und speichert die Zusammenfassungen.
    has_details_synced bleibt bei bereits vorhandenen Aktivitäten unangetastet (Upsert deckt nur
    die Summary-Felder ab). Gibt die Anzahl der verarbeiteten Aktivitäten zurück."""
    activities = _safe_call("get_activities", lambda: client.get_activities(start=start, limit=limit))
    if not activities:
        return 0

    for i, activity in enumerate(activities, start=1):
        upsert_by_key("garmin_activities", "activity_id", _extract_summary(activity))
        if on_progress:
            on_progress(i, len(activities), activity.get("activityName") or "")

    return len(activities)


def _metric(point, key_to_index, key):
    idx = key_to_index.get(key)
    if idx is None:
        return None
    return point["metrics"][idx]


def _detail_cadence_key(key_to_index):
    for key in DETAIL_CADENCE_KEYS:
        if key in key_to_index:
            return key
    return None


def sync_activity_details(client, max_count=10, on_progress=None):
    """Lädt für bis zu max_count Aktivitäten ohne synchronisierte Detaildaten (neueste zuerst)
    die volle Sekunden-/GPS-Zeitreihe nach. Bricht bei 429 sofort ab wie die übrigen Sync-Pfade.
    Gibt (anzahl_synchronisiert, anzahl_fehler) zurück."""
    conn = get_connection()
    pending = conn.execute(
        "SELECT activity_id, activity_name FROM garmin_activities "
        "WHERE has_details_synced = 0 ORDER BY start_time_local DESC LIMIT ?",
        (max_count,)
    ).fetchall()
    conn.close()

    synced, errors = 0, 0
    for i, row in enumerate(pending, start=1):
        activity_id, activity_name = row["activity_id"], row["activity_name"]
        details = _safe_call(
            f"get_activity_details({activity_id})",
            lambda aid=activity_id: client.get_activity_details(aid)
        )
        if details is None:
            errors += 1
            if on_progress:
                on_progress(i, len(pending), activity_name, "error")
            continue

        descriptors = details.get("metricDescriptors") or []
        key_to_index = {d["key"]: d["metricsIndex"] for d in descriptors}
        cadence_key = _detail_cadence_key(key_to_index)
        points = details.get("activityDetailMetrics") or []

        rows = []
        for seq, point in enumerate(points):
            rows.append((
                activity_id, seq,
                _metric(point, key_to_index, "directTimestamp"),
                _metric(point, key_to_index, "directLatitude"),
                _metric(point, key_to_index, "directLongitude"),
                _metric(point, key_to_index, "directElevation"),
                _metric(point, key_to_index, "directHeartRate"),
                _metric(point, key_to_index, "directPower"),
                _metric(point, key_to_index, "directSpeed"),
                _metric(point, key_to_index, cadence_key) if cadence_key else None,
                _metric(point, key_to_index, "sumDistance"),
                _metric(point, key_to_index, "directRespirationRate"),
                _metric(point, key_to_index, "directBodyBattery"),
                _metric(point, key_to_index, "directAvailableStamina"),
                _metric(point, key_to_index, "directVerticalOscillation"),
                _metric(point, key_to_index, "directGroundContactTime"),
                _metric(point, key_to_index, "directAirTemperature"),
            ))

        conn = get_connection()
        conn.execute("DELETE FROM garmin_activity_details WHERE activity_id = ?", (activity_id,))
        if rows:
            conn.executemany("""
                INSERT INTO garmin_activity_details (
                    activity_id, seq, timestamp, latitude, longitude, elevation, heart_rate,
                    power, speed, cadence, distance, respiration_rate, body_battery, stamina,
                    vertical_oscillation, ground_contact_time, temperature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        conn.execute(
            "UPDATE garmin_activities SET has_details_synced = 1 WHERE activity_id = ?",
            (activity_id,)
        )
        conn.commit()
        conn.close()

        # Schicht 1 der KI-Chat-Vorbereitung: erst jetzt sinnvoll möglich, da die meisten Felder
        # (Decoupling, HF-Drift, GAP, Temperatur) die gerade geladene Sekunden-Zeitreihe brauchen.
        compute_activity_analytics(activity_id)

        synced += 1
        if on_progress:
            on_progress(i, len(pending), activity_name, "ok")

    return synced, errors
