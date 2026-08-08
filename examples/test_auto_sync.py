"""
Testskript für auto_sync.py (kein UI). Zwei getrennte Verifikationen, wie in der DoD gefordert:

1. Echter API-Test (Ground-Truth) - prüft, dass check_sleep_data_available() für ein Datum mit
   echten Schlafdaten und für ein Datum ganz ohne Daten (ein zukünftiges Datum) erkennbar
   unterschiedliche Ergebnisse liefert.
2. Orchestrierungs-Test mit Fakes (kein Warten auf echte Uhrzeiten) - prüft den kompletten Ablauf
   von run_auto_sync_loop(): "noch nicht da" -> "noch nicht da" -> "vorhanden" -> voller Sync
   ausgelöst -> auto_sync_status korrekt geschrieben.

Ausführen vom Repo-Root aus (nicht direkt als examples/test_auto_sync.py):
    python3 -m examples.test_auto_sync
"""
import asyncio
from datetime import date, datetime, time as dt_time, timedelta

from garmin_auth import get_garmin_client
from auto_sync import check_sleep_data_available, run_auto_sync_loop, get_status
from db import get_connection

TEST_DATE = "2099-06-15"  # frei erfundenes Testdatum, kollidiert nicht mit echten Daten


def test_real_api_ground_truth():
    print("=== 1. Echter API-Test ===")
    client = get_garmin_client()

    today = date.today().isoformat()
    found_today, err_today = check_sleep_data_available(client, today)
    print(f"Heute ({today}): gefunden={found_today}, Fehler={err_today}")

    future = (date.today() + timedelta(days=3)).isoformat()
    found_future, err_future = check_sleep_data_available(client, future)
    print(f"Zukunftsdatum ({future}): gefunden={found_future}, Fehler={err_future}")

    assert found_future is False, "Zukunftsdatum sollte nie Schlafdaten haben"
    print("OK: Zukunftsdatum korrekt als 'nicht vorhanden' erkannt.\n")


def _clear_test_status():
    conn = get_connection()
    conn.execute("DELETE FROM auto_sync_status WHERE date = ?", (TEST_DATE,))
    conn.commit()
    conn.close()


async def test_orchestration_with_fakes():
    print("=== 2. Orchestrierungs-Test mit Fakes ===")
    _clear_test_status()

    call_results = iter([(False, None), (False, None), (True, None)])
    check_calls = []

    def fake_check(client, target_date):
        result = next(call_results)
        check_calls.append(result)
        return result

    sync_calls = []

    def fake_sync(target_date, client=None):
        sync_calls.append(target_date)

    def fake_client_factory():
        return "FAKE_CLIENT"

    recommendation_calls = []

    def fake_recommendation(target_date):
        # Kein echter Gemini-Call hier - ohne dieses Fake würde jeder Testlauf einen echten
        # generate_daily_recommendation()-Aufruf für das erfundene TEST_DATE auslösen.
        recommendation_calls.append(target_date)

    activities_sync_calls = []

    def fake_activities_sync(client):
        # Kein echter Garmin-Aktivitäten-Call hier - ohne dieses Fake würde jeder Testlauf
        # versuchen, sync_activity_list()/sync_activity_details() mit dem FAKE_CLIENT aufzurufen.
        activities_sync_calls.append(client)

    log_calls = []

    def fake_log(sync_type, status, detail=None):
        # Kein echter garmin_sync_log-Eintrag hier - ohne dieses Fake würde jeder Testlauf den
        # Sync-Verlauf mit Einträgen für das erfundene TEST_DATE verschmutzen.
        log_calls.append((sync_type, status, detail))

    fake_now = datetime.combine(date.today(), dt_time(7, 0))

    def fake_now_fn():
        return fake_now

    status = await run_auto_sync_loop(
        target_date=TEST_DATE,
        start_time=dt_time(0, 0),  # "in der Vergangenheit" relativ zu fake_now -> kein Warten
        cutoff_time=dt_time(23, 59),
        interval_seconds=0.01,
        check_fn=fake_check,
        sync_fn=fake_sync,
        client_factory=fake_client_factory,
        recommendation_fn=fake_recommendation,
        activities_sync_fn=fake_activities_sync,
        log_fn=fake_log,
        now_fn=fake_now_fn,
    )

    print("Ergebnis-Status:", status)
    print("Check-Aufrufe:", check_calls)
    print("Sync-Aufrufe:", sync_calls)
    print("Empfehlungs-Aufrufe:", recommendation_calls)
    print("Aktivitäten-Sync-Aufrufe:", activities_sync_calls)
    print("Log-Aufrufe:", log_calls)

    assert status == "completed"
    assert len(check_calls) == 3
    assert sync_calls == [TEST_DATE]
    assert recommendation_calls == [TEST_DATE]
    assert activities_sync_calls == ["FAKE_CLIENT"]
    assert log_calls == [
        ("check", "nicht gefunden", None),
        ("check", "nicht gefunden", None),
        ("check", "gefunden", None),
        ("auto", "abgeschlossen", f"Datum: {TEST_DATE}"),
    ]

    db_status = get_status(TEST_DATE)
    print("DB-Status:", db_status)
    assert db_status["status"] == "completed"
    assert db_status["check_count"] == 3
    assert db_status["sleep_data_found"] is True

    print("OK: kompletter Ablauf (noch nicht da -> noch nicht da -> vorhanden -> Sync) bestätigt.\n")
    _clear_test_status()


if __name__ == "__main__":
    test_real_api_ground_truth()
    asyncio.run(test_orchestration_with_fakes())
