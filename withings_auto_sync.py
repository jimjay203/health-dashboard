"""
Automatischer Withings-Sync: hält den OAuth2-Token aktiv (siehe withings_auth.py) und synct
nebenbei den heutigen Tag. Reine Python-Logik, kein Streamlit-/FastAPI-Import (Portabilitäts-
Prinzip, analog zu auto_sync.py) - läuft als eigener asyncio-Hintergrund-Task im FastAPI-Backend
(siehe backend/main.py).

Hintergrund/Root-Cause (Vorfall vom 2026-08-07): der Withings-Refresh-Token wurde bisher von
NICHTS periodisch genutzt - erst ein manueller Sync nach über 52h Inaktivität hat den fälligen
Refresh ausgelöst, der dann mit "invalid refresh_token" fehlschlug (genaue Ursache nicht restlos
geklärt: Withings-seitige Ablauffrist für lange ungenutzte Refresh-Tokens ist der wahrscheinlichste
Kandidat). Der Zugriffstoken selbst lebt nur ~3h (withings_auth.py::REFRESH_MARGIN_SECONDS refresht
kurz vorher) - ein Sync-Intervall deutlich darunter hält den Token durchgehend in aktiver Nutzung/
Rotation, unabhängig davon, ob überhaupt neue Messwerte vorliegen.
"""
import asyncio
from datetime import datetime

from withings_service import fetch_and_store_withings_data
from db import log_sync_event
from sync_activity import set_withings_syncing

# Deutlich unter der ~3h-Zugriffstoken-Lebensdauer, damit get_withings_tokens() (siehe
# withings_auth.py) den Token nie ungenutzt ablaufen lässt.
WITHINGS_SYNC_INTERVAL_SECONDS = 60 * 60

# In-Memory-Status für die Einstellungen-Seite (analog zu _backfill_state in
# backend/routers/data_sync.py) - rein informativ, kein Persistenz-/Idempotenz-Zweck wie
# auto_sync_status bei Garmin, da hier jeder Lauf ohnehin denselben Tag erneut synct.
_status = {
    "last_run_at": None,
    "last_success_at": None,
    "last_error": None,
    "last_measurement_count": None,
}


def get_status():
    return dict(_status)


async def run_withings_auto_sync_forever(interval_seconds=WITHINGS_SYNC_INTERVAL_SECONDS, now_fn=datetime.now):
    """Dauerlauf-Task, läuft solange der FastAPI-Prozess lebt (siehe backend/main.py, Lifespan-
    Hintergrund-Task) - synct im festen Takt den heutigen Tag (statt wie beim Garmin-Sync einmal
    täglich zu einer festen Uhrzeit), damit sowohl neue Waagen-Messwerte zeitnah ankommen als auch
    der Token durchgehend aktiv bleibt. Best effort: einzelne Fehlschläge (z.B. Withings kurzzeitig
    nicht erreichbar) dürfen die Schleife nicht beenden, nur geloggt werden - exakt das Muster aus
    auto_sync.py::run_daily_auto_sync_forever für den äußeren try/except."""
    while True:
        _status["last_run_at"] = datetime.now().isoformat()
        set_withings_syncing(True)
        try:
            target_date = now_fn().date().isoformat()
            count = await asyncio.to_thread(fetch_and_store_withings_data, target_date)
            _status["last_success_at"] = datetime.now().isoformat()
            _status["last_error"] = None
            _status["last_measurement_count"] = count
            log_sync_event("withings", "auto", "abgeschlossen", f"{count} Messung(en)")
        except Exception as e:
            _status["last_error"] = str(e)
            print(f"⚠️  withings_auto_sync: Sync fehlgeschlagen: {e}")
            log_sync_event("withings", "auto", "fehler", str(e))
        finally:
            set_withings_syncing(False)
        await asyncio.sleep(interval_seconds)
