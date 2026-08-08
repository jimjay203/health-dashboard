"""
Schicht 2 der KI-Chat-Vorbereitung: regelbasierte Wochen-Kennzahlen (Volumen, Zonen-Verteilung,
Cross-Training, Trainingsphase) - kein LLM-Call. Baut auf daily_summary/activity_analytics
(Schicht 1) und den Friel-Trainingszonen-Tabellen auf. Wird bei jedem Sync (auch Backfill-Tage)
für die jeweils betroffene ISO-Kalenderwoche berechnet, siehe
garmin_service.fetch_and_store_garmin_data().
"""
from datetime import date, timedelta
from statistics import mean
from db import get_connection, upsert_by_key

RUNNING_TYPES = {"running", "trail_running", "treadmill_running", "street_running", "track_running",
                 "indoor_running", "ultra_run", "virtual_run"}
CYCLING_TYPES = {"cycling", "road_biking", "indoor_cycling", "mountain_biking", "gravel_cycling"}
SWIMMING_TYPES = {"lap_swimming", "open_water_swimming"}

# --- Tunable Konstanten (analog zu training_zones.py/daily_summary.py) ---
DISCIPLINE_LIMITER_MIN_PCT = 3.0        # Mindest-Rückstand ggü. eigenem Bestwert, um limiter zu nennen
TAPER_DAYS_THRESHOLD = 10               # <= 10 Tage bis Rennen -> Taper
PEAK_DAYS_THRESHOLD = 28                # <= 28 Tage bis Rennen -> Peak
BUILD_VOLUME_RATIO = 1.1                # > 1.1x Schnitt der letzten 3 Wochen -> Build
LONGEST_SESSION_TREND_WEEKS = 4
TRAINING_PHASE_LOOKBACK_WEEKS = 3
POLARIZATION_MIN_Z1_Z2_PCT = 70.0       # gängige Polarised-Training-Richtgröße


def iso_week_info(target_date):
    """ISO-Wochen-Bucketing (week_id, iso_year, iso_week, week_start, week_end) für target_date.
    Public (vormals _iso_week_info) - injury_log.py::weekly_max_severity nutzt dieselbe Logik
    zum Bucketing statt eine zweite ISO-Wochen-Implementierung zu bauen."""
    d = date.fromisoformat(target_date)
    iso_year, iso_week, iso_weekday = d.isocalendar()
    week_start = d - timedelta(days=iso_weekday - 1)
    week_end = week_start + timedelta(days=6)
    return f"{iso_year}-W{iso_week:02d}", iso_year, iso_week, week_start.isoformat(), week_end.isoformat()


def _previous_week_ids(week_start_date, n):
    """n vorherige week_ids (älteste zuerst), über Jahresgrenzen hinweg korrekt."""
    d = date.fromisoformat(week_start_date)
    ids = []
    for i in range(1, n + 1):
        y, w, _ = (d - timedelta(weeks=i)).isocalendar()
        ids.append(f"{y}-W{w:02d}")
    return list(reversed(ids))


def _sum_km(activities, type_set):
    return sum((a["distance_meters"] or 0) for a in activities if a["activity_type"] in type_set) / 1000.0


def _nearest_zone_snapshot(cursor, table, activity_date):
    """Zonen-Grenzen, die zum Zeitpunkt der Aktivität gültig waren: neuester Snapshot mit
    date <= activity_date, sonst (Aktivität vor dem ersten Snapshot) der älteste verfügbare."""
    row = cursor.execute(
        f"SELECT date FROM {table} WHERE date <= ? ORDER BY date DESC LIMIT 1", (activity_date,)
    ).fetchone()
    if not row:
        row = cursor.execute(f"SELECT date FROM {table} ORDER BY date ASC LIMIT 1").fetchone()
    if not row:
        return None
    return cursor.execute(f"SELECT * FROM {table} WHERE date = ?", (row[0],)).fetchall()


