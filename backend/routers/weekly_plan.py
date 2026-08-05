"""
Backend-Endpoints für den Rolling-Horizon-Wochenplaner (siehe weekly_planner.py,
PROJECT_OVERVIEW.md "Wochenplaner"-Abschnitt): zwei konkret durchgeplante Wochen (Diese Woche +
Nächste Woche, beide über GET /api/weekly-plan/{date}, inkl. week_id/KW), eine Andeutungs-Ebene
für Woche 3 (GET /api/week-outlook/{date}, keine Workout-Details, kein Gemini-Call) sowie
Workout-Entwurf-Status/-Upload, ein grober Trainingsphasen-/Renn-Countdown-Ausblick (GET
/api/training-outlook) und ab Woche 4 eine Zeile pro Woche bis zum nächsten Rennen (GET
/api/far-weeks-outlook/{date}, leer falls kein Rennen mehr ansteht).
"""
import asyncio
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_connection
from weekly_planner import generate_weekly_plan, get_week_plan, get_week_outlook, get_far_weeks_outlook
from workout_builder import build_interval_running_workout, build_steady_running_workout, upload_workout
from garmin_auth import get_garmin_client

router = APIRouter(prefix="/api", tags=["weekly-plan"])

BUILDER_FUNCTIONS = {
    "build_interval_running_workout": build_interval_running_workout,
    "build_steady_running_workout": build_steady_running_workout,
}


def _validate_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum muss im Format YYYY-MM-DD sein.")


# --- Diese Woche (Fixierungs-Ebene) ---

class WeeklyPlanDay(BaseModel):
    date: str
    week_id: str
    weekday: int
    sport_type: str | None = None
    session_type: str | None = None
    target_zone: str | None = None
    target_duration_minutes: float | None = None
    target_distance_m: float | None = None
    is_club_slot: bool
    source: str | None = None
    data_quality_flag: str | None = None


class WeeklyPlanResponse(BaseModel):
    week_id: str
    week_start: str
    week_end: str
    week_rationale_text: str | None = None
    days: list[WeeklyPlanDay]


@router.get("/weekly-plan/{date_str}", response_model=WeeklyPlanResponse)
def get_weekly_plan(date_str: str) -> WeeklyPlanResponse:
    d = _validate_date(date_str)
    rows = get_week_plan(date_str)
    if not rows:
        # Lazy Fallback - z.B. Sonntags-Trigger ist noch nicht gelaufen oder fehlgeschlagen
        # (gleiches Muster wie GET /api/daily-recommendation/{date} in today.py).
        try:
            rows = generate_weekly_plan(date_str)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Wochenplan konnte nicht generiert werden: {e}")

    iso_year, iso_week, iso_weekday = d.isocalendar()
    week_start = d - timedelta(days=iso_weekday - 1)
    week_end = week_start + timedelta(days=6)

    for row in rows:
        row["is_club_slot"] = bool(row["is_club_slot"])

    return WeeklyPlanResponse(
        week_id=f"{iso_year}-W{iso_week:02d}",
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        week_rationale_text=rows[0]["week_rationale_text"] if rows else None,
        days=[WeeklyPlanDay(**row) for row in rows],
    )


# --- Woche 3: Andeutungs-Ebene (kein Gemini-Call, siehe weekly_planner.py::get_week_outlook) ---

class WeekOutlookDay(BaseModel):
    date: str
    weekday: int
    sport_type: str | None = None
    hint: str | None = None


class WeekOutlookResponse(BaseModel):
    week_id: str
    week_start: str
    week_end: str
    days: list[WeekOutlookDay]


@router.get("/week-outlook/{date_str}", response_model=WeekOutlookResponse)
def get_week_outlook_endpoint(date_str: str) -> WeekOutlookResponse:
    d = _validate_date(date_str)
    outlook = get_week_outlook(date_str)

    iso_year, iso_week, iso_weekday = d.isocalendar()
    week_start = d - timedelta(days=iso_weekday - 1)
    week_end = week_start + timedelta(days=6)

    return WeekOutlookResponse(
        week_id=f"{iso_year}-W{iso_week:02d}",
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        days=[WeekOutlookDay(**day) for day in outlook],
    )


