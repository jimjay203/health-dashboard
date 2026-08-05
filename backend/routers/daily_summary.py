"""
Erster Endpoint des FastAPI-Rebuilds (Schritt 1): liest die bereits von daily_summary.py
berechnete/gespeicherte Tageszeile über db.py::get_connection() - reiner Lesezugriff, keine
Berechnungslogik hier. db.py wird unverändert wiederverwendet (siehe Dockerfile: liegt im
Image direkt neben main.py).
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from db import get_connection

router = APIRouter(prefix="/api", tags=["daily-summary"])


class DailySummaryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")  # daily_summary hat u.a. created_at, das wir nicht ausgeben

    date: str
    hrv_vs_7d_avg_pct: float | None = None
    hrv_vs_28d_avg_pct: float | None = None
    sleep_vs_7d_avg_pct: float | None = None
    resting_hr_vs_7d_avg_pct: float | None = None
    training_load_7d: float | None = None
    training_load_28d: float | None = None
    acute_chronic_ratio: float | None = None
    training_monotony: float | None = None
    training_strain: float | None = None
    sleep_debt_cumulative: float | None = None
    overreach_flag: int | None = None
    days_until_next_race: int | None = None
    weight_vs_avg_pct: float | None = None
    data_quality_flag: str | None = None
    notable_events_text: str | None = None
    ctl: float | None = None
    atl: float | None = None
    tsb: float | None = None
    journal_rpe: int | None = None
    journal_soreness: int | None = None
    journal_energy_level: int | None = None


@router.get("/daily-summary/{date_str}", response_model=DailySummaryResponse)
def get_daily_summary(date_str: str) -> DailySummaryResponse:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum muss im Format YYYY-MM-DD sein.")

    conn = get_connection()
    row = conn.execute("SELECT * FROM daily_summary WHERE date = ?", (date_str,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Keine daily_summary-Daten für {date_str} gefunden.")

    return DailySummaryResponse(**dict(row))
