"""
Withings-Waagen-Sync: holt Messwerte direkt bei Withings (statt über Garmins lückenhafte
Weiterleitung) und speichert sie in withings_weigh_ins. Reine Python-Logik, kein Streamlit-Import.

Ground-Truth: siehe withings_auth.py-Docstring für den verifizierten API-Vertrag. Messwerte-
Endpunkt bewusst wbsapi.withings.net/measure (kein "v2"-Präfix) - exakt der Pfad, den die
withings-api-Referenzbibliothek für measure_get_meas nutzt, dort real funktionierend verifiziert.
"""
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from withings_auth import get_withings_tokens
from db import upsert_by_key

MEASURE_URL = "https://wbsapi.withings.net/measure"

MEASURE_TYPE_WEIGHT = 1
MEASURE_TYPE_FAT_RATIO = 6
MEASURE_TYPE_FAT_MASS = 8
MEASURE_TYPE_MUSCLE_MASS = 76
MEASURE_TYPE_HYDRATION = 77
MEASURE_TYPE_BONE_MASS = 88

CATEGORY_REAL = 1  # schließt reine Nutzer-Zielvorgaben (category=2) aus

ATTRIB_LABELS = {
    0: "device_entry",
    1: "device_entry_ambiguous",
    2: "manual_entry",
    4: "manual_entry_account_creation",
    5: "measure_auto",
    7: "measure_user_confirmed",
    8: "same_as_device_entry",
}


def _measure_value(measures, measure_type):
    for m in measures:
        if m["type"] == measure_type:
            return m["value"] * (10 ** m["unit"])
    return None


def _store_measure_group(group, local_date):
    """Extrahiert unsere MEASURE_TYPE_*-Auswahl aus einer einzelnen Withings-Messgruppe und
    speichert sie - geteilt zwischen fetch_and_store_withings_data (ein Tag) und
    fetch_full_withings_history (komplette Historie). Gibt True zurück, wenn tatsächlich etwas
    gespeichert wurde (False bei einer Messgruppe, die nur Typen außerhalb unserer Auswahl enthält,
    z.B. Herzfrequenz einer Impedanzwaage)."""
    measures = group.get("measures") or []
    values = {
        "weight": _measure_value(measures, MEASURE_TYPE_WEIGHT),
        "body_fat": _measure_value(measures, MEASURE_TYPE_FAT_RATIO),
        "body_water": _measure_value(measures, MEASURE_TYPE_HYDRATION),
        "bone_mass": _measure_value(measures, MEASURE_TYPE_BONE_MASS),
        "muscle_mass": _measure_value(measures, MEASURE_TYPE_MUSCLE_MASS),
        "fat_mass_kg": _measure_value(measures, MEASURE_TYPE_FAT_MASS),
    }
    if all(v is None for v in values.values()):
        return False

    upsert_by_key("withings_weigh_ins", "grpid", {
        "grpid": group["grpid"],
        "date": local_date,
        **values,
        "attrib": ATTRIB_LABELS.get(group.get("attrib"), str(group.get("attrib"))),
        "timestamp": group["date"],
    })
    return True


def fetch_and_store_withings_data(target_date):
    """Holt alle Withings-Messgruppen für target_date (YYYY-MM-DD, lokaler Kalendertag laut
    Withings' eigener timezone-Angabe) und speichert sie. Gibt die Anzahl gespeicherter
    Messgruppen zurück."""
    tokens = get_withings_tokens()

    day = datetime.strptime(target_date, "%Y-%m-%d")
    # startdate/enddate sind UTC-Unix-Zeitstempel, das exakte lokale Tagesfenster kennen wir erst
    # aus der Antwort (body.timezone) - Fenster bewusst einen Tag auf jeder Seite größer als
    # nötig anfragen, endgültige Zuordnung zu target_date danach anhand der lokalen Zeit filtern.
    window_start = day - timedelta(days=1)
    window_end = day + timedelta(days=2)

    response = requests.get(
        MEASURE_URL,
        params={
            "action": "getmeas",
            "access_token": tokens["access_token"],
            "category": CATEGORY_REAL,
            "startdate": int(window_start.replace(tzinfo=timezone.utc).timestamp()),
            "enddate": int(window_end.replace(tzinfo=timezone.utc).timestamp()),
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != 0:
        raise RuntimeError(f"Withings-Messwerte-Abruf fehlgeschlagen (status={payload.get('status')}): {payload}")

    body = payload["body"]
    tz = ZoneInfo(body.get("timezone") or "UTC")
    groups = body.get("measuregrps") or []

    count = 0
    for group in groups:
        local_date = datetime.fromtimestamp(group["date"], tz=tz).strftime("%Y-%m-%d")
        if local_date != target_date:
            continue
        if _store_measure_group(group, local_date):
            count += 1

    return count


def fetch_full_withings_history():
    """Einmaliger Voll-Import statt des engen Tagesfensters von fetch_and_store_withings_data() -
    für den initialen Import der kompletten bei Withings vorliegenden Mess-Historie. Kein
    startdate/enddate (keine Einschränkung des Zeitraums), stattdessen Paginierung über
    body.more/body.offset (ground-truth: Withings-API-Referenz measure-getmeas sowie die
    Referenzbibliothek python_withings_api - "more:1 und offset:XX in der Antwort -> offset in den
    nächsten Aufruf übernehmen, bis more nicht mehr gesetzt ist"). Gibt die Anzahl gespeicherter
    Messgruppen zurück."""
    tokens = get_withings_tokens()

    count = 0
    offset = None
    while True:
        params = {
            "action": "getmeas",
            "access_token": tokens["access_token"],
            "category": CATEGORY_REAL,
        }
        if offset:
            params["offset"] = offset

        response = requests.get(MEASURE_URL, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != 0:
            raise RuntimeError(f"Withings-Messwerte-Abruf fehlgeschlagen (status={payload.get('status')}): {payload}")

        body = payload["body"]
        tz = ZoneInfo(body.get("timezone") or "UTC")
        groups = body.get("measuregrps") or []

        for group in groups:
            local_date = datetime.fromtimestamp(group["date"], tz=tz).strftime("%Y-%m-%d")
            if _store_measure_group(group, local_date):
                count += 1

        if not body.get("more"):
            break
        offset = body.get("offset")
        if not offset:
            break
        time.sleep(0.5)

    return count
