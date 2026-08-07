"""
FastAPI-Einstiegspunkt (Schritt 1 des Rebuilds - bewusst inhaltlich leer, siehe PROJECT_OVERVIEW.md).
Liegt im Container-Image direkt neben db.py und den übrigen Root-Level-Modulen, siehe Dockerfile.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routers import daily_summary, sync_status, today, club_slots, weekly_plan, performance, insight_memory, \
    sleep, habit_tracker, data_sync, body
from auto_sync import run_daily_auto_sync_forever
from db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema-Migration lief bisher nur implizit über init_db()-Aufrufe der Streamlit-Seiten (siehe
    # pages/*.py) - dashboard-v2 teilt sich zwar dieselbe SQLite-Datei (docker-compose.yml), aber
    # falls dashboard-v2 vor dem ersten Streamlit-Seitenaufruf startet (z.B. frischer Host/Volume),
    # fehlen neu hinzugekommene Tabellen wie weekly_plan. Eigener init_db()-Aufruf macht die API
    # unabhängig davon.
    init_db()
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
app.include_router(insight_memory.router)
app.include_router(sleep.router)
app.include_router(habit_tracker.router)
app.include_router(data_sync.router)
app.include_router(body.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Muss zuletzt gemountet werden - StaticFiles(html=True) ist ein Catch-all auf "/", API-Routen
# oben werden von FastAPI/Starlette in Registrierungsreihenfolge zuerst geprüft.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
