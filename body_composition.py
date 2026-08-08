"""
Körper-Seite (siehe backend/routers/body.py): Körperzusammensetzung aus withings_weigh_ins,
abgeleitete Kennzahlen (FFMI, Muskel-Fett-Ratio, BMR) und der What-if-Simulator (Zielgewicht ->
Rad-W/kg, relativer Lauf-VO2max, Renn-Zeit-Prognose). Reine Python-Logik, kein Streamlit-Import
(gleiches Muster wie daily_summary.py/performance_goals.py).

Withings-Feld-Ground-Truth (siehe withings_service.py::MEASURE_TYPE_*): weight/bone_mass/
muscle_mass/fat_mass_kg sind Massen in kg, body_fat ist ein Prozentwert (0-100), body_water ist
TROTZ des Spaltennamens KEIN Prozentwert, sondern die Wassermasse in kg (Withings-Messtyp 77
"Hydration" liefert eine Masse, keine Quote) - in der UI entsprechend als "kg" beschriften, nicht
als "%".

Fettfreie Masse wird bewusst als weight - fat_mass_kg berechnet (nicht als Summe aus
muscle_mass+bone_mass+body_water), da diese drei Einzelwerte durch Withings' eigene
Schätzverfahren nicht exakt zu weight-fat_mass_kg aufsummieren müssen - weight/fat_mass_kg aus
derselben Messgruppe sind die konsistentere Paarung.
"""
from datetime import date, datetime, timedelta

import correlation_stats
import injury_log
from db import get_connection, upsert_by_key
from load_focus import ZONE_LABELS_LOW_AEROBIC
from training_zones import zone_bounds_for_date
from weekly_summary import RUNNING_TYPES, iso_week_info

BODY_TREND_MAX_DAYS = 365
WEIGHT_ROLLING_AVG_WINDOW_DAYS = 7

# "Körper- & Performance-Einfluss"-Kachel (siehe backend/routers/body.py::get_performance_
# correlations) - eigene Tunables, analog zu training_zones.py/daily_summary.py.
PERFORMANCE_CORRELATIONS_DAYS = 90       # gleicher Default wie get_body_trend()
GA1_PACE_WINDOW_DAYS = 28                # gleiches Rollfenster wie load_focus.LOAD_FOCUS_WINDOW_DAYS -
                                          # Läufe sind seltener als tägliche Wiegungen, 7 Tage wäre zu dünn.


