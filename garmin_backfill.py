import time
import random
from datetime import date, timedelta
from garminconnect import GarminConnectTooManyRequestsError
from garmin_service import fetch_and_store_garmin_data


def run_backfill(start_date: date, end_date: date, client, on_progress=None):
    """Lädt Garmin-Daten für jeden Tag zwischen start_date und end_date (inklusive).

    on_progress: optionales Callback(current_date, status, success_count, error_count, total_days),
    das nach jedem Tag aufgerufen wird - status ist "ok", "error" oder "rate_limited".

    Gibt (success_count, error_count, stopped_early) zurück.
    """
    if start_date > end_date:
        raise ValueError("Startdatum muss vor oder gleich dem Enddatum liegen.")

    current_date = start_date
    total_days = (end_date - start_date).days + 1
    success_count = 0
    error_count = 0
    stopped_early = False

    while current_date <= end_date:
        date_str = current_date.isoformat()

        try:
            fetch_and_store_garmin_data(date_str, client=client)
            success_count += 1
            if on_progress:
                on_progress(current_date, "ok", success_count, error_count, total_days)
            current_date += timedelta(days=1)
            time.sleep(random.uniform(3, 6))
        except GarminConnectTooManyRequestsError as e:
            if on_progress:
                on_progress(current_date, "rate_limited", success_count, error_count, total_days)
            stopped_early = True
            break
        except Exception as e:
            if "429" in str(e):
                if on_progress:
                    on_progress(current_date, "rate_limited", success_count, error_count, total_days)
                stopped_early = True
                break
            error_count += 1
            if on_progress:
                on_progress(current_date, "error", success_count, error_count, total_days)
            current_date += timedelta(days=1)
            time.sleep(random.uniform(3, 6))

    return success_count, error_count, stopped_early