def _bucket_seconds_by_hr_zone(hr_values, zone_rows):
    z1_z2_labels = {"1", "2"}
    result = {"z1_z2": 0, "z3_plus": 0}
    for hr in hr_values:
        if hr is None:
            continue
        for z in zone_rows:
            lo = z["hr_min"] if z["hr_min"] is not None else -1
            hi = z["hr_max"] if z["hr_max"] is not None else 999
            if lo <= hr <= hi:
                result["z1_z2" if z["zone"] in z1_z2_labels else "z3_plus"] += 1
                break
    return result


def _zone_distribution_seconds(cursor, activities):
    """Sekunden in Zone 1-2 vs. Zone 3+ über alle Aktivitäten der Woche. Präzise Sekunde-für-
    Sekunde-Bucketing der echten HF gegen die Friel-Zonengrenzen, wenn Detaildaten + eine passende
    Zonen-Tabelle vorhanden sind (Laufen/Radfahren) - sonst Fallback auf Garmins eigenes
    5-Zonen-Modell (hr_zone_1..5, deckt auch Schwimmen ab, wofür es keine Friel-Zonen gibt)."""
    z1_z2_total, z3_plus_total = 0, 0
    for a in activities:
        zone_table = None
        if a["activity_type"] in RUNNING_TYPES:
            zone_table = "training_zones_running"
        elif a["activity_type"] in CYCLING_TYPES:
            zone_table = "training_zones_cycling_hr"

        bucketed = None
        if a["has_details_synced"] and zone_table and a["start_time_local"]:
            hr_values = [r[0] for r in cursor.execute(
                "SELECT heart_rate FROM garmin_activity_details WHERE activity_id = ?",
                (a["activity_id"],)
            ).fetchall()]
            zone_rows = _nearest_zone_snapshot(cursor, zone_table, a["start_time_local"][:10])
            if zone_rows and hr_values:
                bucketed = _bucket_seconds_by_hr_zone(hr_values, zone_rows)

        if bucketed:
            z1_z2_total += bucketed["z1_z2"]
            z3_plus_total += bucketed["z3_plus"]
        else:
            z1_z2_total += (a["hr_zone_1"] or 0) + (a["hr_zone_2"] or 0)
            z3_plus_total += (a["hr_zone_3"] or 0) + (a["hr_zone_4"] or 0) + (a["hr_zone_5"] or 0)
    return z1_z2_total, z3_plus_total


def _discipline_limiter(cursor, target_date):
    """Vergleicht den aktuellsten VO2max-Wert je Disziplin gegen das bisherige Allzeithoch
    derselben Disziplin - die Disziplin mit dem größeren relativen Rückstand ist der Limiter.
    Schwimmen ausgeschlossen (Garmin liefert dafür keinen vergleichbaren Trendwert)."""
    rows = cursor.execute(
        "SELECT vo2max_running, vo2max_cycling FROM garmin_max_metrics WHERE date <= ? ORDER BY date",
        (target_date,)
    ).fetchall()
    running_vals = [r[0] for r in rows if r[0] is not None]
    cycling_vals = [r[1] for r in rows if r[1] is not None]

    def _shortfall(vals):
        if not vals:
            return None
        best = max(vals)
        return (best - vals[-1]) / best * 100.0 if best else None

    candidates = [
        (name, s) for name, s in (("Laufen", _shortfall(running_vals)), ("Radfahren", _shortfall(cycling_vals)))
        if s is not None and s >= DISCIPLINE_LIMITER_MIN_PCT
    ]
    return max(candidates, key=lambda c: c[1])[0] if candidates else None


def _days_until_next_race(cursor, target_date):
    row = cursor.execute(
        "SELECT MIN(event_date) AS next_race FROM garmin_scheduled_events "
        "WHERE is_race = 1 AND event_date >= ?", (target_date,)
    ).fetchone()
    if not row or not row["next_race"]:
        return None
    return (date.fromisoformat(row["next_race"]) - date.fromisoformat(target_date)).days