# --- Workout-Entwürfe ---

class WorkoutDraftResponse(BaseModel):
    id: int | None = None
    uploaded: bool = False


@router.get("/workout-draft/{date_str}", response_model=WorkoutDraftResponse)
def get_workout_draft(date_str: str) -> WorkoutDraftResponse:
    _validate_date(date_str)
    conn = get_connection()
    row = conn.execute(
        "SELECT id, uploaded_at FROM weekly_plan_workout_draft WHERE date = ?", (date_str,)
    ).fetchone()
    conn.close()
    if not row:
        return WorkoutDraftResponse()
    return WorkoutDraftResponse(id=row["id"], uploaded=row["uploaded_at"] is not None)


class UploadDraftResponse(BaseModel):
    success: bool
    workout_id: int | None = None
    error: str | None = None


@router.post("/workout-draft/{draft_id}/upload", response_model=UploadDraftResponse)
async def upload_workout_draft(draft_id: int) -> UploadDraftResponse:
    """Baut das Workout frisch aus builder_name+builder_params_json (siehe weekly_planner.py-
    Docstring, warum kein serialisiertes Objekt gespeichert wird), lädt es hoch UND plant es direkt
    für das Datum des Entwurfs in den Garmin-Kalender ein (schedule_date - vorher wurde nur
    hochgeladen, ohne Termin). Blockierende Garmin-Aufrufe laufen über asyncio.to_thread(),
    gleiches Muster wie sync_status.py."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM weekly_plan_workout_draft WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Kein Workout-Entwurf mit id={draft_id}.")

    builder_fn = BUILDER_FUNCTIONS.get(row["builder_name"])
    if builder_fn is None:
        return UploadDraftResponse(success=False, error=f"Unbekannter Builder: {row['builder_name']}")

    params = json.loads(row["builder_params_json"])
    try:
        client = await asyncio.to_thread(get_garmin_client)
        workout = await asyncio.to_thread(lambda: builder_fn(**params))
        result = await asyncio.to_thread(upload_workout, workout, client, row["date"])
    except Exception as e:
        return UploadDraftResponse(success=False, error=str(e))

    if not result["success"]:
        return UploadDraftResponse(success=False, error=result["error"])

    conn = get_connection()
    conn.execute(
        "UPDATE weekly_plan_workout_draft SET uploaded_at = ? WHERE id = ?",
        (datetime.now().isoformat(), draft_id)
    )
    conn.commit()
    conn.close()
    return UploadDraftResponse(success=True, workout_id=result["workout_id"])


# --- Makro-Ebene (Wochen 3-4): grober Trainingsphasen-Ausblick ---

class TrainingOutlookResponse(BaseModel):
    week_id: str | None = None
    training_phase: str | None = None
    days_until_next_race: int | None = None


@router.get("/training-outlook", response_model=TrainingOutlookResponse)
def get_training_outlook() -> TrainingOutlookResponse:
    conn = get_connection()
    row = conn.execute(
        "SELECT week_id, training_phase, days_until_next_race FROM weekly_summary "
        "ORDER BY week_start_date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return TrainingOutlookResponse()
    return TrainingOutlookResponse(**dict(row))


# --- Ab Woche 4: eine Zeile pro Woche bis zum nächsten Rennen (siehe weekly_planner.py::
# get_far_weeks_outlook) ---

class FarWeekBar(BaseModel):
    week_id: str
    iso_week: int
    week_start: str
    week_end: str
    training_phase: str | None = None
    race_title: str | None = None
    race_date: str | None = None


class FarWeeksOutlookResponse(BaseModel):
    weeks: list[FarWeekBar]


@router.get("/far-weeks-outlook/{date_str}", response_model=FarWeeksOutlookResponse)
def get_far_weeks_outlook_endpoint(date_str: str) -> FarWeeksOutlookResponse:
    _validate_date(date_str)
    weeks = get_far_weeks_outlook(date_str)
    return FarWeeksOutlookResponse(weeks=[FarWeekBar(**week) for week in weeks])
