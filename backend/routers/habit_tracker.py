"""
Backend-Endpoints für den Habit-Tracker (siehe habit_tracker.py, "Schlaf"-Seite) - dünner Wrapper,
gleiches Muster wie backend/routers/club_slots.py um training_slots.py.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import habit_tracker

router = APIRouter(prefix="/api/habit-tracker", tags=["habit-tracker"])


def _validate_date(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum muss im Format YYYY-MM-DD sein.")


class HabitEntryResponse(BaseModel):
    date: str
    caffeine_after_noon: bool | None = None
    last_screen_time: str | None = None
    last_meal_time: str | None = None


class HabitEntryIn(BaseModel):
    caffeine_after_noon: bool
    last_screen_time: str | None = None
    last_meal_time: str | None = None


@router.get("/{date_str}", response_model=HabitEntryResponse)
def get_habit_entry(date_str: str) -> HabitEntryResponse:
    _validate_date(date_str)
    entry = habit_tracker.get_habit_entry(date_str)
    if not entry:
        return HabitEntryResponse(date=date_str)
    return HabitEntryResponse(
        date=date_str,
        caffeine_after_noon=bool(entry["caffeine_after_noon"]) if entry["caffeine_after_noon"] is not None else None,
        last_screen_time=entry["last_screen_time"],
        last_meal_time=entry["last_meal_time"],
    )


@router.put("/{date_str}", response_model=HabitEntryResponse)
def put_habit_entry(date_str: str, body: HabitEntryIn) -> HabitEntryResponse:
    _validate_date(date_str)
    habit_tracker.save_habit_entry(
        date_str, body.caffeine_after_noon, body.last_screen_time, body.last_meal_time,
    )
    return HabitEntryResponse(
        date=date_str,
        caffeine_after_noon=body.caffeine_after_noon,
        last_screen_time=body.last_screen_time,
        last_meal_time=body.last_meal_time,
    )
