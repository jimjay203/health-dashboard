"""
Schicht 1 der KI-Chat-Vorbereitung: regelbasierte Pro-Aktivität-Kennzahlen (Decoupling, HF-Drift,
Grade Adjusted Pace, Brick-Erkennung, Ausreißer) - kein LLM-Call. Wird direkt nach dem Laden der
Sekunden-Zeitreihe einer Aktivität berechnet, siehe garmin_activities.sync_activity_details().
"""
from datetime import datetime, timedelta
from statistics import mean, median, pstdev
from db import get_connection, upsert_by_key

# --- Tunable Konstanten (analog zu training_zones.py) ---
MIN_DURATION_FOR_DECOUPLING = 1200  # Sekunden (20 Min) - darunter ist Decoupling/HF-Drift zu verrauscht
RUNNING_ACTIVITY_TYPES = {"running", "trail_running", "treadmill_running", "street_running", "track_running"}
CYCLING_ACTIVITY_TYPES = {"cycling", "road_biking", "indoor_cycling", "mountain_biking", "gravel_cycling"}
DECOUPLING_ACTIVITY_TYPES = RUNNING_ACTIVITY_TYPES | CYCLING_ACTIVITY_TYPES

HEAT_THRESHOLD_C = 22.0
HEAT_EFFECT_PCT = 10.0              # so viel schlechter als die eigene Baseline, um heat_effect_flag zu setzen
MIN_ELEVATION_FOR_GAP = 50.0        # Höhenmeter, ab denen Grade Adjusted Pace berechnet wird
BRICK_GAP_MINUTES = 30
BASELINE_ACTIVITY_COUNT = 10        # wie viele eigene Vergleichsaktivitäten für Baseline-Checks
OUTLIER_STDEV_THRESHOLD = 2.0


def _avg(values):
    filtered = [v for v in values if v is not None]
    return mean(filtered) if filtered else None


def _half_split_index(details):
    """Index, an dem die Aktivität nach verstrichener Zeit (nicht nach Punktanzahl) in zwei
    Hälften geteilt wird - fällt auf die Punktanzahl zurück, falls keine Timestamps vorliegen."""
    timestamps = [d["timestamp"] for d in details if d["timestamp"] is not None]
    if len(timestamps) < 2:
        return len(details) // 2
    t_mid = (timestamps[0] + timestamps[-1]) / 2
    for i, d in enumerate(details):
        if d["timestamp"] is not None and d["timestamp"] >= t_mid:
            return i
    return len(details) // 2


def _pace_hr_split_metrics(details):
    """(decoupling_pct, hr_drift_pct, negative_split_bool) aus dem Vergleich der Effizienz
    (Geschwindigkeit/HF) zwischen erster und zweiter Hälfte - Standard-Decoupling-Formel."""
    idx = _half_split_index(details)
    first, second = details[:idx], details[idx:]
    if not first or not second:
        return None, None, None

    hr1, hr2 = _avg([d["heart_rate"] for d in first]), _avg([d["heart_rate"] for d in second])
    speed1, speed2 = _avg([d["speed"] for d in first]), _avg([d["speed"] for d in second])
    if hr1 is None or hr2 is None or speed1 is None or speed2 is None or hr1 == 0 or hr2 == 0:
        return None, None, None

    efficiency1, efficiency2 = speed1 / hr1, speed2 / hr2
    decoupling_pct = (efficiency2 - efficiency1) / efficiency1 * 100.0
    hr_drift_pct = (hr2 - hr1) / hr1 * 100.0
    negative_split_bool = int(speed2 > speed1)
    return decoupling_pct, hr_drift_pct, negative_split_bool


def _minetti_cost_ratio(grade):
    """Metabolisches Kostenverhältnis C(i)/C(0) nach Minetti et al. 2002 - eine verbreitete GAP-
    Näherung (ähnlich von Strava & Co. genutzt), keine einzige "offizielle" GAP-Formel existiert."""
    i = max(-0.45, min(0.45, grade))  # außerhalb validierter Bereich, hart begrenzen
    cost = 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + 3.6
    return cost / 3.6


def _gap_avg_pace_sec_per_km(details):
    adjusted_speeds = []
    for prev, curr in zip(details, details[1:]):
        if None in (prev["elevation"], curr["elevation"], prev["distance"], curr["distance"], curr["speed"]):
            continue
        dist_delta = curr["distance"] - prev["distance"]
        if dist_delta <= 0:
            continue
        grade = (curr["elevation"] - prev["elevation"]) / dist_delta
        adjusted_speeds.append(curr["speed"] * _minetti_cost_ratio(grade))
    avg_adjusted_speed = _avg(adjusted_speeds)
    if not avg_adjusted_speed or avg_adjusted_speed <= 0:
        return None
    return 1000.0 / avg_adjusted_speed


