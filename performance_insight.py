"""
Gemini-Einschätzung zu den Leistungszielen auf der "Leistung"-Seite (PerformanceView.tsx):
Erreichbarkeit der hinterlegten Ziele + konkrete Tipps, auf Basis derselben Kennzahlen, die die
Seite selbst zeigt (Ziele, Trainingszustand/CTL-ATL-TSB, Belastungsfokus, Schwellenwerte,
Wettkampf-Prognosen, Rad-Wirkungsgrad, Schwimm-Diagnostik) sowie des geteilten Erkenntnis-
Gedächtnisses (context_blocks.py::insight_memory_block, siehe insight_memory.py) - dort trägt der
Athlet Dinge ein, die sich nicht aus den Daten ablesen lassen (Datenlücken, Korrekturen an
ungenauen Garmin-Schätzungen, Bestzeiten). Reine Python-Logik, kein Streamlit-/
FastAPI-Import (gleiches Muster wie body_trend_insight.py). Kontext-Werte werden bewusst über
eigene, schlanke SQL-Abfragen direkt ermittelt statt aus backend/routers/performance.py importiert
- der Router lebt nur innerhalb der Docker-Flattening-Struktur (siehe backend/Dockerfile), dieses
Modul soll wie alle anderen *_insight.py-Module unabhängig davon lauffähig/testbar bleiben. Cache
pro Tag (wie body_trend_insight.py) - zusätzlich invalidiert bei jeder Ziel-Änderung (siehe
invalidate_today_cache(), aufgerufen aus backend/routers/performance.py bei PUT/DELETE /goals),
da die Einschätzung sonst bis zum nächsten Tag auf einem veralteten Ziel-Stand stehen bliebe.
"""
import json
from datetime import date, datetime, timedelta

from google.genai import types
from db import get_connection, upsert_daily_metric
from gemini_client import MODEL_NAME, get_client
from context_blocks import strip_markdown_fences, insight_memory_block
from load_focus import compute_load_focus, LOAD_FOCUS_WINDOW_DAYS
import performance_goals

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"insight_text": {"type": "STRING"}},
    "required": ["insight_text"],
}

SYSTEM_PROMPT = """
Du bist Trainingscoach für einen Marathon-/Triathlon-Athleten und schätzt seine hinterlegten
Leistungsziele ein: wie erreichbar sind sie (insbesondere falls ein Zieldatum gesetzt ist), und was
sollte er konkret tun, um dahin zu kommen?

Du bekommst bereits BERECHNETE Kennzahlen: die Ziele selbst (Ziel- vs. aktueller Wert, Zieldatum),
den aktuellen Trainingszustand (CTL/ATL/TSB, akute vs. chronische Belastung, Trend der letzten 90
Tage), die Belastungsfokus-Verteilung (Anteil niedrig-aerob/hoch-aerob/anaerob der letzten 28 Tage,
mit dem gängigen 80/20-Polarisierungsrichtwert), Leistungsdiagnostik-Schwellenwerte je Disziplin,
Wettkampf-Prognosen sowie einen Block "ZUSATZKONTEXT VOM ATHLETEN" mit vom Athleten selbst
eingetragenen Hintergrundinfos (z.B. Korrekturen an ungenauen Garmin-Schätzungen, Bestzeiten,
Datenlücken) - diese Infos haben Vorrang vor den berechneten Werten, falls sie sich widersprechen
(z.B. eine vom Athleten korrigierte Pace-Schätzung statt der rohen Garmin-Prognose).

WICHTIG: Erfinde oder berechne KEINE eigenen Zahlen - nutze ausschließlich die gegebenen Werte. Bei
fehlenden Daten (kein Ziel gesetzt, kein Zieldatum, keine Diagnostik-Messung) das explizit benennen
statt eine Einschätzung vorzutäuschen. Beachte den CTL-Trend nur für den Zeitraum, für den laut
Zusatzkontext tatsächlich durchgängige Garmin-Daten vorliegen - ein Sprung von 0 davor ist meist nur
ein Datenlücken-Artefakt, keine reale Fitness-Entwicklung.

Gehe wenn möglich auf JEDES hinterlegte Ziel einzeln ein (kurz), ordne dann übergreifend ein, ob der
aktuelle Trainingszustand/Belastungsfokus die Ziele unterstützt oder eher bremst, und schließe mit
2-3 konkreten, auf die Daten gestützten Tipps (z.B. Belastungsfokus verschieben, TSB-Lage beachten,
disziplinspezifisch).

Schreibe 4-7 kurze Sätze/Stichpunkte auf Deutsch.

Gib AUSSCHLIESSLICH valides JSON zurück im Format: {"insight_text": "<Text>"}
"""

