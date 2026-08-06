"""
Backend-Endpoints für die "Leistung"-Seite (Trainingsdiagnostik-KPIs, siehe
PROJECT_OVERVIEW.md): tägliche Bereitschaft & HRV-Status, wöchentliche Belastungssteuerung
(Trainingszustand/akute Last/Belastungsfokus, aus bisher nur als Roh-JSON gespeicherten Feldern
geparst - siehe garmin_service.py::_fetch_advanced_health) sowie Leistungsdiagnostik-Schwellenwerte
plus die manuell gepflegten Leistungsziele zum Vergleich.

Ground-Truth-Fund (kanonische VO2max-Quelle): garmin_training_status.most_recent_vo2max* bleibt in
der Garmin-API-Antwort oft tagelang unverändert/stale stehen (verifiziert: eingefroren auf einen
Wert über mehrere Tage, inkl. eines verdächtig identischen Laufen/Rad-Werts), während
garmin_max_metrics deutlich aktueller synchronisiert wird - garmin_max_metrics ist hier deshalb
die kanonische Quelle, most_recent_vo2max* wird für diese Seite bewusst NICHT verwendet.

Ground-Truth-Fund (Belastungsfokus-Verteilung): metricsTrainingLoadBalanceDTOMap war für dieses
Konto in JEDEM bisher synchronisierten Tag null - die Verteilung ist deshalb in der Praxis meist
nicht vorhanden; die Felder bleiben dann konsequent None statt etwas zu erfinden, das Frontend
zeigt in diesem Fall "keine Daten" statt Balken.
"""
from datetime import datetime, timedelta
from typing import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_connection
import performance_goals

router = APIRouter(prefix="/api/performance", tags=["performance"])


def _validate_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum muss im Format YYYY-MM-DD sein.")


# --- Block 1: Tägliche Bereitschaft & Regeneration ---

class HrvTrendPoint(BaseModel):
    date: str
    avg_hrv: float | None = None
    resting_hr: int | None = None
    # Summe von garmin_activities.activity_training_load für diesen Tag (echter Ist-Wert, kein
    # Rolling-Fenster wie daily_summary.training_load_7d/28d) - None statt 0, falls an diesem Tag
    # keine Aktivität erfasst ist (Unterscheidung "kein Training" vs. "keine Daten").
    training_load: float | None = None


class ReadinessOverviewResponse(BaseModel):
    date: str
    score: int | None = None
    level: str | None = None
    feedback_short: str | None = None
    avg_hrv: float | None = None
    # Garmins eigene Einordnung ("BALANCED"/"UNBALANCED"/"LOW", "NONE" während der Onboarding-Phase
    # des Geräts) - roh durchgereicht, keine erfundene Übersetzung.
    hrv_status: str | None = None
    hrv_last_night_avg: int | None = None
    hrv_baseline_balanced_low: int | None = None
    hrv_baseline_balanced_upper: int | None = None
    resting_hr: int | None = None
    # Ground-Truth-Fund: Garmin liefert für den Ruhepuls KEINEN eigenen Status-Enum wie
    # hrv_status - nur die Zahl + einen 7-Tage-Schnitt (garmin_heart_rate_summary.
    # last_7d_avg_resting_hr). Das Frontend leitet daraus selbst eine Einordnung ab (im Schnitt/
    # erhöht/niedrig) statt einen nicht-existenten Garmin-Status vorzutäuschen.
    resting_hr_7d_avg: int | None = None
    hrv_trend: list[HrvTrendPoint]


