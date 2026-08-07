"""
Backend-Endpoints für die Daten-Engine auf der Einstellungen-Seite - die letzten noch aus
Streamlit fehlenden Sync-Funktionen (siehe pages/3_⚙️_Settings.py): Einzel-Tages-Sync für ein
beliebiges Datum (Garmin + Withings), Backfill über einen Zeitraum, Aktivitäten-Sync
(Liste + Detail-Zeitreihen). Backfill und Aktivitäten-Details laufen mehrere Sekunden bis Minuten
(bewusst gedrosselte Pausen zwischen Tagen/Aktivitäten, siehe garmin_backfill.py/
garmin_activities.py) - dafür bewusst NICHT als blockierender Request, sondern als Hintergrund-
Task mit Status-Polling (analog zu auto_sync.py/sync_status.py), damit die Anfrage nicht in einem
Request-Timeout läuft und das Frontend währenddessen einen Fortschritt anzeigen kann. Die
API-Exploration (Tier-1/2-Testabruf) aus Streamlit ist bewusst NICHT mit übernommen - das ist ein
Debug-/Explorations-Werkzeug, keine Sync-Funktion.
"""
import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_connection
from garmin_auth import get_garmin_client
from garmin_service import fetch_and_store_garmin_data
from garmin_backfill import run_backfill
from garmin_activities import sync_activity_list, sync_activity_details
from withings_service import fetch_and_store_withings_data, fetch_full_withings_history
from withings_auth import get_token_status
from withings_auto_sync import get_status as get_withings_auto_sync_status
from daily_summary import recompute_summary_range

router = APIRouter(prefix="/api/data-sync", tags=["data-sync"])


def _validate_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum muss im Format YYYY-MM-DD sein.")


# --- Einzel-Tages-Sync (Garmin + Withings) für ein beliebiges Datum ---
# Ergänzt POST /api/sync-trigger (sync_status.py), das nur "heute" synct.

class DaySyncResponse(BaseModel):
    success: bool
    error: str | None = None
    measurement_count: int | None = None  # nur bei Withings gesetzt


@router.post("/garmin-day/{date_str}", response_model=DaySyncResponse)
async def sync_garmin_day(date_str: str) -> DaySyncResponse:
    _validate_date(date_str)
    try:
        client = await asyncio.to_thread(get_garmin_client)
        await asyncio.to_thread(fetch_and_store_garmin_data, date_str, client)
        return DaySyncResponse(success=True)
    except Exception as e:
        return DaySyncResponse(success=False, error=str(e))


@router.post("/withings-day/{date_str}", response_model=DaySyncResponse)
async def sync_withings_day(date_str: str) -> DaySyncResponse:
    _validate_date(date_str)
    try:
        count = await asyncio.to_thread(fetch_and_store_withings_data, date_str)
        return DaySyncResponse(success=True, measurement_count=count)
    except Exception as e:
        return DaySyncResponse(success=False, error=str(e))


@router.post("/withings-full-history", response_model=DaySyncResponse)
async def sync_withings_full_history() -> DaySyncResponse:
    """Einmaliger Voll-Import der kompletten Withings-Historie (siehe
    withings_service.py::fetch_full_withings_history) - bewusst blockierend statt Hintergrund-Task
    wie Backfill unten: Withings liefert die ganze Historie über wenige paginierte Aufrufe (kein
    day-by-day-Loop mit Drosselungspausen wie bei Garmin nötig), das passt in ein normales
    Request-Timeout."""
    try:
        count = await asyncio.to_thread(fetch_full_withings_history)
        return DaySyncResponse(success=True, measurement_count=count)
    except Exception as e:
        return DaySyncResponse(success=False, error=str(e))


class WithingsAutoSyncStatusResponse(BaseModel):
    last_run_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    last_measurement_count: int | None = None
    token_created_at: int | None = None
    token_expires_at: int | None = None


@router.get("/withings-auto-sync-status", response_model=WithingsAutoSyncStatusResponse)
def get_withings_auto_sync_status_route() -> WithingsAutoSyncStatusResponse:
    """Status des stündlichen Hintergrund-Tasks (siehe withings_auto_sync.py) - hält primär den
    OAuth2-Token aktiv (Root-Cause des Vorfalls vom 2026-08-07: ein über 52h nie genutzter
    Refresh-Token wurde beim fälligen Refresh ungültig), synct nebenbei den heutigen Tag.
    token_status kommt bewusst über get_token_status() (kein Refresh-Seiteneffekt) statt
    get_withings_tokens()."""
    status = get_withings_auto_sync_status()
    token_status = get_token_status() or {}
    return WithingsAutoSyncStatusResponse(
        **status,
        token_created_at=token_status.get("created_at"),
        token_expires_at=token_status.get("expires_at"),
    )


