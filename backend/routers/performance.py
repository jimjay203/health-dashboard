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


# --- Leistungsziele (Teil C) - einfache CRUD-API, analog zu backend/routers/club_slots.py ---

class PerformanceGoalIn(BaseModel):
    key: str
    label: str
    target_value: float
    unit: str
    derived_from_race_goal_id: int | None = None
    notes: str | None = None


class PerformanceGoalResponse(PerformanceGoalIn):
    updated_at: str


@router.get("/goals", response_model=list[PerformanceGoalResponse])
def list_performance_goals() -> list[PerformanceGoalResponse]:
    return [PerformanceGoalResponse(**goal) for goal in performance_goals.list_performance_goals()]


@router.put("/goals/{key}", response_model=PerformanceGoalResponse)
def upsert_performance_goal(key: str, body: PerformanceGoalIn) -> PerformanceGoalResponse:
    if body.key != key:
        raise HTTPException(status_code=400, detail="key im Pfad und im Body müssen übereinstimmen.")
    saved = performance_goals.upsert_performance_goal(
        key=body.key, label=body.label, target_value=body.target_value, unit=body.unit,
        derived_from_race_goal_id=body.derived_from_race_goal_id, notes=body.notes,
    )
    return PerformanceGoalResponse(**saved)


@router.delete("/goals/{key}")
def delete_performance_goal(key: str) -> dict:
    performance_goals.delete_performance_goal(key)
    return {"success": True}
