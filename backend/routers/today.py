"""
Backend-Endpoints für die Heute-Ansicht (siehe PROJECT_OVERVIEW.md, "Heute-Ansicht"-Abschnitt):
KI-Empfehlung inkl. Override, Wochenstreifen. Der Readiness-Score + Metrik-Trends kommen für die
Heute-Seite mittlerweile aus GET /api/performance/readiness-overview/{date} (siehe
backend/routers/performance.py - liefert zusätzlich HRV/Ruhepuls, die TodayView.tsx jetzt ebenfalls
zeigt). Alle Handler sind synchrone def-Funktionen wie backend/routers/daily_summary.py -
FastAPI/Starlette führt sie automatisch in einem Threadpool aus, kein asyncio.to_thread() nötig
(anders als in auto_sync.py, das selbst im Event-Loop läuft).
"""
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_connection
from daily_recommendation import generate_daily_recommendation, get_cached_recommendation, \
    set_override_and_regenerate

router = APIRouter(prefix="/api", tags=["today"])


def _validate_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum muss im Format YYYY-MM-DD sein.")


# --- Empfehlung ---

class RecommendationResponse(BaseModel):
    date: str
    recommendation_text: str
    reasoning_bullets: list[str]
    generated_at: str


@router.get("/daily-recommendation/{date_str}", response_model=RecommendationResponse)
def get_daily_recommendation(date_str: str) -> RecommendationResponse:
    _validate_date(date_str)
    cached = get_cached_recommendation(date_str)
    if cached:
        return RecommendationResponse(**cached)
    try:
        fresh = generate_daily_recommendation(date_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Empfehlung konnte nicht generiert werden: {e}")
    return RecommendationResponse(**fresh)


class OverrideRequest(BaseModel):
    override_value: Literal["worse", "better", "neutral"]


@router.post("/daily-override/{date_str}", response_model=RecommendationResponse)
def post_daily_override(date_str: str, body: OverrideRequest) -> RecommendationResponse:
    _validate_date(date_str)
    try:
        fresh = set_override_and_regenerate(date_str, body.override_value)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Override konnte nicht verarbeitet werden: {e}")
    return RecommendationResponse(**fresh)


# --- Wochenstreifen ---

class WeekDay(BaseModel):
    date: str
    weekday: int  # 0=Montag ... 6=Sonntag
    category: Literal["race", "completed", "club", "rest"]
    label: str | None = None
    sport_type: str | None = None  # nur bei category="club" gesetzt, siehe club_slots.py::SportType
    is_today: bool


class WeekStripResponse(BaseModel):
    week_start: str
    week_end: str
    days: list[WeekDay]


@router.get("/week-strip/{date_str}", response_model=WeekStripResponse)
def get_week_strip(date_str: str) -> WeekStripResponse:
    d = _validate_date(date_str)
    iso_weekday = d.isoweekday()  # 1=Montag..7=Sonntag
    week_start = d - timedelta(days=iso_weekday - 1)
    week_end = week_start + timedelta(days=6)
    today_str = date.today().isoformat()

    conn = get_connection()
    cursor = conn.cursor()

    days = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        day_str = day.isoformat()
        weekday = day.weekday()  # 0=Montag..6=Sonntag

        # Priorität bei Überschneidungen (siehe PROJECT_OVERVIEW.md): race > completed > club >
        # rest. Rennen schlägt Vereinstermin (Nutzer-Vorgabe); "tatsächlich passiert" schlägt den
        # geplanten Club-Slot, falls an einem Vereins-Wochentag doch woanders trainiert wurde.
        race_row = cursor.execute(
            "SELECT title FROM garmin_scheduled_events WHERE event_date = ? AND is_race = 1 LIMIT 1",
            (day_str,)
        ).fetchone()
        activity_row = cursor.execute(
            "SELECT activity_type FROM garmin_activities WHERE date(start_time_local) = ? LIMIT 1",
            (day_str,)
        ).fetchone()
        club_row = cursor.execute(
            "SELECT label, sport_type FROM club_training_slots WHERE weekday = ? AND valid_from <= ? "
            "AND (valid_to IS NULL OR valid_to >= ?) LIMIT 1",
            (weekday, day_str, day_str)
        ).fetchone()

        sport_type = None
        if race_row:
            category, label = "race", race_row["title"]
        elif activity_row:
            category, label = "completed", activity_row["activity_type"]
        elif club_row:
            category, label, sport_type = "club", club_row["label"], club_row["sport_type"]
        else:
            category, label = "rest", None

        days.append(WeekDay(
            date=day_str, weekday=weekday, category=category, label=label, sport_type=sport_type,
            is_today=(day_str == today_str),
        ))

    conn.close()
    return WeekStripResponse(week_start=week_start.isoformat(), week_end=week_end.isoformat(), days=days)
