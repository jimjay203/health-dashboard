import os
import json
from datetime import date
from garminconnect import Garmin
from db import save_garmin_data

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")

def fetch_and_store_garmin_data(target_date=None):
    """Holt die wichtigsten Metriken für ein Datum und speichert sie in SQLite."""
    if not target_date:
        target_date = date.today().isoformat()

    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        raise ValueError("GARMIN_EMAIL und GARMIN_PASSWORD müssen in .env gesetzt sein.")

    # Garmin Client Initialisierung
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()

    # API Abrufe
    stats = client.get_stats(target_date)
    sleep_data = client.get_sleep_data(target_date)
    hrv_data = client.get_hrv_data(target_date)

    # Daten-Transformation & Fallbacks
    resting_hr = stats.get("restingHeartRate")
    steps = stats.get("totalSteps")
    stress_avg = stats.get("averageStressLevel")
    
    # Schlafstunden / Score extrahieren
    sleep_score = None
    sleep_hours = None
    if sleep_data and "dailySleepDTO" in sleep_data:
        dto = sleep_data["dailySleepDTO"]
        sleep_score = dto.get("sleepScores", {}).get("overall", {}).get("value")
        sleep_seconds = dto.get("sleepTimeSeconds", 0)
        sleep_hours = round(sleep_seconds / 3600.0, 2) if sleep_seconds else None

    # HRV Auswertung
    avg_hrv = None
    if hrv_data and "hrvSummary" in hrv_data:
        avg_hrv = hrv_data["hrvSummary"].get("weeklyAvg") or hrv_data["hrvSummary"].get("lastNightAvg")

    db_payload = {
        "date": target_date,
        "resting_hr": resting_hr,
        "avg_hrv": avg_hrv,
        "sleep_score": sleep_score,
        "sleep_hours": sleep_hours,
        "body_battery_max": stats.get("bodyBatteryChargedValue"),
        "body_battery_min": stats.get("bodyBatteryDrainedValue"),
        "stress_avg": stress_avg,
        "steps": steps,
        "raw_json": json.dumps({"stats": stats, "sleep": sleep_data, "hrv": hrv_data})
    }

    save_garmin_data(db_payload)
    return db_payload

if __name__ == "__main__":
    print("Teste Garmin-Import für heute...")
    res = fetch_and_store_garmin_data()
    print("Erfolgreich importiert:", res)