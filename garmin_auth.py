import os
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")
TOKEN_DIR = os.path.expanduser("~/.garminconnect")

# Prozessweiter Cache, damit innerhalb eines laufenden Prozesses
# (z.B. der Streamlit-App) nicht bei jedem Klick neu eingeloggt wird.
_cached_client = None

def get_garmin_client(force_new: bool = False):
    """Erstellt ein Garmin-Objekt und nutzt lokal gespeicherte Tokens, um Logins zu vermeiden.

    Seit garminconnect 0.3.0 läuft die Auth nativ über DI OAuth: login(tokenstore_path)
    speichert die Tokens selbst (kein manuelles client.garth.dump() mehr nötig/möglich).

    Reihenfolge:
    1. Bereits im Prozess gecachter Client (z.B. wiederholte Klicks in der UI)
    2. Lokal gespeicherte Session-Tokens aus TOKEN_DIR
    3. Regulärer Passwort-Login als letzter Ausweg
    """
    global _cached_client

    if _cached_client is not None and not force_new:
        return _cached_client

    try:
        client = Garmin()
        client.login(TOKEN_DIR)
        print("✅ Session erfolgreich aus gespeicherten Tokens wiederhergestellt!")
    except GarminConnectTooManyRequestsError:
        # Rate-Limit direkt durchreichen, NICHT auf Passwort-Login zurückfallen -
        # sonst verlängert sich die Sperre nur.
        raise
    except (GarminConnectAuthenticationError, GarminConnectConnectionError, Exception):
        print("🔑 Kein gültiges Token gefunden, führe Passwort-Login durch...")
        if not GARMIN_EMAIL or not GARMIN_PASSWORD:
            raise ValueError("GARMIN_EMAIL und GARMIN_PASSWORD müssen in .env gesetzt sein.")
        client = Garmin(email=GARMIN_EMAIL, password=GARMIN_PASSWORD)
        client.login(TOKEN_DIR)  # speichert Tokens automatisch in TOKEN_DIR
        print(f"💾 Neue Session-Tokens gespeichert unter: {TOKEN_DIR}")

    _cached_client = client
    return client