# --- Backfill über einen Zeitraum (Hintergrund-Task + Status-Polling) ---

_backfill_state = {
    "running": False,
    "current_date": None,
    "success_count": 0,
    "error_count": 0,
    "total": 0,
    "stopped_early": False,
    "last_error": None,
}


async def _run_backfill_task(start, end):
    _backfill_state.update(
        running=True, current_date=None, success_count=0, error_count=0,
        total=(end - start).days + 1, stopped_early=False, last_error=None,
    )
    try:
        client = await asyncio.to_thread(get_garmin_client)
    except Exception as e:
        _backfill_state.update(running=False, last_error=str(e))
        return

    def on_progress(current_date, status, success_count, error_count, total, error_detail=None):
        _backfill_state.update(
            current_date=current_date.isoformat(), success_count=success_count,
            error_count=error_count, total=total,
        )
        if status == "rate_limited":
            _backfill_state["last_error"] = f"Rate-Limit erreicht: {error_detail}"
        elif status == "error" and error_detail:
            _backfill_state["last_error"] = error_detail

    try:
        success_count, error_count, stopped_early = await asyncio.to_thread(
            run_backfill, start, end, client, on_progress
        )
        _backfill_state.update(
            running=False, success_count=success_count, error_count=error_count, stopped_early=stopped_early,
        )
    except Exception as e:
        _backfill_state.update(running=False, last_error=str(e))


class BackfillRequest(BaseModel):
    start_date: str
    end_date: str


class BackfillStartResponse(BaseModel):
    started: bool


@router.post("/backfill", response_model=BackfillStartResponse)
async def start_backfill(body: BackfillRequest) -> BackfillStartResponse:
    if _backfill_state["running"]:
        raise HTTPException(status_code=409, detail="Backfill läuft bereits.")
    start = _validate_date(body.start_date)
    end = _validate_date(body.end_date)
    if start > end:
        raise HTTPException(status_code=400, detail="Startdatum muss vor oder gleich dem Enddatum liegen.")
    asyncio.create_task(_run_backfill_task(start, end))
    return BackfillStartResponse(started=True)


class BackfillStatusResponse(BaseModel):
    running: bool
    current_date: str | None = None
    success_count: int = 0
    error_count: int = 0
    total: int = 0
    stopped_early: bool = False
    last_error: str | None = None


@router.get("/backfill-status", response_model=BackfillStatusResponse)
def get_backfill_status() -> BackfillStatusResponse:
    return BackfillStatusResponse(**_backfill_state)


# --- CTL/ATL/TSB (daily_summary/weekly_summary) für einen Zeitraum neu berechnen - rein lokal,
# kein Garmin-API-Call (siehe daily_summary.py::recompute_summary_range). Braucht man z.B. nach
# nachträglichem Aktivitäten-Nachladen (siehe Aktivitäten-Sektion unten) - das löst selbst keinen
# compute_daily_summary()-Aufruf aus, die CTL/ATL-Kette bliebe sonst auf altem Stand stehen. Anders
# als Backfill oben bewusst blockierend statt Hintergrund-Task - keine Drosselungspausen nötig,
# eine Neuberechnung über Monate dauert nur Sekunden.

class RecomputeSummaryRequest(BaseModel):
    start_date: str
    end_date: str


class RecomputeSummaryResponse(BaseModel):
    success: bool
    days_recomputed: int = 0
    error: str | None = None


@router.post("/recompute-summary", response_model=RecomputeSummaryResponse)
async def recompute_summary(body: RecomputeSummaryRequest) -> RecomputeSummaryResponse:
    _validate_date(body.start_date)
    _validate_date(body.end_date)
    try:
        count = await asyncio.to_thread(recompute_summary_range, body.start_date, body.end_date)
        return RecomputeSummaryResponse(success=True, days_recomputed=count)
    except Exception as e:
        return RecomputeSummaryResponse(success=False, error=str(e))


# --- Aktivitäten (Liste + Detail-Zeitreihen) ---