def _avg_7d(cursor, table, column, target_date):
    start = (date.fromisoformat(target_date) - timedelta(days=6)).isoformat()
    rows = cursor.execute(
        f"SELECT {column} FROM {table} WHERE date >= ? AND date <= ? AND {column} IS NOT NULL",
        (start, target_date)
    ).fetchall()
    values = [r[0] for r in rows]
    return mean(values) if values else None


def _longest_session_trend(cursor, week_start, this_week_longest_km):
    prev_ids = _previous_week_ids(week_start, LONGEST_SESSION_TREND_WEEKS)
    placeholders = ",".join("?" for _ in prev_ids)
    rows = cursor.execute(
        f"SELECT longest_session_km FROM weekly_summary WHERE week_id IN ({placeholders})", prev_ids
    ).fetchall()
    values = [r[0] for r in rows if r[0] is not None]
    if not values:
        return None
    avg_prev = mean(values)
    return (this_week_longest_km - avg_prev) / avg_prev * 100.0 if avg_prev else None


def _training_phase(cursor, week_start, this_week_minutes, days_until_race):
    if days_until_race is not None and days_until_race <= TAPER_DAYS_THRESHOLD:
        return "Taper"
    if days_until_race is not None and days_until_race <= PEAK_DAYS_THRESHOLD:
        return "Peak"
    prev_ids = _previous_week_ids(week_start, TRAINING_PHASE_LOOKBACK_WEEKS)
    placeholders = ",".join("?" for _ in prev_ids)
    rows = cursor.execute(
        f"SELECT volume_total_minutes FROM weekly_summary WHERE week_id IN ({placeholders})", prev_ids
    ).fetchall()
    values = [r[0] for r in rows if r[0] is not None]
    if values and this_week_minutes > mean(values) * BUILD_VOLUME_RATIO:
        return "Build"
    return "Base"


def _yoy_volume(cursor, iso_year, iso_week):
    week_id = f"{iso_year - 1}-W{iso_week:02d}"
    row = cursor.execute(
        "SELECT volume_running_km, volume_cycling_km, volume_swimming_km FROM weekly_summary WHERE week_id = ?",
        (week_id,)
    ).fetchone()
    if not row or all(v is None for v in row):
        return None
    return (row[0] or 0) + (row[1] or 0) + (row[2] or 0)


def _week_data_quality(cursor, week_start, week_end):
    rows = cursor.execute(
        "SELECT date, data_quality_flag FROM daily_summary WHERE date >= ? AND date <= ?",
        (week_start, week_end)
    ).fetchall()
    present_dates = {r[0] for r in rows}
    total_days = (date.fromisoformat(week_end) - date.fromisoformat(week_start)).days + 1
    flagged = sum(1 for r in rows if r[1] is not None)
    missing = total_days - len(present_dates)
    problem_days = flagged + missing
    return f"{problem_days}/{total_days} Tage unvollständig" if problem_days else None


def _notable_events_text(discipline_limiter, training_phase, days_until_race, zone_z1_z2_pct, data_quality_flag):
    if days_until_race is not None and days_until_race <= 7:
        return f"Nur noch {days_until_race} Tage bis zum nächsten Rennen ({training_phase}-Phase)."
    if discipline_limiter:
        return f"{discipline_limiter} liegt aktuell am weitesten hinter der eigenen Bestform zurück."
    if zone_z1_z2_pct is not None and zone_z1_z2_pct < POLARIZATION_MIN_Z1_Z2_PCT:
        return f"Nur {zone_z1_z2_pct:.0f}% der Trainingszeit in Zone 1-2 - wenig polarisiert diese Woche."
    if data_quality_flag:
        return f"Datenlücken diese Woche: {data_quality_flag}."
    return f"{training_phase}-Phase, keine besonderen Auffälligkeiten."


