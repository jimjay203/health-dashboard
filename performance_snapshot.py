"""
Leistungsziele + Diagnostik-Schnappschuss als Gemini-Kontext-Text - geteilt zwischen
performance_insight.py (Leistung-Seite, "Einschätzung zu deinen Zielen") und weekly_planner.py
(Rolling-Horizon-Wochenplaner), damit beide KI-Aufrufe auf denselben Zahlen basieren statt
unabhängig voneinander leicht unterschiedliche Werte zu berechnen. Reine Python-Logik, kein
Streamlit-/FastAPI-Import (gleiches Muster wie load_focus.py).

Enthält bewusst NICHT den Trainingszustand (CTL/ATL/TSB) oder die Belastungsfokus-Verteilung -
beide Aufrufer haben dafür bereits eigene, zueinander unterschiedlich geformte Kontext-Blöcke
(performance_insight.py::_load_status_block/_load_focus_block bzw. weekly_planner.py's
CTL/ATL/TSB-Trend + weekly_summary-Zeile), ein zusätzlicher dritter hier hätte nur Redundanz ohne
neuen Informationsgehalt erzeugt.
"""
from datetime import date

from db import get_connection
import performance_goals

# Zielstrecken/Intensitäten für die Rad-Wettkampf-Schätzung - identisch zu
# backend/routers/performance.py::CYCLING_PREDICTION_SCENARIOS.
CYCLING_PREDICTION_SCENARIOS = [
    {"key": "sprint", "label": "Sprint", "distance_km": 20.0, "pct_ftp": 0.95},
    {"key": "olympic", "label": "Olympisch", "distance_km": 40.0, "pct_ftp": 0.88},
]
CYCLING_FLAT_ELEVATION_GAIN_PER_KM = 10.0

# Ziel-Typ -> Einheit-Formatierer. Werte selbst kommen NICHT aus einer eigenen
# GOAL_METRIC_SOURCES-Abfrage wie im Router, sondern aus den ohnehin schon für die anderen
# Kontext-Blöcke ermittelten Diagnostik-/Prognose-Werten (siehe _current_goal_values) - dieselben
# Zahlen, die die Leistung-Seite selbst anzeigt.
GOAL_UNIT_KIND = {
    "run_threshold_pace": "pace_km",
    "marathon_pace": "pace_km",
    "halbmarathon_pace": "pace_km",
    "ftp_w_per_kg": "w_per_kg",
    "swim_pace_100m": "pace_100m",
}


def _format_pace_per_km(sec_per_km):
    if sec_per_km is None:
        return None
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d} min/km"


def _format_pace_per_100m(sec_per_100m):
    if sec_per_100m is None:
        return None
    m, s = divmod(int(round(sec_per_100m)), 60)
    return f"{m}:{s:02d} min/100m"


def _format_duration(seconds):
    if seconds is None:
        return None
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d} h" if h else f"{m}:{s:02d} min"


def _format_goal_value(value, unit_kind):
    if value is None:
        return None
    if unit_kind == "pace_km":
        return _format_pace_per_km(value)
    if unit_kind == "pace_100m":
        return _format_pace_per_100m(value)
    if unit_kind == "w_per_kg":
        return f"{value:.2f} W/kg"
    return str(value)


