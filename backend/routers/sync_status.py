"""
Endpoints für den automatischen Sync-Trigger (siehe auto_sync.py im Repo-Root). Der
Hintergrund-Task selbst wird beim App-Start über den Lifespan-Kontextmanager in main.py
angestoßen, nicht hier - diese Router-Datei stellt nur Status-Einsicht und einen optionalen
manuellen Sofort-Trigger bereit.
"""
import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from auto_sync import get_status
from garmin_auth import get_garmin_client
from garmin_service import fetch_and_store_garmin_data
from db import log_sync_event
from sync_activity import set_garmin_syncing, get_sync_activity

router = APIRouter(prefix="/api", tags=["sync-status"])


class SyncStatusResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str
    status: str  # not_started | checking | completed | gave_up | rate_limited
    first_check_at: str | None = None
    last_check_at: str | None = None
    check_count: int = 0
    sleep_data_found: bool = False
    full_sync_completed_at: str | None = None
    gave_up_at: str | None = None
    last_error: str | None = None


@router.get("/sync-status", response_model=SyncStatusResponse)
def sync_status() -> SyncStatusResponse:
    return SyncStatusResponse(**get_status())


class SyncTriggerResponse(BaseModel):
    success: bool
    error: str | None = None


@router.post("/sync-trigger", response_model=SyncTriggerResponse)
async def sync_trigger() -> SyncTriggerResponse:
    """Manueller Sofort-Trigger über die API - Ergänzung, kein Ersatz für den bestehenden
    Streamlit-Settings-Button. Läuft über asyncio.to_thread(), da die Garmin-Aufrufe blockierend
    sind und den Event-Loop sonst einfrieren würden."""
    set_garmin_syncing(True)
    try:
        client = await asyncio.to_thread(get_garmin_client)
        await asyncio.to_thread(fetch_and_store_garmin_data, None, client)
        log_sync_event("garmin", "manual", "abgeschlossen", "TopBar-Button (heute)")
        return SyncTriggerResponse(success=True)
    except Exception as e:
        log_sync_event("garmin", "manual", "fehler", str(e))
        return SyncTriggerResponse(success=False, error=str(e))
    finally:
        set_garmin_syncing(False)


class SyncActivityResponse(BaseModel):
    garmin_syncing: bool
    withings_syncing: bool


@router.get("/sync-activity", response_model=SyncActivityResponse)
def sync_activity() -> SyncActivityResponse:
    """Live-Zustand für die TopBar-Pille (siehe sync_activity.py) - "läuft gerade irgendein Sync",
    unabhängig vom persistenten Verlauf (GET /api/data-sync/{garmin,withings}-sync-log). Gepollt
    statt push-basiert, da Hintergrund-Tasks (auto_sync.py/withings_auto_sync.py) keine eigene
    WebSocket-Verbindung zum Frontend haben."""
    return SyncActivityResponse(**get_sync_activity())
