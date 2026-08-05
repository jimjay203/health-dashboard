"""
CRUD-Endpoints für wiederkehrende Vereins-Trainingstermine (siehe training_slots.py). Genutzt von
der neuen Settings-Oberfläche im React-Frontend (nicht der alten Streamlit-Settings-Seite - die
bleibt unverändert, siehe PROJECT_OVERVIEW.md).
"""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import training_slots

router = APIRouter(prefix="/api", tags=["club-slots"])

# Feste Sportart-Auswahl fürs Dropdown im Frontend (siehe ClubSlotsSettings.tsx) - Emoji-Zuordnung
# fürs Wochenstreifen-Icon lebt bewusst im Frontend (api.ts), hier nur die Wertemenge zur Validierung.
SportType = Literal["Schwimmen", "Laufen", "Rad", "Krafttraining", "Mobility"]


class ClubSlotIn(BaseModel):
    weekday: int  # 0=Montag ... 6=Sonntag
    sport_type: SportType
    label: str
    valid_from: str
    valid_to: str | None = None
    # Freitext fürs Wochenplaner-Modell (siehe weekly_planner.py) - was an diesem Slot realistisch
    # möglich ist, z.B. "Bahntraining: meist Intervalle, 400-1000m Wiederholungen". Optional.
    typical_character: str | None = None


class ClubSlotResponse(ClubSlotIn):
    id: int


@router.get("/club-slots", response_model=list[ClubSlotResponse])
def list_club_slots() -> list[ClubSlotResponse]:
    return [ClubSlotResponse(**slot) for slot in training_slots.list_slots()]


@router.post("/club-slots", response_model=ClubSlotResponse)
def create_club_slot(body: ClubSlotIn) -> ClubSlotResponse:
    created = training_slots.create_slot(**body.model_dump())
    return ClubSlotResponse(**created)


@router.put("/club-slots/{slot_id}", response_model=ClubSlotResponse)
def update_club_slot(slot_id: int, body: ClubSlotIn) -> ClubSlotResponse:
    updated = training_slots.update_slot(slot_id, **body.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail=f"Kein Vereins-Slot mit id={slot_id}.")
    return ClubSlotResponse(**updated)


@router.delete("/club-slots/{slot_id}")
def delete_club_slot(slot_id: int) -> dict:
    training_slots.delete_slot(slot_id)
    return {"success": True}
