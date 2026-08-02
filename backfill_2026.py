import os
import time
from datetime import date, timedelta
from garminconnect import Garmin
from garmin_service import fetch_and_store_garmin_data
from db import init_db

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")

def backfill_year_2026():
    init_db()
    
    start_date = date(2026, 7, 28)
    end_date = date.today()
    
    current_date = start_date
    total_days = (end_date - start_date).days + 1
    
    print(f"🚀 Einloggen bei Garmin Connect...")
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()
    print("✅ Login erfolgreich!")
    
    print(f"🚀 Starte Daten-Import für 2026 ({total_days} Tage von {start_date} bis {end_date})...")
    
    success_count = 0
    error_count = 0

    while current_date <= end_date:
        date_str = current_date.isoformat()
        print(f"⏳ Lade [{date_str}]...", end="", flush=True)
        
        try:
            fetch_and_store_garmin_data(date_str, client=client)
            print(" ✅")
            success_count += 1
        except Exception as e:
            print(f" ❌ Fehler: {e}")
            error_count += 1
            
        current_date += timedelta(days=1)
        # 2 Sekunden Pause zwischen API-Requests schont Garmin-Server
        time.sleep(2)

    print("\n🎉 Import abgeschlossen!")
    print(f"Erfolgreich: {success_count} Tage")
    print(f"Fehlerhaft:  {error_count} Tage")

if __name__ == "__main__":
    backfill_year_2026()