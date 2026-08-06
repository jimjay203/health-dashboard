"""
Backend-Endpoints für die "Erkenntnisse"-Seite (Schicht 3 der KI-Chat-Vorbereitung, siehe
PROJECT_OVERVIEW.md/insight_memory.py) - dünne Wrapper um insight_memory.py, gleiches Muster wie
backend/routers/club_slots.py um training_slots.py.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_connection
import insight_memory

router = APIRouter(prefix="/api/insight-memory", tags=["insight-memory"])


class CompressedVersion(BaseModel):
    version: int
    updated_at: str
    compressed_text: str | None = None


class RawEntry(BaseModel):
    id: int
    created_at: str
    raw_text: str
    source: str


class RawEntryIn(BaseModel):
    raw_text: str


@router.get("/compressed", response_model=list[CompressedVersion])
def get_compressed_versions() -> list[CompressedVersion]:
    return [CompressedVersion(**dict(v)) for v in insight_memory.list_compressed_versions()]


@router.get("/raw", response_model=list[RawEntry])
def get_raw_entries() -> list[RawEntry]:
    return [RawEntry(**dict(e)) for e in insight_memory.list_raw_entries()]


# Läuft synchron (blockierender Gemini-Call, siehe insight_memory.py::add_raw_entry) - FastAPI führt
# einen synchronen def-Handler automatisch im Threadpool aus, gleiches Prinzip wie
# backend/routers/today.py. Gibt bewusst die frisch verdichtete Version zurück (nicht nur den neuen
# Rohtext-Eintrag), damit das Frontend "Aktueller Stand" ohne zweiten Roundtrip aktualisieren kann.
@router.post("/raw", response_model=CompressedVersion)
def add_raw_entry(body: RawEntryIn) -> CompressedVersion:
    text = body.raw_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text darf nicht leer sein.")
    try:
        insight_memory.add_raw_entry(text, source="user")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eintrag konnte nicht verdichtet werden: {e}")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT version, updated_at, compressed_text FROM insight_memory_compressed "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return CompressedVersion(**dict(row))


@router.delete("/raw/{entry_id}")
def delete_raw_entry(entry_id: int) -> dict:
    insight_memory.delete_raw_entry(entry_id)
    return {"success": True}