@router.get("/readiness-overview/{date_str}", response_model=ReadinessOverviewResponse)
def get_readiness_overview(date_str: str) -> ReadinessOverviewResponse:
    d = _validate_date(date_str)
    conn = get_connection()

    readiness = conn.execute(
        "SELECT score, level, feedback_short FROM garmin_training_readiness WHERE date = ?",
        (date_str,)
    ).fetchone()
    daily = conn.execute(
        "SELECT avg_hrv, hrv_status, hrv_last_night_avg, hrv_baseline_balanced_low, "
        "hrv_baseline_balanced_upper, resting_hr FROM garmin_daily WHERE date = ?",
        (date_str,)
    ).fetchone()
    heart_rate_summary = conn.execute(
        "SELECT last_7d_avg_resting_hr FROM garmin_heart_rate_summary WHERE date = ?",
        (date_str,)
    ).fetchone()

    # 28-Tage-Bilanz (HRV/Ruhepuls/Trainings-Load kombiniert, siehe PerformanceView.tsx).
    trend_start = (d - timedelta(days=27)).isoformat()
    trend_rows = conn.execute(
        "SELECT gd.date, gd.avg_hrv, gd.resting_hr, "
        "(SELECT SUM(ga.activity_training_load) FROM garmin_activities ga "
        " WHERE date(ga.start_time_local) = gd.date) AS training_load "
        "FROM garmin_daily gd WHERE gd.date >= ? AND gd.date <= ? ORDER BY gd.date ASC",
        (trend_start, date_str)
    ).fetchall()
    conn.close()

    return ReadinessOverviewResponse(
        date=date_str,
        score=readiness["score"] if readiness else None,
        level=readiness["level"] if readiness else None,
        feedback_short=readiness["feedback_short"] if readiness else None,
        avg_hrv=daily["avg_hrv"] if daily else None,
        hrv_status=daily["hrv_status"] if daily else None,
        hrv_last_night_avg=daily["hrv_last_night_avg"] if daily else None,
        hrv_baseline_balanced_low=daily["hrv_baseline_balanced_low"] if daily else None,
        hrv_baseline_balanced_upper=daily["hrv_baseline_balanced_upper"] if daily else None,
        resting_hr=daily["resting_hr"] if daily else None,
        resting_hr_7d_avg=heart_rate_summary["last_7d_avg_resting_hr"] if heart_rate_summary else None,
        hrv_trend=[HrvTrendPoint(**dict(r)) for r in trend_rows],
    )


# --- Block 2: Wochen-Steuerung & Belastung ---

class LoadStatusResponse(BaseModel):
    # data_date: das Datum, dessen Wert tatsächlich angezeigt wird - training_status wird nicht an
    # jedem Sync-Tag neu geliefert (siehe Moduldocstring), deshalb Fallback auf die letzte
    # vorhandene Zeile bis einschließlich date_str statt an den meisten Tagen leer zu bleiben.
    data_date: str | None = None
    training_status_label: str | None = None
    acute_training_load: float | None = None
    chronic_training_load: float | None = None
    chronic_load_min: float | None = None
    chronic_load_max: float | None = None
    acwr_status: str | None = None
    acwr_ratio: float | None = None
    load_focus_anaerobic_pct: float | None = None
    load_focus_high_aerobic_pct: float | None = None
    load_focus_low_aerobic_pct: float | None = None


@router.get("/load-status/{date_str}", response_model=LoadStatusResponse)
def get_load_status(date_str: str) -> LoadStatusResponse:
    _validate_date(date_str)
    conn = get_connection()
    row = conn.execute(
        "SELECT date, training_status_label, acute_training_load, chronic_training_load, "
        "chronic_load_min, chronic_load_max, acwr_status, acwr_ratio, load_focus_anaerobic_pct, "
        "load_focus_high_aerobic_pct, load_focus_low_aerobic_pct FROM garmin_training_status "
        "WHERE date <= ? AND training_status_label IS NOT NULL ORDER BY date DESC LIMIT 1",
        (date_str,)
    ).fetchone()
    conn.close()
    if not row:
        return LoadStatusResponse()
    data = dict(row)
    data["data_date"] = data.pop("date")
    return LoadStatusResponse(**data)


# --- Block 3: Leistungsdiagnostik & Schwellenwerte (kontostandsweite "aktuelle" Werte, kein
# bestimmtes Datum - siehe Ground-Truth-Fund: nur an Sync-Tagen für "heute" neu abgerufen) ---