def _find_linked_brick_activity(cursor, activity_row):
    """Andere Aktivität anderer Sportart, deren Ende < BRICK_GAP_MINUTES vor dem Start dieser
    Aktivität liegt (z.B. Rad direkt gefolgt von Lauf = Brick-Workout)."""
    if not activity_row["start_time_local"]:
        return None
    start_dt = datetime.fromisoformat(activity_row["start_time_local"])
    candidates = cursor.execute(
        "SELECT activity_id, activity_type, start_time_local, duration_seconds FROM garmin_activities "
        "WHERE activity_id != ? AND start_time_local <= ? ORDER BY start_time_local DESC LIMIT 5",
        (activity_row["activity_id"], activity_row["start_time_local"])
    ).fetchall()
    for c in candidates:
        if c["activity_type"] == activity_row["activity_type"] or not c["duration_seconds"] or not c["start_time_local"]:
            continue
        c_end = datetime.fromisoformat(c["start_time_local"]) + timedelta(seconds=c["duration_seconds"])
        gap_minutes = (start_dt - c_end).total_seconds() / 60.0
        if 0 <= gap_minutes <= BRICK_GAP_MINUTES:
            return c["activity_id"]
    return None


def _bike_to_run_pace_drop_pct(cursor, activity_row, linked_activity_id):
    """Nur gesetzt, wenn diese Aktivität ein Lauf direkt nach einer Rad-Einheit war - vergleicht
    die Pace bei ähnlicher HF gegen den Median der eigenen nicht-Brick-Läufe."""
    if linked_activity_id is None or activity_row["activity_type"] not in RUNNING_ACTIVITY_TYPES:
        return None
    if activity_row["average_speed"] is None or not activity_row["average_hr"]:
        return None
    linked = cursor.execute(
        "SELECT activity_type FROM garmin_activities WHERE activity_id = ?", (linked_activity_id,)
    ).fetchone()
    if not linked or linked["activity_type"] not in CYCLING_ACTIVITY_TYPES:
        return None

    hr = activity_row["average_hr"]
    baseline_rows = cursor.execute(
        "SELECT ga.average_speed FROM garmin_activities ga "
        "LEFT JOIN activity_analytics aa ON aa.activity_id = ga.activity_id "
        "WHERE ga.activity_type = ? AND ga.activity_id != ? "
        "AND ga.average_hr BETWEEN ? AND ? AND aa.linked_brick_activity_id IS NULL "
        "ORDER BY ga.start_time_local DESC LIMIT ?",
        (activity_row["activity_type"], activity_row["activity_id"], hr - 5, hr + 5, BASELINE_ACTIVITY_COUNT)
    ).fetchall()
    speeds = [r["average_speed"] for r in baseline_rows if r["average_speed"]]
    if not speeds:
        return None
    baseline_speed = median(speeds)
    if not baseline_speed:
        return None
    return (baseline_speed - activity_row["average_speed"]) / baseline_speed * 100.0


def _outlier_flag(cursor, activity_row):
    """HF oder Pace mehr als OUTLIER_STDEV_THRESHOLD Standardabweichungen von der eigenen
    Baseline (letzte BASELINE_ACTIVITY_COUNT Aktivitäten derselben Sportart) entfernt."""
    if activity_row["average_hr"] is None or activity_row["average_speed"] is None:
        return 0
    baseline_rows = cursor.execute(
        "SELECT average_hr, average_speed FROM garmin_activities "
        "WHERE activity_type = ? AND activity_id != ? ORDER BY start_time_local DESC LIMIT ?",
        (activity_row["activity_type"], activity_row["activity_id"], BASELINE_ACTIVITY_COUNT)
    ).fetchall()
    hrs = [r["average_hr"] for r in baseline_rows if r["average_hr"] is not None]
    speeds = [r["average_speed"] for r in baseline_rows if r["average_speed"] is not None]
    if len(hrs) < 3 or len(speeds) < 3:
        return 0
    hr_spread = pstdev(hrs) or None
    speed_spread = pstdev(speeds) or None
    hr_outlier = hr_spread and abs(activity_row["average_hr"] - mean(hrs)) > OUTLIER_STDEV_THRESHOLD * hr_spread
    speed_outlier = speed_spread and abs(activity_row["average_speed"] - mean(speeds)) > OUTLIER_STDEV_THRESHOLD * speed_spread
    return int(bool(hr_outlier or speed_outlier))