def _thresholds(conn):
    lactate = conn.execute(
        "SELECT date, speed, heart_rate, heart_rate_cycling FROM garmin_lactate_threshold "
        "WHERE speed IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    ftp = conn.execute(
        "SELECT date, functional_threshold_power, power_to_weight FROM garmin_cycling_ftp "
        "WHERE functional_threshold_power IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    vo2max_run = conn.execute(
        "SELECT date, vo2max_running FROM garmin_max_metrics WHERE vo2max_running IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    vo2max_cycle = conn.execute(
        "SELECT date, vo2max_cycling FROM garmin_max_metrics WHERE vo2max_cycling IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    run_pace = (1000.0 / lactate["speed"]) if lactate and lactate["speed"] else None
    return {
        "run_threshold_pace_sec_per_km": run_pace,
        "run_threshold_date": lactate["date"] if lactate else None,
        "run_threshold_hr": lactate["heart_rate"] if lactate else None,
        "cycling_threshold_hr": lactate["heart_rate_cycling"] if lactate else None,
        "ftp_watts": ftp["functional_threshold_power"] if ftp else None,
        "ftp_power_to_weight": ftp["power_to_weight"] if ftp else None,
        "ftp_date": ftp["date"] if ftp else None,
        "vo2max_running": vo2max_run["vo2max_running"] if vo2max_run else None,
        "vo2max_running_date": vo2max_run["date"] if vo2max_run else None,
        "vo2max_cycling": vo2max_cycle["vo2max_cycling"] if vo2max_cycle else None,
        "vo2max_cycling_date": vo2max_cycle["date"] if vo2max_cycle else None,
    }


def _thresholds_block(t):
    parts = []
    if t["vo2max_running"]:
        parts.append(f"VO2max Laufen={t['vo2max_running']} ({t['vo2max_running_date']})")
    if t["vo2max_cycling"]:
        parts.append(f"VO2max Rad={t['vo2max_cycling']} ({t['vo2max_cycling_date']})")
    if t["run_threshold_pace_sec_per_km"]:
        parts.append(
            f"Lauf-Schwellenpace={_format_pace_per_km(t['run_threshold_pace_sec_per_km'])} bei "
            f"{t['run_threshold_hr']} bpm ({t['run_threshold_date']})"
        )
    if t["ftp_watts"]:
        parts.append(
            f"Rad-FTP={t['ftp_watts']}W ({t['ftp_power_to_weight']:.2f} W/kg) bei "
            f"{t['cycling_threshold_hr']} bpm ({t['ftp_date']})"
        )
    if not parts:
        return "Leistungsdiagnostik: keine Schwellenwerte/VO2max-Messung vorhanden."
    return "Leistungsdiagnostik: " + "; ".join(parts) + "."


def _race_predictions(conn):
    row = conn.execute(
        "SELECT date, time_5k, time_10k, time_half_marathon, time_marathon FROM garmin_race_predictions "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else {}


def _race_predictions_block(r):
    if not r:
        return "Wettkampf-Prognose Laufen: keine Garmin-Vorhersage vorhanden."
    parts = []
    for key, label in (("time_5k", "5km"), ("time_10k", "10km"),
                        ("time_half_marathon", "Halbmarathon"), ("time_marathon", "Marathon")):
        if r.get(key):
            parts.append(f"{label}={_format_duration(r[key])}")
    return f"Wettkampf-Prognose Laufen ({r['date']}): " + ", ".join(parts) + "."


def _cycling_prediction(conn):
    rows = conn.execute(
        "SELECT avg_power, average_speed FROM garmin_activities "
        "WHERE activity_type IN ('cycling', 'road_biking') AND avg_power IS NOT NULL "
        "AND avg_power > 0 AND average_speed IS NOT NULL AND distance_meters > 0 "
        "AND (elevation_gain IS NULL OR (elevation_gain / (distance_meters / 1000.0)) <= ?)",
        (CYCLING_FLAT_ELEVATION_GAIN_PER_KM,)
    ).fetchall()
    ftp_row = conn.execute(
        "SELECT functional_threshold_power FROM garmin_cycling_ftp "
        "WHERE functional_threshold_power IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if not rows:
        return None
    efficiency_values = [(r["average_speed"] * 3.6) / r["avg_power"] for r in rows]
    efficiency = sum(efficiency_values) / len(efficiency_values)
    ftp_watts = ftp_row["functional_threshold_power"] if ftp_row else None

    scenarios = []
    for s in CYCLING_PREDICTION_SCENARIOS:
        target_power = ftp_watts * s["pct_ftp"] if ftp_watts else None
        speed_kmh = efficiency * target_power if target_power else None
        duration = (s["distance_km"] / speed_kmh) * 3600 if speed_kmh else None
        scenarios.append({"label": s["label"], "distance_km": s["distance_km"], "duration": duration})
    return {"sample_size": len(rows), "efficiency": efficiency, "scenarios": scenarios}


def _cycling_prediction_block(c):
    if not c:
        return "Wettkampf-Prognose Rad: keine flachen Fahrten mit Leistungsdaten vorhanden."
    parts = [f"{s['label']} {s['distance_km']:.0f}km={_format_duration(s['duration'])}"
             for s in c["scenarios"] if s["duration"]]
    return (
        f"Wettkampf-Prognose Rad (Wirkungsgrad aus {c['sample_size']} flachen Fahrten): "
        + ", ".join(parts) + "." if parts else "Wettkampf-Prognose Rad: FTP fehlt für eine Schätzung."
    )


def _swim_diagnostics(conn):
    row = conn.execute(
        "SELECT date(start_time_local) AS date, average_speed, "
        "json_extract(raw_json, '$.averageSwolf') AS swolf FROM garmin_activities "
        "WHERE activity_type = 'lap_swimming' AND average_speed IS NOT NULL "
        "ORDER BY start_time_local DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {}
    pace = (100.0 / row["average_speed"]) if row["average_speed"] else None
    return {"date": row["date"], "swolf": row["swolf"], "pace_sec_per_100m": pace}


def _swim_diagnostics_block(s):
    if not s:
        return "Schwimm-Diagnostik: keine Bahnschwimmen-Aktivität vorhanden."
    return (
        f"Schwimm-Diagnostik ({s['date']}): SWOLF={s['swolf']}, "
        f"Pace={_format_pace_per_100m(s['pace_sec_per_100m'])}."
    )


def _current_goal_values(thresholds, race_predictions, cycling, swim):
    """Ist-Werte je Ziel-Typ, aus denselben Rohdaten wie die übrigen Kontext-Blöcke - keine
    eigene GOAL_METRIC_SOURCES-Abfrage nötig (siehe Moduldocstring)."""
    values = {
        "run_threshold_pace": thresholds.get("run_threshold_pace_sec_per_km"),
        "ftp_w_per_kg": thresholds.get("ftp_power_to_weight"),
        "swim_pace_100m": swim.get("pace_sec_per_100m"),
    }
    time_marathon = race_predictions.get("time_marathon")
    values["marathon_pace"] = time_marathon / 42.195 if time_marathon else None
    time_hm = race_predictions.get("time_half_marathon")
    values["halbmarathon_pace"] = time_hm / 21.0975 if time_hm else None
    return values


def _goals_block(target_date, current_values):
    goals = performance_goals.list_performance_goals()
    if not goals:
        return "Leistungsziele: keine hinterlegt."

    lines = []
    for g in goals:
        unit_kind = GOAL_UNIT_KIND.get(g["key"])
        current = current_values.get(g["key"])
        current_text = _format_goal_value(current, unit_kind) or "kein aktueller Messwert"
        target_text = _format_goal_value(g["target_value"], unit_kind) or f"{g['target_value']} {g['unit']}"
        days_left_text = ""
        if g.get("target_date"):
            days_left = (date.fromisoformat(g["target_date"]) - date.fromisoformat(target_date)).days
            days_left_text = f", Zieldatum {g['target_date']} ({days_left} Tage verbleibend)"
        lines.append(f"- {g['label']}: aktuell {current_text}, Ziel {target_text}{days_left_text}.")
    return "Leistungsziele:\n" + "\n".join(lines)


def gather_performance_snapshot(target_date):
    """Leistungsziele (Ziel- vs. aktueller Wert) + Leistungsdiagnostik-Schwellenwerte +
    Wettkampf-Prognosen (Lauf/Rad) + Schwimm-Diagnostik als ein Text-Block, dieselben Zahlen wie
    die Leistung-Seite. target_date bestimmt nur die "Tage verbleibend"-Berechnung bei Zielen mit
    Zieldatum - die zugrundeliegenden Garmin-Messwerte sind immer der jeweils neueste verfügbare
    Stand (kontostandsweite Werte, kein bestimmtes Datum, siehe backend/routers/performance.py)."""
    conn = get_connection()
    try:
        thresholds = _thresholds(conn)
        race_predictions = _race_predictions(conn)
        cycling = _cycling_prediction(conn)
        swim = _swim_diagnostics(conn)
        current_values = _current_goal_values(thresholds, race_predictions, cycling, swim)
        goals_text = _goals_block(target_date, current_values)
    finally:
        conn.close()

    return "\n".join([
        goals_text,
        _thresholds_block(thresholds),
        _race_predictions_block(race_predictions),
        _cycling_prediction_block(cycling),
        _swim_diagnostics_block(swim),
    ])
