"""
FastAPI-Einstiegspunkt (Schritt 1 des Rebuilds - bewusst inhaltlich leer, siehe PROJECT_OVERVIEW.md).
Liegt im Container-Image direkt neben db.py und den übrigen Root-Level-Modulen, siehe Dockerfile.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routers import daily_summary, sync_status, today, club_slots, weekly_plan, performance
from auto_sync import run_daily_auto_sync_forever


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Automatischer Sync-Trigger (siehe auto_sync.py) - läuft als Hintergrund-Task im selben
    # Event-Loop, solange der Container lebt. Kein manueller Anstoß nötig.
    task = asyncio.create_task(run_daily_auto_sync_forever())
    yield
    task.cancel()


app = FastAPI(title="Health Dashboard API", lifespan=lifespan)

app.include_router(daily_summary.router)
app.include_router(sync_status.router)
app.include_router(today.router)
app.include_router(club_slots.router)
app.include_router(weekly_plan.router)
app.include_router(performance.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Muss zuletzt gemountet werden - StaticFiles(html=True) ist ein Catch-all auf "/", API-Routen
# oben werden von FastAPI/Starlette in Registrierungsreihenfolge zuerst geprüft.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