class ActivitiesSummaryResponse(BaseModel):
    total_activities: int
    pending_details: int


@router.get("/activities-summary", response_model=ActivitiesSummaryResponse)
def get_activities_summary() -> ActivitiesSummaryResponse:
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) AS n FROM garmin_activities").fetchone()["n"]
    pending = conn.execute("SELECT COUNT(*) AS n FROM garmin_activities WHERE has_details_synced = 0").fetchone()["n"]
    conn.close()
    return ActivitiesSummaryResponse(total_activities=total, pending_details=pending)


class ActivityRow(BaseModel):
    activity_id: int
    start_time_local: str | None = None
    activity_type: str | None = None
    activity_name: str | None = None
    distance_km: float | None = None
    has_details_synced: bool


@router.get("/activities", response_model=list[ActivityRow])
def get_activities(limit: int = 50) -> list[ActivityRow]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT activity_id, start_time_local, activity_type, activity_name, "
        "ROUND(distance_meters / 1000.0, 2) AS distance_km, has_details_synced "
        "FROM garmin_activities ORDER BY start_time_local DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [
        ActivityRow(**{**dict(r), "has_details_synced": bool(r["has_details_synced"])})
        for r in rows
    ]


class ActivityListSyncRequest(BaseModel):
    limit: int = 20


class ActivityListSyncResponse(BaseModel):
    success: bool
    count: int = 0
    error: str | None = None


@router.post("/activities-list", response_model=ActivityListSyncResponse)
async def sync_activities_list(body: ActivityListSyncRequest) -> ActivityListSyncResponse:
    """Eine einzelne Garmin-API-Seite (ein Aufruf, siehe garmin_activities.py::sync_activity_list) -
    bewusst blockierend statt Hintergrund-Task, da hier nur eine kurze Pause anfällt, kein
    sequentieller Mehrtage-/Mehraktivitäten-Ablauf wie bei Backfill/Detail-Sync."""
    try:
        client = await asyncio.to_thread(get_garmin_client)
        count = await asyncio.to_thread(sync_activity_list, client, body.limit)
        return ActivityListSyncResponse(success=True, count=count)
    except Exception as e:
        return ActivityListSyncResponse(success=False, error=str(e))


_activity_details_state = {
    "running": False,
    "current_index": 0,
    "total": 0,
    "current_activity_name": None,
    "synced_count": 0,
    "error_count": 0,
    "last_error": None,
}


async def _run_activity_details_task(max_count):
    _activity_details_state.update(
        running=True, current_index=0, total=0, current_activity_name=None,
        synced_count=0, error_count=0, last_error=None,
    )
    try:
        client = await asyncio.to_thread(get_garmin_client)
    except Exception as e:
        _activity_details_state.update(running=False, last_error=str(e))
        return

    def on_progress(index, total, activity_name, status):
        _activity_details_state.update(current_index=index, total=total, current_activity_name=activity_name)
        if status == "ok":
            _activity_details_state["synced_count"] += 1
        else:
            _activity_details_state["error_count"] += 1

    try:
        synced, errors = await asyncio.to_thread(sync_activity_details, client, max_count, on_progress)
        _activity_details_state.update(running=False, synced_count=synced, error_count=errors)
    except Exception as e:
        _activity_details_state.update(running=False, last_error=str(e))


class ActivityDetailsSyncRequest(BaseModel):
    max_count: int = 5


class ActivityDetailsStartResponse(BaseModel):
    started: bool


@router.post("/activities-details", response_model=ActivityDetailsStartResponse)
async def start_activity_details_sync(body: ActivityDetailsSyncRequest) -> ActivityDetailsStartResponse:
    if _activity_details_state["running"]:
        raise HTTPException(status_code=409, detail="Detail-Sync läuft bereits.")
    asyncio.create_task(_run_activity_details_task(body.max_count))
    return ActivityDetailsStartResponse(started=True)


class ActivityDetailsStatusResponse(BaseModel):
    running: bool
    current_index: int = 0
    total: int = 0
    current_activity_name: str | None = None
    synced_count: int = 0
    error_count: int = 0
    last_error: str | None = None


@router.get("/activities-details-status", response_model=ActivityDetailsStatusResponse)
def get_activity_details_status() -> ActivityDetailsStatusResponse:
    return ActivityDetailsStatusResponse(**_activity_details_state)
