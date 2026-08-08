"""
Sammel-Endpoint "Alle KI-Texte neu generieren" für die neue TopBar-Pille (siehe TopBar.tsx,
analog zur bestehenden Sync-Pille) - seit dem 2026-08-08 generiert keiner der Insight-/
Empfehlungs-Endpoints mehr automatisch beim Seitenaufruf (Nutzer-Vorgabe), dieser Endpoint bündelt
die einzelnen, weiterhin vorhandenen Regenerate-Funktionen zu einem Klick.

Bewusst OHNE Wochenplan (weekly_planner.py) - der hat einen eigenen Sonntags-Auto-Trigger
(auto_sync.py) und pro-Woche-Buttons in WeeklyCalendarWidget.tsx; ein versehentlicher Klick hier
soll keine bereits zu Garmin hochgeladenen Workout-Entwürfe zurücksetzen (siehe
backend/routers/weekly_plan.py::regenerate_weekly_plan-Docstring zum already_uploaded_count-Risiko).

Läuft sequentiell statt parallel (asyncio.gather) - vermeidet gleichzeitige SQLite-Schreibzugriffe
aus mehreren Threads gleichzeitig, unkritisch für eine gelegentlich per Klick ausgelöste
Sammel-Aktion.
"""
import asyncio
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

import body_composition
from daily_recommendation import generate_daily_recommendation
from sleep_trend_insight import generate_trend_insight as generate_sleep_trend_insight
from sleep_insight import generate_correlations_insight
from body_trend_insight import generate_trend_insight as generate_body_trend_insight
from performance_insight import generate_goals_insight
from routers.sleep import get_sleep_trend

router = APIRouter(prefix="/api/ai-texts", tags=["ai-texts"])


class RegenerateAllResult(BaseModel):
    key: str
    label: str
    success: bool
    error: str | None = None


class RegenerateAllResponse(BaseModel):
    results: list[RegenerateAllResult]


@router.post("/regenerate-all", response_model=RegenerateAllResponse)
async def regenerate_all_ai_texts() -> RegenerateAllResponse:
    today = date.today().isoformat()
    results: list[RegenerateAllResult] = []

    async def run(key, label, fn):
        try:
            await asyncio.to_thread(fn)
            results.append(RegenerateAllResult(key=key, label=label, success=True))
        except Exception as e:
            results.append(RegenerateAllResult(key=key, label=label, success=False, error=str(e)))

    await run("daily_recommendation", "Trainingsbereitschaft (Heute)", lambda: generate_daily_recommendation(today))
    await run(
        "sleep_trend", "Schlaf-Trend (28 Tage)",
        lambda: generate_sleep_trend_insight(today, get_sleep_trend(days=28).points)
    )
    await run(
        "sleep_correlations", "Schlaf-Korrelationen",
        lambda: generate_correlations_insight(today, get_sleep_trend(days=28).points)
    )
    await run(
        "body_trend", "Körper-Trend (90 Tage)",
        lambda: generate_body_trend_insight(today, body_composition.get_body_trend(90)["points"])
    )
    await run("performance_goals", "Leistungsziele-Einschätzung", lambda: generate_goals_insight(today))

    return RegenerateAllResponse(results=results)