def compute_weekly_summary(target_date):
    """Berechnet und speichert die weekly_summary-Zeile für die ISO-Woche, in der target_date
    liegt. Rein lesend/rechnend auf bereits synchronisierten Daten - kein API-Call."""
    week_id, iso_year, iso_week, week_start, week_end = iso_week_info(target_date)

    conn = get_connection()
    cursor = conn.cursor()

    activities = cursor.execute(
        "SELECT * FROM garmin_activities WHERE date(start_time_local) >= ? AND date(start_time_local) <= ?",
        (week_start, week_end)
    ).fetchall()

    volume_running_km = _sum_km(activities, RUNNING_TYPES)
    volume_cycling_km = _sum_km(activities, CYCLING_TYPES)
    volume_swimming_km = _sum_km(activities, SWIMMING_TYPES)
    volume_total_minutes = sum((a["duration_seconds"] or 0) for a in activities) / 60.0

    total_km = volume_running_km + volume_cycling_km + volume_swimming_km
    if total_km > 0:
        cross_run_pct = volume_running_km / total_km * 100
        cross_bike_pct = volume_cycling_km / total_km * 100
        cross_swim_pct = volume_swimming_km / total_km * 100
    else:
        cross_run_pct = cross_bike_pct = cross_swim_pct = None

    z1_z2_secs, z3_plus_secs = _zone_distribution_seconds(cursor, activities)
    total_zone_secs = z1_z2_secs + z3_plus_secs
    if total_zone_secs > 0:
        zone_z1_z2_pct = z1_z2_secs / total_zone_secs * 100
        zone_z3_plus_pct = 100 - zone_z1_z2_pct
    else:
        zone_z1_z2_pct = zone_z3_plus_pct = None

    longest_session_km = max(((a["distance_meters"] or 0) for a in activities), default=0.0) / 1000.0
    longest_trend_pct = _longest_session_trend(cursor, week_start, longest_session_km)

    discipline_limiter = _discipline_limiter(cursor, target_date)
    days_until_race = _days_until_next_race(cursor, target_date)
    avg_readiness_7d = _avg_7d(cursor, "garmin_training_readiness", "score", target_date)
    avg_hrv_7d = _avg_7d(cursor, "garmin_daily", "avg_hrv", target_date)
    training_phase = _training_phase(cursor, week_start, volume_total_minutes, days_until_race)
    yoy_volume = _yoy_volume(cursor, iso_year, iso_week)
    data_quality_flag = _week_data_quality(cursor, week_start, week_end)
    notable_text = _notable_events_text(
        discipline_limiter, training_phase, days_until_race, zone_z1_z2_pct, data_quality_flag
    )

    conn.close()

    upsert_by_key("weekly_summary", "week_id", {
        "week_id": week_id,
        "year": iso_year,
        "iso_week": iso_week,
        "week_start_date": week_start,
        "week_end_date": week_end,
        "volume_running_km": volume_running_km,
        "volume_cycling_km": volume_cycling_km,
        "volume_swimming_km": volume_swimming_km,
        "volume_total_minutes": volume_total_minutes,
        "zone_distribution_z1_z2_pct": zone_z1_z2_pct,
        "zone_distribution_z3_plus_pct": zone_z3_plus_pct,
        "cross_training_run_pct": cross_run_pct,
        "cross_training_bike_pct": cross_bike_pct,
        "cross_training_swim_pct": cross_swim_pct,
        "discipline_limiter": discipline_limiter,
        "longest_session_km": longest_session_km,
        "longest_session_vs_4wk_trend_pct": longest_trend_pct,
        "training_phase": training_phase,
        "days_until_next_race": days_until_race,
        "avg_readiness_7d": avg_readiness_7d,
        "avg_hrv_7d": avg_hrv_7d,
        "yoy_same_week_volume_km": yoy_volume,
        "data_quality_flag": data_quality_flag,
        "notable_events_text": notable_text,
    })
