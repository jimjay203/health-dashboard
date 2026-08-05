"""
Automatischer Sync-Trigger via Schlafdaten-Checker (Zwischenschritt vor der Heute-Ansicht).
Reine Python-Logik, kein Streamlit-/FastAPI-Import (Portabilitäts-Prinzip, analog zu
daily_summary.py/insight_memory.py) - läuft aktuell als asyncio-Hintergrund-Task im
FastAPI-Backend (siehe backend/main.py).

Ground-Truth-Hinweis: client.get_sleep_data(date) liefert IMMER ein "dailySleepDTO"-Objekt
zurück, auch für Tage ganz ohne Daten (live gegen ein Zukunftsdatum verifiziert) - nur mit
durchgehend null-Feldern. "dailySleepDTO" in der Antwort ist deshalb KEIN zuverlässiges
Verfügbarkeits-Signal. Zuverlässig ist dailySleepDTO.sleepTimeSeconds (None/0 ohne Daten, sonst
der reale Sekundenwert) - dieselbe Feld-Konvention, die garmin_service.py bereits für
sleep_hours nutzt.
"""
import asyncio
from datetime import date, datetime, time as dt_time, timedelta

from garminconnect import GarminConnectTooManyRequestsError
from garmin_auth import get_garmin_client
from garmin_service import fetch_and_store_garmin_data
from daily_recommendation import generate_daily_recommendation
from weekly_planner import generate_weekly_plan, get_week_plan
from db import get_connection, upsert_daily_metric

AUTO_SYNC_START_TIME = dt_time(6, 0)
AUTO_SYNC_CUTOFF_TIME = dt_time(12, 0)
# Bewusst nicht enger als 20-30 Min., auch wenn manuelle App-Nutzung bisher keine 429-Fehler
# gezeigt hat - zu kleine Stichprobe, um daraus ein engeres Intervall abzuleiten (siehe
# bestehendes, ebenso vorsichtiges 429-Handling in garmin_service.py/garmin_backfill.py).
AUTO_SYNC_CHECK_INTERVAL_SECONDS = 25 * 60


def check_sleep_data_available(client, target_date):
    """Leichtgewichtiger Check (nur get_sleep_data, kein voller Sync). Gibt (bool, Fehlermeldung
    oder None) zurück. Ein 429 wird durchgereicht - run_auto_sync_loop() entscheidet, ob
    abgebrochen wird, statt es hier stillschweigend zu schlucken."""
    try:
        sleep_data = client.get_sleep_data(target_date)
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as e:
        return False, str(e)

    dto = (sleep_data or {}).get("dailySleepDTO") or {}
    sleep_seconds = dto.get("sleepTimeSeconds")
    return bool(sleep_seconds), None


def _current_row(cursor, target_date):
    return cursor.execute(
        "SELECT * FROM auto_sync_status WHERE date = ?", (target_date,)
    ).fetchone()


def get_status(target_date=None):
    """Für GET /api/sync-status: Zeile für target_date (Default heute) oder ein
    "noch nicht gestartet"-Default, plus ein abgeleitetes lesbares status-Feld."""
    target_date = target_date or date.today().isoformat()
    conn = get_connection()
    row = _current_row(conn.cursor(), target_date)
    conn.close()

    if not row:
        return {
            "date": target_date, "first_check_at": None, "last_check_at": None,
            "check_count": 0, "sleep_data_found": False, "full_sync_completed_at": None,
            "gave_up_at": None, "last_error": None, "status": "not_started",
        }

    result = dict(row)
    result["sleep_data_found"] = bool(result["sleep_data_found"])
    if result["full_sync_completed_at"]:
        result["status"] = "completed"
    elif result["gave_up_at"]:
        result["status"] = "gave_up"
    elif result["check_count"]:
        result["status"] = "checking"
    else:
        result["status"] = "not_started"
    return result


def _mark_check(target_date, found, error=None):
    conn = get_connection()
    cursor = conn.cursor()
    existing = _current_row(cursor, target_date)
    check_count = (existing["check_count"] if existing else 0) + 1
    first_check_at = (
        existing["first_check_at"] if existing and existing["first_check_at"]
        else datetime.now().isoformat()
    )
    conn.close()

    upsert_daily_metric("auto_sync_status", {
        "date": target_date,
        "first_check_at": first_check_at,
        "last_check_at": datetime.now().isoformat(),
        "check_count": check_count,
        "sleep_data_found": int(found),
        "last_error": error,
    })


def _mark_sync_completed(target_date):
    upsert_daily_metric("auto_sync_status", {
        "date": target_date,
        "full_sync_completed_at": datetime.now().isoformat(),
    })


def _mark_gave_up(target_date):
    upsert_daily_metric("auto_sync_status", {
        "date": target_date,
        "gave_up_at": datetime.now().isoformat(),
    })


async def _sleep_until(target_time, now_fn):
    """Wartet bis now_fn() >= target_time (heutiges Datum von now_fn())."""
    now = now_fn()
    target_dt = datetime.combine(now.date(), target_time)
    if now >= target_dt:
        return
    await asyncio.sleep((target_dt - now).total_seconds())