def _latest_withings_row():
    conn = get_connection()
    row = conn.execute(
        "SELECT date, weight, body_fat, body_water, bone_mass, muscle_mass, fat_mass_kg "
        "FROM withings_weigh_ins WHERE weight IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _fat_free_mass_kg(weight_kg, fat_mass_kg):
    if weight_kg is None or fat_mass_kg is None:
        return None
    return weight_kg - fat_mass_kg


def compute_ffmi(fat_free_mass_kg, height_cm):
    if fat_free_mass_kg is None or not height_cm:
        return None
    height_m = height_cm / 100
    return fat_free_mass_kg / (height_m ** 2)


def compute_bmr_katch_mcardle(fat_free_mass_kg):
    """Katch-McArdle-Formel (Lehrbuch-Standard, keine Coach-Faustregel) - BMR aus fettfreier
    Masse statt Körpergewicht/Alter/Geschlecht (Harris-Benedict), da Withings die fettfreie Masse
    direkt liefert und diese Formel bei athletischen Körpern präziser gilt."""
    if fat_free_mass_kg is None:
        return None
    return 370 + 21.6 * fat_free_mass_kg


def compute_muscle_fat_ratio(muscle_mass_kg, fat_mass_kg):
    if not muscle_mass_kg or not fat_mass_kg:
        return None
    return muscle_mass_kg / fat_mass_kg


def compute_body_water_pct(weight_kg, body_water_kg):
    """body_water_kg ist eine Masse (siehe Moduldocstring) - Prozentanteil am Körpergewicht wird
    hier abgeleitet, keine Rohgröße aus Withings."""
    if not weight_kg or body_water_kg is None:
        return None
    return body_water_kg / weight_kg * 100


# Grobe Referenzspanne für erwachsene Männer (Quelle: InBody-Referenzwerte - sedentary ~50-55%,
# aktiv ~55-65%, athletisch ~60-70% Körperwasseranteil), KEINE personalisierte oder medizinische
# Bewertung. Nur zwei Stufen wie vom Nutzer vorgegeben (Normal/Erhöht) statt einer feineren
# Abstufung - Schwelle an der oberen Grenze der "aktiv"-Spanne orientiert.
HYDRATION_HIGH_THRESHOLD_PCT = 65.0


def hydration_status(water_pct):
    if water_pct is None:
        return None
    return "erhöht" if water_pct > HYDRATION_HIGH_THRESHOLD_PCT else "normal"


# FFMI-Klassifizierung für Männer (natural, nicht leistungssportlich optimiert) - eine von mehreren
# gängigen Einteilungen (Quelle: ffmicalculator.io/what-is-a-good-ffmi-score, abgerufen 2026-08-07).
# Andere Quellen setzen die Grenzen leicht anders (z.B. feinere 13-Stufen-Skalen mit Perzentilen) -
# dies ist EINE zitierfähige Variante, keine allgemeingültige medizinische Norm. Obergrenze
# exklusiv: ein Wert wird der ersten Stufe zugeordnet, deren Obergrenze er unterschreitet.
FFMI_CLASSIFICATION_BANDS = [
    (18.0, "Unterdurchschnittlich"),
    (20.0, "Durchschnittlich"),
    (23.0, "Sportlich"),
    (25.0, "Muskulös"),
]
FFMI_CLASSIFICATION_TOP_LABEL = "Außergewöhnlich (natürliches Limit)"


def ffmi_classification(ffmi):
    if ffmi is None:
        return None
    for upper_bound, label in FFMI_CLASSIFICATION_BANDS:
        if ffmi < upper_bound:
            return label
    return FFMI_CLASSIFICATION_TOP_LABEL


def get_body_settings():
    conn = get_connection()
    rows = conn.execute("SELECT key, value, source FROM body_settings").fetchall()
    conn.close()
    values = {r["key"]: r["value"] for r in rows}
    sources = {r["key"]: r["source"] for r in rows}
    return {
        "height_cm": values.get("height_cm"),
        "height_source": sources.get("height_cm"),
        "target_weight_kg": values.get("target_weight_kg"),
        "target_body_fat_pct": values.get("target_body_fat_pct"),
    }


def save_body_setting(key, value, source=None):
    upsert_by_key("body_settings", "key", {
        "key": key,
        "value": value,
        "source": source,
        "updated_at": datetime.now().isoformat(),
    })


def sync_height_from_garmin(height_cm):
    """Automatischer Höhen-Sync aus Garmins get_user_profile() (siehe garmin_service.py -
    _fetch_body_composition, läuft nur für "heute"). Überschreibt NICHT, wenn der Nutzer die
    Größe unter Einstellungen manuell übersteuert hat (source='manual')."""
    conn = get_connection()
    row = conn.execute("SELECT source FROM body_settings WHERE key = 'height_cm'").fetchone()
    conn.close()
    if row and row["source"] == "manual":
        return
    save_body_setting("height_cm", height_cm, source="garmin")


def reset_height_to_garmin():
    """Setzt die Quelle zurück auf 'garmin', ohne den Wert selbst zu ändern - der nächste
    tägliche Garmin-Sync überschreibt ihn automatisch mit dem aktuellen Profil-Wert (siehe
    sync_height_from_garmin)."""
    conn = get_connection()
    conn.execute("UPDATE body_settings SET source = 'garmin' WHERE key = 'height_cm'")
    conn.commit()
    conn.close()


def _latest_cycling_ftp_watts():
    conn = get_connection()
    row = conn.execute(
        "SELECT functional_threshold_power FROM garmin_cycling_ftp "
        "WHERE functional_threshold_power IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["functional_threshold_power"] if row else None


def _latest_vo2max_running():
    conn = get_connection()
    row = conn.execute(
        "SELECT vo2max_running FROM garmin_max_metrics WHERE vo2max_running IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["vo2max_running"] if row else None


def _latest_vo2max_cycling():
    conn = get_connection()
    row = conn.execute(
        "SELECT vo2max_cycling FROM garmin_max_metrics WHERE vo2max_cycling IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["vo2max_cycling"] if row else None


def _latest_running_power_to_weight():
    conn = get_connection()
    row = conn.execute(
        "SELECT power_to_weight FROM garmin_lactate_threshold WHERE power_to_weight IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["power_to_weight"] if row else None


def _latest_cycling_power_to_weight():
    conn = get_connection()
    row = conn.execute(
        "SELECT power_to_weight FROM garmin_cycling_ftp WHERE power_to_weight IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["power_to_weight"] if row else None


def _latest_running_ftp_watts():
    conn = get_connection()
    row = conn.execute(
        "SELECT functional_threshold_power FROM garmin_lactate_threshold "
        "WHERE functional_threshold_power IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["functional_threshold_power"] if row else None


def _weight_7d_trend_kg():
    """Differenz aktuellste Messung vs. Ø der 7 Tage DAVOR (nicht inkl. der aktuellen Messung
    selbst) - sonst würde ein Schnitt, der den aktuellen Tag bereits einschließt, die eigene
    Abweichung künstlich verkleinern."""
    conn = get_connection()
    latest = conn.execute(
        "SELECT date, weight FROM withings_weigh_ins WHERE weight IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    if not latest:
        conn.close()
        return None
    latest_date = date.fromisoformat(latest["date"])
    window_start = (latest_date - timedelta(days=WEIGHT_ROLLING_AVG_WINDOW_DAYS)).isoformat()
    window_end = (latest_date - timedelta(days=1)).isoformat()
    rows = conn.execute(
        "SELECT weight FROM withings_weigh_ins WHERE weight IS NOT NULL AND date >= ? AND date <= ?",
        (window_start, window_end)
    ).fetchall()
    conn.close()
    values = [r["weight"] for r in rows]
    if not values:
        return None
    return latest["weight"] - (sum(values) / len(values))


def _latest_race_predictions():
    conn = get_connection()
    row = conn.execute(
        "SELECT time_5k, time_10k, time_half_marathon, time_marathon FROM garmin_race_predictions "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def _latest_daily_summary_extras():
    conn = get_connection()
    row = conn.execute(
        "SELECT date, weight_vs_avg_pct, days_until_next_race FROM daily_summary "
        "WHERE weight_vs_avg_pct IS NOT NULL OR days_until_next_race IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_body_overview():
    withings = _latest_withings_row() or {}
    settings = get_body_settings()
    weight_kg = withings.get("weight")
    fat_mass_kg = withings.get("fat_mass_kg")
    fat_free_mass_kg = _fat_free_mass_kg(weight_kg, fat_mass_kg)
    daily_extras = _latest_daily_summary_extras()
    ffmi = compute_ffmi(fat_free_mass_kg, settings.get("height_cm"))
    water_pct = compute_body_water_pct(weight_kg, withings.get("body_water"))

    return {
        "measured_date": withings.get("date"),
        "weight_kg": weight_kg,
        "weight_trend_7d_kg": _weight_7d_trend_kg(),
        "body_fat_pct": withings.get("body_fat"),
        "body_water_kg": withings.get("body_water"),
        "body_water_pct": water_pct,
        "hydration_status": hydration_status(water_pct),
        "bone_mass_kg": withings.get("bone_mass"),
        "muscle_mass_kg": withings.get("muscle_mass"),
        "fat_mass_kg": fat_mass_kg,
        "fat_free_mass_kg": fat_free_mass_kg,
        "ffmi": ffmi,
        "ffmi_classification": ffmi_classification(ffmi),
        "muscle_fat_ratio": compute_muscle_fat_ratio(withings.get("muscle_mass"), fat_mass_kg),
        "bmr_kcal": compute_bmr_katch_mcardle(fat_free_mass_kg),
        "height_cm": settings.get("height_cm"),
        "target_weight_kg": settings.get("target_weight_kg"),
        "target_body_fat_pct": settings.get("target_body_fat_pct"),
        "weight_vs_avg_pct": daily_extras.get("weight_vs_avg_pct"),
        "days_until_next_race": daily_extras.get("days_until_next_race"),
        "running_power_to_weight": _latest_running_power_to_weight(),
        "cycling_power_to_weight": _latest_cycling_power_to_weight(),
        "running_ftp_watts": _latest_running_ftp_watts(),
        "cycling_ftp_watts": _latest_cycling_ftp_watts(),
        "vo2max_running": _latest_vo2max_running(),
        "vo2max_cycling": _latest_vo2max_cycling(),
    }


def get_body_trend(days=90):
    days = min(days, BODY_TREND_MAX_DAYS)
    end = date.today()
    start = end - timedelta(days=days - 1)

    conn = get_connection()
    withings_rows = conn.execute(
        "SELECT date, weight, body_fat, body_water, bone_mass, muscle_mass, fat_mass_kg "
        "FROM withings_weigh_ins WHERE date >= ? AND date <= ? ORDER BY date, timestamp",
        (start.isoformat(), end.isoformat())
    ).fetchall()
    journal_rows = conn.execute(
        "SELECT date, muscle_soreness FROM daily_journal WHERE date >= ? AND date <= ? "
        "AND muscle_soreness IS NOT NULL",
        (start.isoformat(), end.isoformat())
    ).fetchall()
    # Tages-Trainingslast für die Überlagerung im Schmerz-Chart (gleiches Feld/Muster wie die
    # Korrelations-Charts der Schlaf-Seite, siehe backend/routers/sleep.py).
    training_load_rows = conn.execute(
        "SELECT date(start_time_local) AS date, SUM(activity_training_load) AS load "
        "FROM garmin_activities WHERE date(start_time_local) >= ? AND date(start_time_local) <= ? "
        "GROUP BY date(start_time_local)",
        (start.isoformat(), end.isoformat())
    ).fetchall()
    conn.close()

    # Ein Wert pro Tag (letzte Messung, falls mehrere) statt aller Rohmessungen - vermeidet, dass
    # ein Tag mit mehreren Wiegungen den Trend-Chart verzerrt.
    by_date = {}
    for r in withings_rows:
        by_date[r["date"]] = dict(r)
    sorted_dates = sorted(by_date.keys())

    # Gleitender 7-Tage-Durchschnitt des Gewichts (glättet Glykogen-/Wasserschwankungen, ohne eine
    # nicht gemessene Ursache zu behaupten - siehe Brainstorming-Entscheidung gegen eine
    # "Glykogen-Erklärung" mit erfundenen Schwellenwerten).
    points = []
    for d in sorted_dates:
        row = by_date[d]
        window = [
            by_date[wd]["weight"] for wd in sorted_dates
            if wd <= d and (date.fromisoformat(d) - date.fromisoformat(wd)).days < WEIGHT_ROLLING_AVG_WINDOW_DAYS
            and by_date[wd]["weight"] is not None
        ]
        rolling_avg = sum(window) / len(window) if window else None
        points.append({
            "date": d,
            "weight_kg": row.get("weight"),
            "weight_rolling_avg_kg": rolling_avg,
            "body_fat_pct": row.get("body_fat"),
            "body_water_kg": row.get("body_water"),
            "bone_mass_kg": row.get("bone_mass"),
            "muscle_mass_kg": row.get("muscle_mass"),
            "fat_mass_kg": row.get("fat_mass_kg"),
        })

    muscle_soreness_points = [{"date": r["date"], "muscle_soreness": r["muscle_soreness"]} for r in journal_rows]
    training_load_points = [{"date": r["date"], "training_load": r["load"]} for r in training_load_rows]

    return {"points": points, "muscle_soreness_points": muscle_soreness_points, "training_load_points": training_load_points}


def compute_what_if(target_weight_kg):
    overview = get_body_overview()
    current_weight_kg = overview["weight_kg"]

    ftp_watts = _latest_cycling_ftp_watts()
    cycling_power_to_weight_target = ftp_watts / target_weight_kg if ftp_watts else None

    vo2max_running = _latest_vo2max_running()
    vo2max_running_target = (
        vo2max_running * current_weight_kg / target_weight_kg
        if vo2max_running is not None and current_weight_kg else None
    )

    # Renn-Zeit-Prognose: Zeit skaliert direkt proportional zum Gewichtsverhältnis - dieselbe
    # Annahme wie bei vo2max_running_target oben (absolute VO2max-Kapazität bleibt konstant, die
    # relative VO2max skaliert mit 1/Gewicht). Da Zeit ~ 1/(relative VO2max) angenommen wird, kürzt
    # sich das zu new_time = current_time * (target_weight / current_weight) - siehe Bugfix-
    # Anforderung vom Nutzer (ersetzt die vorherige "0,8-1% pro 1% Gewichtsverlust"-Faustregel, die
    # bei realistischen Gewichtsänderungen kaum spürbare Zeitunterschiede ergab). Funktioniert
    # symmetrisch für Zunahme UND Verlust, kein Gating mehr nötig.
    race_time_projection = None
    if current_weight_kg:
        weight_ratio = target_weight_kg / current_weight_kg
        predictions = _latest_race_predictions()
        projection = {
            key: {"current_seconds": predictions[key], "target_seconds": round(predictions[key] * weight_ratio)}
            for key in ("time_5k", "time_10k", "time_half_marathon", "time_marathon")
            if predictions.get(key) is not None
        }
        race_time_projection = projection or None

    return {
        "current_weight_kg": current_weight_kg,
        "target_weight_kg": target_weight_kg,
        "cycling_ftp_watts": ftp_watts,
        "cycling_power_to_weight_current": overview["cycling_power_to_weight"],
        "cycling_power_to_weight_target": cycling_power_to_weight_target,
        "vo2max_running_current": vo2max_running,
        "vo2max_running_target": vo2max_running_target,
        "race_time_projection": race_time_projection,
    }


# --- "Körper- & Performance-Einfluss"-Kachel (Category-B-Korrelationen, siehe Plan) ---

def _classify_hr_zone(hr, bounds):
    for label, lo, hi in bounds:
        if (lo is None or hr >= lo) and (hi is None or hr <= hi):
            return label
    return None


def _weight_by_date(cursor, start, end):
    """Ein Gewichtswert pro Tag (Withings bevorzugt, sonst Garmin - gleiche Quellen-Präferenz wie
    _weight_series_for_range/_weight_for_date), hier zusätzlich mit Datum statt als flache Liste -
    für die Tag-für-Tag-Rollierung unten gebraucht. Aufsteigend nach Zeitstempel iteriert, damit ein
    späterer Dict-Eintrag pro Datum die jeweils letzte Messung des Tages überschreibt."""
    result = {}
    for r in cursor.execute(
        "SELECT date, weight FROM withings_weigh_ins WHERE date >= ? AND date <= ? "
        "AND weight IS NOT NULL ORDER BY timestamp",
        (start, end)
    ).fetchall():
        result[r["date"]] = r["weight"]
    for r in cursor.execute(
        "SELECT date, weight FROM garmin_weigh_ins WHERE date >= ? AND date <= ? "
        "AND weight IS NOT NULL ORDER BY timestamp_gmt",
        (start, end)
    ).fetchall():
        # garmin_weigh_ins.weight ist in Gramm gespeichert (im Gegensatz zu withings_weigh_ins.weight
        # in kg) - ground-truth verifiziert an echten Datensätzen (84100g vs. 84.941kg für dieselbe
        # Messung am selben Tag). Siehe auch garmin_service.py:694 (dortige Power-to-Weight-Berechnung
        # macht dieselbe /1000-Umrechnung).
        result.setdefault(r["date"], r["weight"] / 1000.0)
    return result


def _weight_7d_avg_by_date(cursor, start_date, end_date):
    """{date: 7-Tage-Rollschnitt}, NUR für Tage mit einer tatsächlichen Messung (gleiches Prinzip
    wie get_body_trend()s weight_rolling_avg_kg - Wiegungen sind lückenhaft, ca. wöchentlich, ein
    Wert für JEDEN Kalendertag im Bereich wäre deshalb überwiegend None). Fenster-Logik (wd <= d,
    Differenz < WEIGHT_ROLLING_AVG_WINDOW_DAYS Tage) identisch zu get_body_trend()."""
    lookback_start = (date.fromisoformat(start_date) - timedelta(days=WEIGHT_ROLLING_AVG_WINDOW_DAYS - 1)).isoformat()
    by_date = _weight_by_date(cursor, lookback_start, end_date)
    sorted_dates = sorted(by_date.keys())

    result = {}
    for d_str in sorted_dates:
        if d_str < start_date or d_str > end_date:
            continue
        d = date.fromisoformat(d_str)
        window = [
            by_date[wd] for wd in sorted_dates
            if wd <= d_str and (d - date.fromisoformat(wd)).days < WEIGHT_ROLLING_AVG_WINDOW_DAYS
        ]
        result[d_str] = sum(window) / len(window) if window else None
    return result


def _ga1_pace_by_date(cursor, start_date, end_date):
    """{date: GA1-Pace (Sekunden/km)} - Ø-Pace der Lauf-Aktivitäten im jeweils vorangehenden
    GA1_PACE_WINDOW_DAYS-Fenster, deren Ø-Herzfrequenz in Friel-Zone 1+2 liegt (siehe Plan-
    Entscheidung: nächstliegende verifizierte Definition für "GA1", da Garmin dieses Konzept nicht
    kennt). Zonen-Snapshot: neuester <= Aktivitätsdatum, sonst früheste verfügbare (siehe
    training_zones.zone_bounds_for_date)."""
    lookback_start = (date.fromisoformat(start_date) - timedelta(days=GA1_PACE_WINDOW_DAYS - 1)).isoformat()
    activities = cursor.execute(
        "SELECT date(start_time_local) AS d, activity_type, average_hr, average_speed "
        "FROM garmin_activities WHERE date(start_time_local) >= ? AND date(start_time_local) <= ? "
        "AND average_hr IS NOT NULL AND average_speed IS NOT NULL AND average_speed > 0",
        (lookback_start, end_date)
    ).fetchall()

    zone_bounds_cache = {}
    ga1_activities = []  # (date, pace_sec_per_km)
    for a in activities:
        if a["activity_type"] not in RUNNING_TYPES:
            continue
        if a["d"] not in zone_bounds_cache:
            zone_bounds_cache[a["d"]] = zone_bounds_for_date(cursor, "training_zones_running", a["d"])
        bounds = zone_bounds_cache[a["d"]]
        if not bounds:
            continue
        label = _classify_hr_zone(a["average_hr"], bounds)
        if label in ZONE_LABELS_LOW_AEROBIC:
            ga1_activities.append((a["d"], 1000.0 / a["average_speed"]))

    result = {}
    d = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    while d <= end:
        window_start = (d - timedelta(days=GA1_PACE_WINDOW_DAYS - 1)).isoformat()
        d_str = d.isoformat()
        paces = [p for (ad, p) in ga1_activities if window_start <= ad <= d_str]
        result[d_str] = sum(paces) / len(paces) if paces else None
        d += timedelta(days=1)
    return result


def _weekly_running_training_load(cursor, start_date, end_date):
    """{week_id: Summe activity_training_load} über Lauf-Aktivitäten - "Trainingslast" statt reiner
    Distanz (siehe Plan-Entscheidung: konsistent mit dem einen etablierten Load-Begriff dieser App,
    ein harter und ein lockerer 10-km-Lauf sollen nicht gleich gewichtet werden)."""
    rows = cursor.execute(
        "SELECT date(start_time_local) AS d, activity_type, activity_training_load FROM garmin_activities "
        "WHERE date(start_time_local) >= ? AND date(start_time_local) <= ? AND activity_training_load IS NOT NULL",
        (start_date, end_date)
    ).fetchall()
    totals = {}
    for r in rows:
        if r["activity_type"] not in RUNNING_TYPES:
            continue
        week_id, *_ = iso_week_info(r["d"])
        totals[week_id] = totals.get(week_id, 0.0) + r["activity_training_load"]
    return totals


def get_performance_correlations(days=PERFORMANCE_CORRELATIONS_DAYS):
    """Zwei Category-B-Korrelationen für die "Körper- & Performance-Einfluss"-Kachel (Körper-Seite):
    Körpergewicht (7-Tage-Schnitt) vs. GA1-Pace (Tages-Ebene) und wöchentlicher Lauf-Load vs.
    maximale wöchentliche Schmerz-Intensität (Wochen-Ebene) - bewusst getrennt von get_body_trend()
    (siehe Moduldocstring-Begründung im Plan: zwei unterschiedliche Aggregationsebenen, die
    get_body_trend()s reine Tages-Punkt-Struktur nicht beide sauber abbilden würde)."""
    days = min(days, BODY_TREND_MAX_DAYS)
    end = date.today()
    start = end - timedelta(days=days - 1)
    start_iso, end_iso = start.isoformat(), end.isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    weight_7d_avg = _weight_7d_avg_by_date(cursor, start_iso, end_iso)
    ga1_pace = _ga1_pace_by_date(cursor, start_iso, end_iso)
    weekly_load = _weekly_running_training_load(cursor, start_iso, end_iso)
    conn.close()

    weekly_severity = injury_log.weekly_max_severity(start_iso, end_iso)

    # Nur Tage mit einer tatsächlichen Gewichtsmessung (weight_7d_avg ist bereits darauf begrenzt,
    # siehe _weight_7d_avg_by_date) - GA1-Pace ist dagegen ein Rollwert für JEDEN Tag verfügbar.
    weight_points = [
        {"date": d_str, "weight_avg_kg": w, "ga1_pace_sec_per_km": ga1_pace.get(d_str)}
        for d_str, w in sorted(weight_7d_avg.items())
    ]
    weight_vs_ga1_pairs = [
        (pt["weight_avg_kg"], pt["ga1_pace_sec_per_km"]) for pt in weight_points
        if pt["weight_avg_kg"] is not None and pt["ga1_pace_sec_per_km"] is not None
    ]

    # Wochen ohne Laufaktivität zählen als 0 Load (kein Trainingsreiz ist ein echter Wert, kein
    # fehlender - gleiche Konvention wie daily_summary._daily_training_loads).
    weekly_points = [
        {"week_id": week_id, "running_load": weekly_load.get(week_id, 0.0), "max_pain_severity": severity}
        for week_id, severity in sorted(weekly_severity.items())
    ]
    weekly_load_vs_severity_pairs = [
        (pt["running_load"], pt["max_pain_severity"]) for pt in weekly_points
    ]

    return {
        "weight_vs_ga1_pace": {
            "points": weight_points,
            "stats": correlation_stats.correlation_summary(weight_vs_ga1_pairs),
        },
        "weekly_running_load_vs_injury_severity": {
            "points": weekly_points,
            "stats": correlation_stats.correlation_summary(weekly_load_vs_severity_pairs),
        },
    }
