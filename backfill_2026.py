from datetime import date
from garminconnect import GarminConnectTooManyRequestsError
from garmin_auth import get_garmin_client
from garmin_backfill import run_backfill
from db import init_db


def _print_progress(current_date, status, success_count, error_count, total_days):
    if status == "ok":
        print(" ✅")
    elif status == "rate_limited":
        print(f" 🛑 Rate-Limit erreicht bei {current_date.isoformat()}")
        print("Breche komplett ab, um die Sperre nicht zu verlängern.")
    else:
        print(" ❌ Fehler")
    print(f"⏳ Lade [{current_date.isoformat()}]...", end="", flush=True)


def backfill_year_2026():
    init_db()

    start_date = date(2026, 7, 28)
    end_date = date.today()

    print("🚀 Verbinde mit Garmin...")
    try:
        client = get_garmin_client()
    except GarminConnectTooManyRequestsError as e:
        print(f"🛑 Rate-Limit beim Login: {e}")
        print("Breche ab, ohne einen weiteren Versuch zu machen.")
        return

    total_days = (end_date - start_date).days + 1
    print(f"🚀 Starte Daten-Import ({total_days} Tage von {start_date} bis {end_date})...")
    print(f"⏳ Lade [{start_date.isoformat()}]...", end="", flush=True)

    success_count, error_count, stopped_early = run_backfill(
        start_date, end_date, client, on_progress=_print_progress
    )

    print(f"\n🎉 Import abgeschlossen! Erfolgreich: {success_count}, Fehler: {error_count}")


if __name__ == "__main__":
    backfill_year_2026()