async def run_auto_sync_loop(
    target_date=None,
    start_time=AUTO_SYNC_START_TIME,
    cutoff_time=AUTO_SYNC_CUTOFF_TIME,
    interval_seconds=AUTO_SYNC_CHECK_INTERVAL_SECONDS,
    check_fn=check_sleep_data_available,
    sync_fn=fetch_and_store_garmin_data,
    client_factory=get_garmin_client,
    recommendation_fn=generate_daily_recommendation,
    now_fn=datetime.now,
):
    """Eine Tages-Schleife: wartet bis start_time, prüft dann im interval_seconds-Takt bis
    cutoff_time, ob Schlafdaten vorliegen - bei Treffer einmaliger voller Sync, sonst nach
    cutoff_time als "aufgegeben" markiert. Alle Parameter austauschbar (siehe
    examples/test_auto_sync.py) - damit lässt sich der komplette Ablauf ohne Warten auf echte
    Uhrzeiten durchspielen. Garmin-Aufrufe laufen über asyncio.to_thread(), da garminconnect eine
    blockierende Bibliothek ist und der FastAPI-Event-Loop sonst während eines Syncs einfrieren
    würde."""
    target_date = target_date or now_fn().date().isoformat()

    existing = get_status(target_date)
    if existing["status"] in ("completed", "gave_up"):
        return existing["status"]

    await _sleep_until(start_time, now_fn)

    client = None
    while now_fn().time() < cutoff_time:
        try:
            if client is None:
                client = await asyncio.to_thread(client_factory)
            found, error = await asyncio.to_thread(check_fn, client, target_date)
        except GarminConnectTooManyRequestsError as e:
            _mark_check(target_date, False, error=f"429: {e}")
            return "rate_limited"

        _mark_check(target_date, found, error=error)
        if found:
            await asyncio.to_thread(sync_fn, target_date, client)
            _mark_sync_completed(target_date)
            # Best effort: die Heute-Ansicht (siehe daily_recommendation.py) hat einen eigenen
            # Lazy-Fallback für fehlende/fehlgeschlagene Empfehlungen - ein Gemini-Fehler hier darf
            # den bereits erfolgreichen Sync-Status daher nicht kippen, nur geloggt werden.
            try:
                await asyncio.to_thread(recommendation_fn, target_date)
            except Exception as e:
                print(f"⚠️  auto_sync: Empfehlungsgenerierung fehlgeschlagen: {e}")
            return "completed"

        await asyncio.sleep(interval_seconds)

    _mark_gave_up(target_date)
    return "gave_up"


async def _maybe_run_weekly_planner(weekly_planner_fn, now_fn):
    """Sonntags, nach erfolgreichem Tages-Sync, den Wochenplaner für die kommende UND die
    übernächste Woche anstoßen (siehe weekly_planner.py) - zwei konkrete, mit Workouts
    durchgeplante Wochen sollen jederzeit sichtbar sein. Kein neuer Scheduler, hängt direkt an der
    bestehenden Tages-Schleife in run_daily_auto_sync_forever(). Idempotenz-Check pro Woche direkt
    gegen weekly_plan selbst (kein zusätzliches Tracking nötig) - dadurch bekommt jede Woche genau
    einmal einen Plan, zwei Sonntage vor ihrem Montag (als "übernächste" Woche), nicht noch einmal
    kurz davor überschrieben (würde sonst bereits hochgeladene/angepasste Entwürfe verwerfen).
    Best effort: ein Fehler hier darf den bereits erfolgreichen Tages-Sync-Status nicht kippen,
    wird nur geloggt."""
    now = now_fn()
    if now.date().isoweekday() != 7:  # nur sonntags (1=Montag..7=Sonntag)
        return
    next_monday = now.date() + timedelta(days=1)
    for target_monday in (next_monday, next_monday + timedelta(days=7)):
        target_date = target_monday.isoformat()
        try:
            already_planned = await asyncio.to_thread(get_week_plan, target_date)
            if already_planned:
                continue
            await asyncio.to_thread(weekly_planner_fn, target_date)
        except Exception as e:
            print(f"⚠️  auto_sync: Wochenplanung für {target_date} fehlgeschlagen: {e}")


async def run_daily_auto_sync_forever(
    start_time=AUTO_SYNC_START_TIME,
    cutoff_time=AUTO_SYNC_CUTOFF_TIME,
    interval_seconds=AUTO_SYNC_CHECK_INTERVAL_SECONDS,
    weekly_planner_fn=generate_weekly_plan,
    now_fn=datetime.now,
):
    """Dauerlauf-Wrapper um run_auto_sync_loop() - läuft, solange der FastAPI-Prozess lebt (siehe
    backend/main.py, Lifespan-Hintergrund-Task). Wiederholt die Tages-Schleife jeden Tag neu,
    statt nur einmal nach Container-Start zu laufen (der Container läuft potenziell wochenlang
    durch, restart: unless-stopped)."""
    while True:
        try:
            status = await run_auto_sync_loop(
                start_time=start_time, cutoff_time=cutoff_time,
                interval_seconds=interval_seconds, now_fn=now_fn,
            )
            if status == "completed":
                await _maybe_run_weekly_planner(weekly_planner_fn, now_fn)
        except Exception as e:
            print(f"⚠️  auto_sync: unerwarteter Fehler in der Tages-Schleife: {e}")

        now = now_fn()
        next_start_date = now.date() if now.time() < start_time else now.date() + timedelta(days=1)
        next_start_dt = datetime.combine(next_start_date, start_time)
        await asyncio.sleep(max((next_start_dt - now).total_seconds(), 0))