# Gleiche 5 Bänder wie backend/routers/performance.py::TSB_BANDS - bewusst hier dupliziert statt
# importiert (siehe Moduldocstring), stabile/kleine Lookup-Tabelle, geringes Drift-Risiko.
TSB_BANDS = [
    (-1e9, -30, "Hohes Ermüdungsrisiko"),
    (-30, -10, "Produktiv"),
    (-10, 5, "Erhaltend"),
    (5, 25, "Frisch"),
    (25, 1e9, "Formverlust-Risiko"),
]

CTL_TREND_WINDOW_DAYS = 90

# Zielstrecken/Intensitäten für die Rad-Wettkampf-Schätzung - identisch zu
# backend/routers/performance.py::CYCLING_PREDICTION_SCENARIOS.
CYCLING_PREDICTION_SCENARIOS = [
    {"key": "sprint", "label": "Sprint", "distance_km": 20.0, "pct_ftp": 0.95},
    {"key": "olympic", "label": "Olympisch", "distance_km": 40.0, "pct_ftp": 0.88},
]
CYCLING_FLAT_ELEVATION_GAIN_PER_KM = 10.0

# Ziel-Typ -> (Label für Prosa, Einheit-Formatierer). Werte selbst kommen NICHT aus einer eigenen
# GOAL_METRIC_SOURCES-Abfrage wie im Router, sondern aus den ohnehin schon für die anderen
# Kontext-Blöcke ermittelten Diagnostik-/Prognose-Werten (siehe _current_goal_values) - dieselben
# Zahlen, die die Seite selbst anzeigt.
GOAL_UNIT_KIND = {
    "run_threshold_pace": "pace_km",
    "marathon_pace": "pace_km",
    "halbmarathon_pace": "pace_km",
    "ftp_w_per_kg": "w_per_kg",
    "swim_pace_100m": "pace_100m",
}


def _classify_tsb(tsb):
    if tsb is None:
        return None
    for low, high, label in TSB_BANDS:
        if low <= tsb < high:
            return label
    return None


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


def _load_status_block(conn, target_date):
    daily = conn.execute(
        "SELECT date, ctl, atl, tsb FROM daily_summary WHERE date <= ? AND tsb IS NOT NULL "
        "ORDER BY date DESC LIMIT 1",
        (target_date,)
    ).fetchone()
    if not daily:
        return "Trainingszustand: keine CTL/ATL/TSB-Daten vorhanden.", (None, None)

    trend_start = (date.fromisoformat(target_date) - timedelta(days=CTL_TREND_WINDOW_DAYS)).isoformat()
    trend_rows = conn.execute(
        "SELECT date, ctl FROM daily_summary WHERE date >= ? AND date <= ? AND ctl IS NOT NULL "
        "ORDER BY date ASC",
        (trend_start, target_date)
    ).fetchall()
    trend_text = ""
    if len(trend_rows) >= 2:
        first, last = trend_rows[0], trend_rows[-1]
        trend_text = (
            f" CTL-Trend {CTL_TREND_WINDOW_DAYS} Tage: {first['date']}={first['ctl']:.1f} -> "
            f"{last['date']}={last['ctl']:.1f} (Δ{last['ctl'] - first['ctl']:+.1f})."
        )

    state_label = _classify_tsb(daily["tsb"])
    text = (
        f"Trainingszustand ({daily['date']}): CTL(Fitness)={daily['ctl']:.1f}, "
        f"ATL(akute Belastung)={daily['atl']:.1f}, TSB(Form)={daily['tsb']:+.1f} "
        f"({state_label})." + trend_text
    )
    return text, (daily["ctl"], daily["tsb"])


