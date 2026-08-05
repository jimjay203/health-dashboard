"""
Withings-Waagen-Sync: holt Messwerte direkt bei Withings (statt über Garmins lückenhafte
Weiterleitung) und speichert sie in withings_weigh_ins. Reine Python-Logik, kein Streamlit-Import.

Ground-Truth: siehe withings_auth.py-Docstring für den verifizierten API-Vertrag. Messwerte-
Endpunkt bewusst wbsapi.withings.net/measure (kein "v2"-Präfix) - exakt der Pfad, den die
withings-api-Referenzbibliothek für measure_get_meas nutzt, dort real funktionierend verifiziert.
"""
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
            # Messgruppe enthält ausschließlich Typen außerhalb unserer MEASURE_TYPE_*-Auswahl
            # (z.B. Herzfrequenz einer Impedanzwaage) - nichts Sinnvolles zu speichern.
            continue

        upsert_by_key("withings_weigh_ins", "grpid", {
            "grpid": group["grpid"],
            "date": local_date,
            **values,
            "attrib": ATTRIB_LABELS.get(group.get("attrib"), str(group.get("attrib"))),
            "timestamp": group["date"],
        })
        count += 1

    return count