def _heat_effect_flag(cursor, activity_row, avg_temperature):
    """Vergleich zur eigenen Baseline (nicht nur Rohtemperatur): Pace:HF-Effizienz bei >22°C
    gegen den Median der eigenen kühleren (<=22°C) Aktivitäten derselben Sportart."""
    if avg_temperature is None or avg_temperature <= HEAT_THRESHOLD_C:
        return 0
    if not activity_row["average_hr"] or activity_row["average_speed"] is None:
        return 0
    this_efficiency = activity_row["average_speed"] / activity_row["average_hr"]

    baseline_rows = cursor.execute(
        "SELECT ga.average_speed, ga.average_hr FROM garmin_activities ga "
        "JOIN activity_analytics aa ON aa.activity_id = ga.activity_id "
        "WHERE ga.activity_type = ? AND ga.activity_id != ? "
        "AND aa.avg_temperature IS NOT NULL AND aa.avg_temperature <= ? "
        "ORDER BY ga.start_time_local DESC LIMIT ?",
        (activity_row["activity_type"], activity_row["activity_id"], HEAT_THRESHOLD_C, BASELINE_ACTIVITY_COUNT)
    ).fetchall()
    efficiencies = [r["average_speed"] / r["average_hr"] for r in baseline_rows if r["average_speed"] and r["average_hr"]]
    if not efficiencies:
        return 0
    baseline_efficiency = median(efficiencies)
    if not baseline_efficiency:
        return 0
    worse_pct = (baseline_efficiency - this_efficiency) / baseline_efficiency * 100.0
    return int(worse_pct > HEAT_EFFECT_PCT)


def compute_activity_analytics(activity_id):
    """Berechnet und speichert die activity_analytics-Zeile für activity_id. Rein lesend/rechnend
    auf bereits synchronisierten Daten (garmin_activities + garmin_activity_details) - kein API-Call."""
    conn = get_connection()
    cursor = conn.cursor()

    activity_row = cursor.execute(
        "SELECT * FROM garmin_activities WHERE activity_id = ?", (activity_id,)
    ).fetchone()
    if not activity_row:
        conn.close()
        return

    details = cursor.execute(
        "SELECT * FROM garmin_activity_details WHERE activity_id = ? ORDER BY seq", (activity_id,)
    ).fetchall()

    activity_type = activity_row["activity_type"]
    duration = activity_row["duration_seconds"] or 0

    decoupling_pct = hr_drift_pct = negative_split_bool = None
    avg_temperature = gap_pace = None
    variability_index = None

    if details:
        avg_temperature = _avg([d["temperature"] for d in details])
        if activity_type in DECOUPLING_ACTIVITY_TYPES and duration >= MIN_DURATION_FOR_DECOUPLING:
            decoupling_pct, hr_drift_pct, negative_split_bool = _pace_hr_split_metrics(details)
        # GAP ist ein Lauf-spezifisches Konzept (Minettis Kostenfunktion modelliert die
        # Laufökonomie) - fürs Rad übernimmt variability_index (NP/AP) dieselbe Rolle.
        if activity_type in RUNNING_ACTIVITY_TYPES and (activity_row["elevation_gain"] or 0) >= MIN_ELEVATION_FOR_GAP:
            gap_pace = _gap_avg_pace_sec_per_km(details)

    if activity_type in CYCLING_ACTIVITY_TYPES and activity_row["avg_power"] and activity_row["norm_power"]:
        variability_index = activity_row["norm_power"] / activity_row["avg_power"]

    linked_brick_id = _find_linked_brick_activity(cursor, activity_row)
    bike_to_run_drop = _bike_to_run_pace_drop_pct(cursor, activity_row, linked_brick_id)
    outlier = _outlier_flag(cursor, activity_row)
    heat_flag = _heat_effect_flag(cursor, activity_row, avg_temperature)

    conn.close()

    upsert_by_key("activity_analytics", "activity_id", {
        "activity_id": activity_id,
        "date": (activity_row["start_time_local"] or "")[:10] or None,
        "decoupling_pct": decoupling_pct,
        "negative_split_bool": negative_split_bool,
        "variability_index": variability_index,
        "hr_drift_pct": hr_drift_pct,
        "avg_temperature": avg_temperature,
        "heat_effect_flag": heat_flag,
        "gap_avg_pace_sec_per_km": gap_pace,
        "linked_brick_activity_id": linked_brick_id,
        "bike_to_run_pace_drop_pct": bike_to_run_drop,
        "outlier_flag": outlier,
    })