class ThresholdsResponse(BaseModel):
    run_threshold_pace_sec_per_km: float | None = None
    run_threshold_hr: int | None = None
    run_threshold_date: str | None = None
    cycling_threshold_hr: int | None = None
    ftp_watts: int | None = None
    ftp_power_to_weight: float | None = None
    ftp_date: str | None = None
    vo2max_running: float | None = None
    vo2max_running_date: str | None = None
    vo2max_cycling: float | None = None
    vo2max_cycling_date: str | None = None


@router.get("/thresholds", response_model=ThresholdsResponse)
def get_thresholds() -> ThresholdsResponse:
    conn = get_connection()

    lactate = conn.execute(
        "SELECT date, speed, heart_rate, heart_rate_cycling FROM garmin_lactate_threshold "
        "WHERE speed IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    ftp = conn.execute(
        "SELECT date, functional_threshold_power, power_to_weight FROM garmin_cycling_ftp "
        "WHERE functional_threshold_power IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    # vo2max_running/vo2max_cycling synchronisieren unabhängig voneinander (siehe Moduldocstring) -
    # deshalb für jede Sportart einzeln die jeweils neueste nicht-null Zeile suchen, statt eine
    # einzelne Zeile mit beiden Werten zu verlangen.
    vo2max_run = conn.execute(
        "SELECT date, vo2max_running FROM garmin_max_metrics WHERE vo2max_running IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    vo2max_cycle = conn.execute(
        "SELECT date, vo2max_cycling FROM garmin_max_metrics WHERE vo2max_cycling IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()

    # Garmins "speed" ist bereits die korrigierte m/s-Geschwindigkeit (siehe garmin_service.py-
    # Kommentar zur *10-Korrektur) - Pace in Sekunden/km für einheitliche Frontend-Formatierung.
    run_pace_sec_per_km = (1000.0 / lactate["speed"]) if lactate and lactate["speed"] else None

    return ThresholdsResponse(
        run_threshold_pace_sec_per_km=run_pace_sec_per_km,
        run_threshold_hr=lactate["heart_rate"] if lactate else None,
        run_threshold_date=lactate["date"] if lactate else None,
        cycling_threshold_hr=lactate["heart_rate_cycling"] if lactate else None,
        ftp_watts=ftp["functional_threshold_power"] if ftp else None,
        ftp_power_to_weight=ftp["power_to_weight"] if ftp else None,
        ftp_date=ftp["date"] if ftp else None,
        vo2max_running=vo2max_run["vo2max_running"] if vo2max_run else None,
        vo2max_running_date=vo2max_run["date"] if vo2max_run else None,
        vo2max_cycling=vo2max_cycle["vo2max_cycling"] if vo2max_cycle else None,
        vo2max_cycling_date=vo2max_cycle["date"] if vo2max_cycle else None,
    )


# --- Block 3b: Wettkampf-Prognosen & Schwimm-Diagnostik ---

class RacePredictionsResponse(BaseModel):
    date: str | None = None
    time_5k: int | None = None
    time_10k: int | None = None
    time_half_marathon: int | None = None
    time_marathon: int | None = None


@router.get("/race-predictions", response_model=RacePredictionsResponse)
def get_race_predictions() -> RacePredictionsResponse:
    conn = get_connection()
    row = conn.execute(
        "SELECT date, time_5k, time_10k, time_half_marathon, time_marathon FROM garmin_race_predictions "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return RacePredictionsResponse(**dict(row)) if row else RacePredictionsResponse()


# Zielstrecken/Intensitäten für die Rad-Wettkampf-Schätzung - bewusst nur zwei grobe Szenarien
# (kein Garmin-Rad-Pendant zum Lauf-Race-Predictor, siehe Moduldocstring-Ergänzung unten).
CYCLING_PREDICTION_SCENARIOS = [
    {"key": "sprint", "label": "Sprint", "distance_km": 20.0, "pct_ftp": 0.95},
    {"key": "olympic", "label": "Olympisch", "distance_km": 40.0, "pct_ftp": 0.88},
]


class CyclingPredictionScenario(BaseModel):
    key: str
    label: str
    distance_km: float
    target_power_watts: float | None = None
    estimated_speed_kmh: float | None = None
    estimated_duration_seconds: float | None = None


class CyclingPredictionResponse(BaseModel):
    # sample_size ist die Datenbasis-Transparenz - je mehr Fahrten, desto belastbarer der
    # Wirkungsgrad (siehe get_cycling_prediction-Docstring). 0 = keine Schätzung möglich.
    sample_size: int = 0
    efficiency_kmh_per_watt: float | None = None
    scenarios: list[CyclingPredictionScenario] = []


#  m Höhenmeter pro km, ab dem eine Fahrt als "hügelig" gilt und aus dem Wirkungsgrad-Schnitt
# ausgeschlossen wird - gleiche Watt ergeben bergauf deutlich weniger km/h als auf der Ebene, das
# würde den Wirkungsgrad sonst verfälschen. 10 m/km ist ein gängiger Richtwert für "flaches
# Terrain" im Radsport - ground-truth an den eigenen Aktivitäten geprüft (aktuell 8 Fahrten:
# 6 klar darunter (1-4 m/km), 2 klar darüber (12-13 m/km), keine Grenzfälle).
CYCLING_FLAT_ELEVATION_GAIN_PER_KM = 10.0


@router.get("/cycling-prediction", response_model=CyclingPredictionResponse)
def get_cycling_prediction() -> CyclingPredictionResponse:
    """Rad hat kein Garmin-Pendant zum Lauf-Race-Predictor - Schätzung stattdessen aus einem
    persönlichen Wirkungsgrad (km/h pro Watt), gemittelt über die eigenen Rad-Aktivitäten mit
    Leistungs- und Geschwindigkeitsdaten UND flachem Profil (siehe CYCLING_FLAT_ELEVATION_GAIN_PER_KM
    - hügelige Fahrten würden den Wirkungsgrad sonst verzerren, da gleiche Watt bergauf weniger
    km/h ergeben). Bewusst EIN Schnitt über alle passenden Fahrten statt zusätzlich nach Intensität
    gebündelt - die Datenbasis reicht (Stand jetzt: einstellige Fahrtenzahl) für eine verlässliche
    Bucket-Aufteilung nicht; wird mit mehr Fahrten automatisch repräsentativer (sample_size zeigt
    das transparent an). Wind/Aerodynamik sind weiterhin nicht rausgerechnet - das bleibt eine
    grobe Tendenz, keine physikalische Modellierung.
    """
    conn = get_connection()
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
    conn.close()

    sample_size = len(rows)
    if sample_size == 0:
        return CyclingPredictionResponse(sample_size=0)

    efficiency_values = [(r["average_speed"] * 3.6) / r["avg_power"] for r in rows]
    efficiency = sum(efficiency_values) / len(efficiency_values)
    ftp_watts = ftp_row["functional_threshold_power"] if ftp_row else None

    scenarios = []
    for s in CYCLING_PREDICTION_SCENARIOS:
        target_power = ftp_watts * s["pct_ftp"] if ftp_watts else None
        speed_kmh = efficiency * target_power if target_power else None
        duration = (s["distance_km"] / speed_kmh) * 3600 if speed_kmh else None
        scenarios.append(CyclingPredictionScenario(
            key=s["key"], label=s["label"], distance_km=s["distance_km"],
            target_power_watts=target_power, estimated_speed_kmh=speed_kmh, estimated_duration_seconds=duration,
        ))

    return CyclingPredictionResponse(sample_size=sample_size, efficiency_kmh_per_watt=efficiency, scenarios=scenarios)


class SwimDiagnosticsResponse(BaseModel):
    date: str | None = None
    swolf: float | None = None
    pace_sec_per_100m: float | None = None


@router.get("/swim-diagnostics", response_model=SwimDiagnosticsResponse)
def get_swim_diagnostics() -> SwimDiagnosticsResponse:
    # averageSwolf steckt nur im raw_json (keine eigene Spalte, siehe garmin_activities-Schema in
    # db.py) - json_extract statt einer neuen Sync-Spalte+Backfill, da SQLites JSON1-Extension
    # bereits verfügbar ist (verifiziert) und raw_json ohnehin für jede Aktivität gespeichert wird.
    conn = get_connection()
    row = conn.execute(
        "SELECT date(start_time_local) AS date, average_speed, "
        "json_extract(raw_json, '$.averageSwolf') AS swolf FROM garmin_activities "
        "WHERE activity_type = 'lap_swimming' AND average_speed IS NOT NULL "
        "ORDER BY start_time_local DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return SwimDiagnosticsResponse()
    pace = (100.0 / row["average_speed"]) if row["average_speed"] else None
    return SwimDiagnosticsResponse(date=row["date"], swolf=row["swolf"], pace_sec_per_100m=pace)


# --- Leistungsziele (Teil C) - einfache CRUD-API, analog zu backend/routers/club_slots.py ---

class PerformanceGoalIn(BaseModel):
    key: str
    label: str
    target_value: float
    unit: str
    derived_from_race_goal_id: int | None = None
    notes: str | None = None
    target_date: str | None = None
    start_date: str | None = None


class PerformanceGoalResponse(PerformanceGoalIn):
    updated_at: str
    # current_value/start_value sind abgeleitet (nicht in der Tabelle gespeichert - siehe
    # _metric_value) und deshalb bei jedem GET frisch berechnet statt beim Anlegen eingefroren.
    current_value: float | None = None
    current_value_date: str | None = None
    start_value: float | None = None
    # Datum des tatsächlich verwendeten Startwerts - entspricht start_date, wenn gesetzt, sonst der
    # frühesten verfügbaren Messung (siehe _enrich_goal). Bewusst getrennt von start_date gehalten,
    # damit ein impliziter Start nicht beim nächsten Speichern versehentlich als "manuell gesetzt"
    # persistiert wird (start_date selbst bleibt dabei unverändert null).
    start_value_date: str | None = None


# Ziel-Typen mit einem echten, laufend synchronisierten Garmin-Ist-Wert (dieselben Quellen wie im
# Thresholds-Block oben bzw. garmin_race_predictions, siehe garmin_service.py) - ermöglicht einen
# Start-/Ist-Wert-Vergleich für die Progressbar auf der Leistungsseite, ohne einen Wert zu
# erfinden. swim_pace_100m ist bewusst NICHT hier drin (andere Tabellenform, kein date-PK - siehe
# _swim_pace_value), wird in _metric_value separat behandelt.
GOAL_METRIC_SOURCES: dict[str, tuple[str, str, Callable[[float], float | None]]] = {
    "run_threshold_pace": ("garmin_lactate_threshold", "speed", lambda v: 1000.0 / v if v else None),
    "ftp_w_per_kg": ("garmin_cycling_ftp", "power_to_weight", lambda v: v),
    # Garmins Renn-Vorhersage liefert Finish-Zeiten in Sekunden, keine Pace - Distanzen sind die
    # offiziellen Wettkampf-Distanzen (42,195 km / 21,0975 km).
    "marathon_pace": ("garmin_race_predictions", "time_marathon", lambda v: v / 42.195 if v else None),
    "halbmarathon_pace": ("garmin_race_predictions", "time_half_marathon", lambda v: v / 21.0975 if v else None),
}


def _swim_pace_value(conn, before_date=None):
    """Ist-Wert für swim_pace_100m: Pace der letzten Bahnschwimmen-Aktivität (garmin_activities.
    activity_type = 'lap_swimming', ground-truth-verifiziert) bis einschließlich before_date. Kein
    date-PK-Zeitreihen-Table wie GOAL_METRIC_SOURCES (mehrere/keine Aktivitäten pro Tag), deshalb
    eigene Abfrage statt Eintrag im generischen Dict. Fällt wie _metric_value auf die allererste
    vorhandene Aktivität zurück, falls before_date vor jeder Schwimm-Historie liegt."""
    query = (
        "SELECT date(start_time_local) AS date, average_speed FROM garmin_activities "
        "WHERE activity_type = 'lap_swimming' AND average_speed IS NOT NULL"
    )
    params: list = []
    if before_date:
        query += " AND date(start_time_local) <= ?"
        params.append(before_date)
    query += " ORDER BY start_time_local DESC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    if not row and before_date:
        row = conn.execute(
            "SELECT date(start_time_local) AS date, average_speed FROM garmin_activities "
            "WHERE activity_type = 'lap_swimming' AND average_speed IS NOT NULL "
            "ORDER BY start_time_local ASC LIMIT 1"
        ).fetchone()
    if not row:
        return None, None
    pace = (100.0 / row["average_speed"]) if row["average_speed"] else None
    return pace, row["date"]


def _metric_value(conn, key, before_date=None):
    """Ist-Wert für einen Ziel-Typ: neuester Wert bis einschließlich before_date (None = neuester
    überhaupt). Fällt für ein before_date vor der ersten vorhandenen Messung auf die allererste
    vorhandene Messung zurück, statt für frühe Startdaten ganz leer zu bleiben."""
    if key == "swim_pace_100m":
        return _swim_pace_value(conn, before_date)
    source = GOAL_METRIC_SOURCES.get(key)
    if not source:
        return None, None
    table, column, transform = source
    if before_date:
        row = conn.execute(
            f"SELECT date, {column} AS v FROM {table} WHERE date <= ? AND {column} IS NOT NULL "
            f"ORDER BY date DESC LIMIT 1",
            (before_date,)
        ).fetchone()
        if not row:
            row = conn.execute(
                f"SELECT date, {column} AS v FROM {table} WHERE {column} IS NOT NULL ORDER BY date ASC LIMIT 1"
            ).fetchone()
    else:
        row = conn.execute(
            f"SELECT date, {column} AS v FROM {table} WHERE {column} IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None, None
    return transform(row["v"]), row["date"]


def _enrich_goal(conn, goal: dict) -> PerformanceGoalResponse:
    current_value, current_value_date = _metric_value(conn, goal["key"])
    # Ohne explizit gesetztes start_date trotzdem einen Fortschrittsbalken zeigen - impliziter Start
    # ist dann die früheste verfügbare Messung (Sentinel-Datum weit in der Vergangenheit löst genau
    # den bestehenden "vor der ersten Messung -> nimm die ganz erste" Fallback in _metric_value/
    # _swim_pace_value aus). start_date selbst bleibt unverändert - siehe start_value_date-Kommentar.
    start_value, start_value_date = _metric_value(
        conn, goal["key"], before_date=goal.get("start_date") or "0001-01-01"
    )
    return PerformanceGoalResponse(
        **goal, current_value=current_value, current_value_date=current_value_date,
        start_value=start_value, start_value_date=start_value_date,
    )


@router.get("/goals", response_model=list[PerformanceGoalResponse])
def list_performance_goals() -> list[PerformanceGoalResponse]:
    conn = get_connection()
    try:
        return [_enrich_goal(conn, goal) for goal in performance_goals.list_performance_goals()]
    finally:
        conn.close()


@router.put("/goals/{key}", response_model=PerformanceGoalResponse)
def upsert_performance_goal(key: str, body: PerformanceGoalIn) -> PerformanceGoalResponse:
    if body.key != key:
        raise HTTPException(status_code=400, detail="key im Pfad und im Body müssen übereinstimmen.")
    saved = performance_goals.upsert_performance_goal(
        key=body.key, label=body.label, target_value=body.target_value, unit=body.unit,
        derived_from_race_goal_id=body.derived_from_race_goal_id, notes=body.notes,
        target_date=body.target_date, start_date=body.start_date,
    )
    conn = get_connection()
    try:
        return _enrich_goal(conn, saved)
    finally:
        conn.close()


@router.delete("/goals/{key}")
def delete_performance_goal(key: str) -> dict:
    performance_goals.delete_performance_goal(key)
    return {"success": True}
