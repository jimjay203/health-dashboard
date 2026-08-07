"""
Backend-Endpoints für die "Körper"-Seite: Körperzusammensetzung (Withings), What-if-Simulator
(Zielgewicht -> Rad-W/kg/relativer Lauf-VO2max/Renn-Zeit-Prognose), Körper-Einstellungen
(Größe/Zielgewicht) und das Schmerz-/Verletzungsprotokoll. Dünner Wrapper um body_composition.py/
injury_log.py, gleiches Muster wie backend/routers/sleep.py.
"""
from datetime import date, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import body_composition
import injury_log
from body_trend_insight import generate_trend_insight, get_cached_trend_insight

router = APIRouter(prefix="/api/body", tags=["body"])

BODY_TREND_MAX_DAYS = body_composition.BODY_TREND_MAX_DAYS


def _validate_date(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum muss im Format YYYY-MM-DD sein.")


# --- Übersicht ---

class BodyOverviewResponse(BaseModel):
    measured_date: str | None = None
    weight_kg: float | None = None
    weight_trend_7d_kg: float | None = None
    body_fat_pct: float | None = None
    body_water_kg: float | None = None
    body_water_pct: float | None = None
    hydration_status: str | None = None
    bone_mass_kg: float | None = None
    muscle_mass_kg: float | None = None
    fat_mass_kg: float | None = None
    fat_free_mass_kg: float | None = None
    ffmi: float | None = None
    ffmi_classification: str | None = None
    muscle_fat_ratio: float | None = None
    bmr_kcal: float | None = None
    height_cm: float | None = None
    target_weight_kg: float | None = None
    target_body_fat_pct: float | None = None
    weight_vs_avg_pct: float | None = None
    days_until_next_race: int | None = None
    running_power_to_weight: float | None = None
    cycling_power_to_weight: float | None = None
    running_ftp_watts: float | None = None
    cycling_ftp_watts: float | None = None
    vo2max_running: float | None = None
    vo2max_cycling: float | None = None


@router.get("/overview", response_model=BodyOverviewResponse)
def get_body_overview() -> BodyOverviewResponse:
    return BodyOverviewResponse(**body_composition.get_body_overview())


# --- Trend ---

class BodyTrendPoint(BaseModel):
    date: str
    weight_kg: float | None = None
    weight_rolling_avg_kg: float | None = None
    body_fat_pct: float | None = None
    body_water_kg: float | None = None
    bone_mass_kg: float | None = None
    muscle_mass_kg: float | None = None
    fat_mass_kg: float | None = None


class MuscleSorenessPoint(BaseModel):
    date: str
    muscle_soreness: int


class TrainingLoadPoint(BaseModel):
    date: str
    training_load: float | None = None


class BodyTrendResponse(BaseModel):
    points: list[BodyTrendPoint] = []
    muscle_soreness_points: list[MuscleSorenessPoint] = []
    training_load_points: list[TrainingLoadPoint] = []


@router.get("/trend", response_model=BodyTrendResponse)
def get_body_trend(days: int = 90) -> BodyTrendResponse:
    days = min(days, BODY_TREND_MAX_DAYS)
    return BodyTrendResponse(**body_composition.get_body_trend(days))


# --- Gemini-Einordnung des 90-Tage-Trends (siehe body_trend_insight.py) ---

class TrendInsightResponse(BaseModel):
    date: str
    insight_text: str
    generated_at: str


@router.get("/trend-insight", response_model=TrendInsightResponse)
def get_trend_insight() -> TrendInsightResponse:
    """Cache-dann-lazy-generieren, gleiches Muster wie backend/routers/sleep.py."""
    today = date.today().isoformat()
    cached = get_cached_trend_insight(today)
    if cached:
        return TrendInsightResponse(**cached)
    try:
        points = body_composition.get_body_trend(90)["points"]
        fresh = generate_trend_insight(today, points)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Einordnung konnte nicht generiert werden: {e}")
    return TrendInsightResponse(**fresh)


# --- What-if-Simulator ---

class RaceTimeProjectionEntry(BaseModel):
    current_seconds: int
    target_seconds: int


class WhatIfResponse(BaseModel):
    current_weight_kg: float | None = None
    target_weight_kg: float
    cycling_ftp_watts: float | None = None
    cycling_power_to_weight_current: float | None = None
    cycling_power_to_weight_target: float | None = None
    vo2max_running_current: float | None = None
    vo2max_running_target: float | None = None
    race_time_projection: dict[str, RaceTimeProjectionEntry] | None = None


@router.get("/what-if", response_model=WhatIfResponse)
def get_what_if(target_weight_kg: float) -> WhatIfResponse:
    if target_weight_kg <= 0:
        raise HTTPException(status_code=400, detail="Zielgewicht muss größer als 0 sein.")
    return WhatIfResponse(**body_composition.compute_what_if(target_weight_kg))


# --- Körper-Einstellungen (Größe/Zielgewicht) ---

class BodySettingsResponse(BaseModel):
    height_cm: float | None = None
    height_source: str | None = None
    target_weight_kg: float | None = None
    target_body_fat_pct: float | None = None


class BodySettingsUpdate(BaseModel):
    height_cm: float | None = None
    target_weight_kg: float | None = None
    target_body_fat_pct: float | None = None
    reset_height_to_garmin: bool = False


@router.get("/settings", response_model=BodySettingsResponse)
def get_body_settings() -> BodySettingsResponse:
    return BodySettingsResponse(**body_composition.get_body_settings())


@router.put("/settings", response_model=BodySettingsResponse)
def put_body_settings(body: BodySettingsUpdate) -> BodySettingsResponse:
    if body.reset_height_to_garmin:
        body_composition.reset_height_to_garmin()
    elif body.height_cm is not None:
        body_composition.save_body_setting("height_cm", body.height_cm, source="manual")
    if body.target_weight_kg is not None:
        body_composition.save_body_setting("target_weight_kg", body.target_weight_kg)
    if body.target_body_fat_pct is not None:
        body_composition.save_body_setting("target_body_fat_pct", body.target_body_fat_pct)
    return BodySettingsResponse(**body_composition.get_body_settings())


# --- Schmerz-/Verletzungsprotokoll ---

class InjuryResponse(BaseModel):
    id: int
    date: str
    body_part: str
    severity: int
    pain_type: str | None = None
    context: str | None = None
    notes: str | None = None
    resolved_at: str | None = None
    created_at: str


class InjuryIn(BaseModel):
    date: str
    body_part: str
    severity: int
    pain_type: str | None = None
    context: str | None = None
    notes: str | None = None


class InjuryUpdate(BaseModel):
    body_part: str | None = None
    severity: int | None = None
    pain_type: str | None = None
    context: str | None = None
    notes: str | None = None
    resolved: bool | None = None


@router.get("/injuries", response_model=list[InjuryResponse])
def list_injuries(active_only: bool = False) -> list[InjuryResponse]:
    return [InjuryResponse(**row) for row in injury_log.list_injuries(active_only=active_only)]


@router.post("/injuries", response_model=InjuryResponse)
def create_injury(body: InjuryIn) -> InjuryResponse:
    _validate_date(body.date)
    if not (1 <= body.severity <= 10):
        raise HTTPException(status_code=400, detail="Schmerz-Skala muss zwischen 1 und 10 liegen.")
    row = injury_log.create_injury(
        body.date, body.body_part, body.severity, body.pain_type, body.context, body.notes
    )
    return InjuryResponse(**row)


@router.put("/injuries/{injury_id}", response_model=InjuryResponse)
def update_injury(injury_id: int, body: InjuryUpdate) -> InjuryResponse:
    if body.severity is not None and not (1 <= body.severity <= 10):
        raise HTTPException(status_code=400, detail="Schmerz-Skala muss zwischen 1 und 10 liegen.")
    row = injury_log.update_injury(
        injury_id, body.body_part, body.severity, body.pain_type, body.context, body.notes, body.resolved
    )
    if not row:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")
    return InjuryResponse(**row)


@router.delete("/injuries/{injury_id}")
def delete_injury(injury_id: int) -> dict:
    injury_log.delete_injury(injury_id)
    return {"success": True}