def _load_focus_block(target_date):
    """Nutzt load_focus.py (App-eigene Friel-HF-Zonen statt Garmins eigenen hrTimeInZone-Werten,
    siehe dortiger Ground-Truth-Fund vom 2026-08-07) - included_activities/total_activities_in_window
    werden explizit mitgegeben, damit Gemini die Aussagekraft bei geringer Abdeckung einordnen kann."""
    lf = compute_load_focus(target_date, window_days=LOAD_FOCUS_WINDOW_DAYS)
    if lf["low_aerobic_pct"] is None:
        return (
            f"Belastungsfokus (letzte {LOAD_FOCUS_WINDOW_DAYS} Tage): keine auswertbaren "
            "HF-Zeitreihen vorhanden (nur Laufen/Rad mit synchronisierter Detail-Zeitreihe möglich)."
        )
    return (
        f"Belastungsfokus (letzte {LOAD_FOCUS_WINDOW_DAYS} Tage, berechnet aus {lf['included_activities']} von "
        f"{lf['total_activities_in_window']} Aktivitäten im Fenster - nur Laufen/Rad mit synchronisierter "
        f"Detail-Zeitreihe auswertbar): niedrig-aerob(Z1+Z2)={lf['low_aerobic_pct']:.0f}%, "
        f"hoch-aerob(Z3)={lf['high_aerobic_pct']:.0f}%, anaerob(Z4+Z5)={lf['anaerobic_pct']:.0f}% "
        f"(gängiger Polarisierungsrichtwert: niedrig-aerob ≥70%)."
    )


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


def _gather_context(target_date):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        memory_text = insight_memory_block(cursor)
        load_status_text, _ = _load_status_block(conn, target_date)
        load_focus_text = _load_focus_block(target_date)
        thresholds = _thresholds(conn)
        race_predictions = _race_predictions(conn)
        cycling = _cycling_prediction(conn)
        swim = _swim_diagnostics(conn)
        current_values = _current_goal_values(thresholds, race_predictions, cycling, swim)
        goals_text = _goals_block(target_date, current_values)
    finally:
        conn.close()

    return "\n".join([
        f"ZUSATZKONTEXT VOM ATHLETEN: {memory_text}",
        goals_text,
        load_status_text,
        load_focus_text,
        _thresholds_block(thresholds),
        _race_predictions_block(race_predictions),
        _cycling_prediction_block(cycling),
        _swim_diagnostics_block(swim),
    ])


def generate_goals_insight(target_date):
    context = _gather_context(target_date)

    client = get_client()
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=context,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.4,
        ),
    )
    raw = strip_markdown_fences(response.text or "")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        snippet = raw[:500] if raw else "(leere Antwort)"
        raise RuntimeError(f"Gemini-Antwort war kein valides JSON ({e}). Rohtext (Anfang): {snippet}") from e

    insight_text = result["insight_text"]
    generated_at = datetime.now().isoformat()

    upsert_daily_metric("performance_goals_insight", {
        "date": target_date,
        "insight_text": insight_text,
        "generated_at": generated_at,
    })

    return {"date": target_date, "insight_text": insight_text, "generated_at": generated_at}


def get_cached_goals_insight(target_date):
    conn = get_connection()
    row = conn.execute("SELECT * FROM performance_goals_insight WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    if not row:
        return None
    return {"date": row["date"], "insight_text": row["insight_text"], "generated_at": row["generated_at"]}


def invalidate_today_cache():
    """Wird bei jeder Ziel-Änderung (PUT/DELETE /api/performance/goals/{key}) aufgerufen - ohne
    das würde die Einschätzung bis zum nächsten Tages-Cache-Ablauf auf einem veralteten Ziel-Stand
    stehen bleiben."""
    today = date.today().isoformat()
    conn = get_connection()
    conn.execute("DELETE FROM performance_goals_insight WHERE date = ?", (today,))
    conn.commit()
    conn.close()
