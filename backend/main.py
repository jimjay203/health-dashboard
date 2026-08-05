"""
FastAPI-Einstiegspunkt (Schritt 1 des Rebuilds - bewusst inhaltlich leer, siehe PROJECT_OVERVIEW.md).
Liegt im Container-Image direkt neben db.py, siehe Dockerfile.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routers import daily_summary

app = FastAPI(title="Health Dashboard API")

app.include_router(daily_summary.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Muss zuletzt gemountet werden - StaticFiles(html=True) ist ein Catch-all auf "/", API-Routen
# oben werden von FastAPI/Starlette in Registrierungsreihenfolge zuerst geprüft.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
