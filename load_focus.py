"""
Belastungsfokus-Verteilung (niedrig-/hoch-aerob/anaerob) aus den App-eigenen Friel-HF-Zonen
(siehe training_zones.py) statt aus Garmins eigenen vorberechneten hrTimeInZone_1..5-Werten
(garmin_activities.hr_zone_1..5). Reine Python-Logik, kein Streamlit-/FastAPI-Import - geteilt
zwischen backend/routers/performance.py und performance_insight.py (beide root-level-Module
dürfen das importieren, siehe performance_insight.py-Docstring zur Docker-Flattening-Struktur).

Ground-Truth-Fund (2026-08-07): Garmins eigene Zonenkonfiguration weicht für dieses Konto massiv
von der schwellen-HF-basierten Friel-Einteilung ab - an 12 Läufen im 28-Tage-Fenster verglichen:
Garmin-Zonen ergaben 5% niedrig-aerob, dieselben Rohdaten neu klassifiziert nach den App-eigenen
Friel-Zonen ergaben 86% niedrig-aerob (vermutlich, weil Garmins Zonen nicht auf der aktuellen
Schwellen-HF basieren). Diese Berechnung nutzt deshalb die Sekunden-HF-Zeitreihe
(garmin_activity_details) statt der vorberechneten Zonen-Werte.

Einschränkungen (bewusst, nicht verschwiegen): nur für Aktivitäten mit synchronisierter Detail-
Zeitreihe (has_details_synced=1) UND einem Sportart-Typ mit eigenem Friel-Zonensystem in dieser
App möglich (Laufen/Rad - siehe ZONE_TABLE_BY_ACTIVITY_TYPE; Schwimmen/Multisport/Kraft etc. haben
kein eigenes HF-Zonensystem hier und werden ausgeschlossen). Zonen-Snapshots existieren zudem nur
für "heute"-Syncs (siehe training_zones.py::recompute_zones, NICHT für jeden Backfill-Tag) - für
eine Aktivität wird deshalb der neueste Snapshot <= Aktivitätsdatum verwendet, sonst der früheste
verfügbare (gleiches Fallback-Prinzip wie backend/routers/performance.py::_metric_value).
included_activities/total_activities_in_window machen transparent, wie viel der berechneten
Verteilung tatsächlich zugrunde liegt.
"""
from datetime import date, timedelta
from db import get_connection

LOAD_FOCUS_WINDOW_DAYS = 28

ZONE_TABLE_BY_ACTIVITY_TYPE = {
    "running": "training_zones_running",
    "cycling": "training_zones_cycling_hr",
    "road_biking": "training_zones_cycling_hr",
}

ZONE_LABELS_LOW_AEROBIC = {"1", "2"}
ZONE_LABELS_HIGH_AEROBIC = {"3"}
# Alles andere (4, 5a, 5b, 5c) zählt als anaerob.


def _zone_bounds_for_date(cursor, table, target_date):
    row = cursor.execute(f"SELECT MAX(date) AS d FROM {table} WHERE date <= ?", (target_date,)).fetchone()
    snapshot_date = row["d"]
    if not snapshot_date:
        row = cursor.execute(f"SELECT MIN(date) AS d FROM {table}").fetchone()
        snapshot_date = row["d"]
    if not snapshot_date:
        return None
    rows = cursor.execute(f"SELECT zone, hr_min, hr_max FROM {table} WHERE date = ?", (snapshot_date,)).fetchall()
    return [(r["zone"], r["hr_min"], r["hr_max"]) for r in rows]


def _classify_hr(hr, bounds):
    for label, lo, hi in bounds:
        if (lo is None or hr >= lo) and (hi is None or hr <= hi):
            return label
    return None


def _activity_zone_seconds(cursor, activity_id, bounds):
    """Klassifiziert jeden Sekunden-HF-Messpunkt (timestamp in ms, siehe garmin_activity_details-
    Schema) nach bounds und summiert die Zeit bis zum jeweils nächsten Messpunkt - dieselbe
    Bucket-Logik wie die manuelle Ad-hoc-Analyse, jetzt fest im Code. None, falls weniger als zwei
    verwertbare Messpunkte vorliegen (Aktivität ohne echte HF-Zeitreihe)."""
    rows = cursor.execute(
        "SELECT timestamp, heart_rate FROM garmin_activity_details WHERE activity_id = ? ORDER BY seq",
        (activity_id,)
    ).fetchall()
    hr_ts = [(r["timestamp"], r["heart_rate"]) for r in rows if r["timestamp"] is not None and r["heart_rate"] is not None]
    if len(hr_ts) < 2:
        return None
    hr_ts.sort()

    seconds = {"low": 0.0, "high": 0.0, "anaerobic": 0.0}
    for i in range(len(hr_ts) - 1):
        t0, hr0 = hr_ts[i]
        t1, _ = hr_ts[i + 1]
        dt = max(0.0, (t1 - t0) / 1000.0)
        label = _classify_hr(hr0, bounds)
        if label in ZONE_LABELS_LOW_AEROBIC:
            seconds["low"] += dt
        elif label in ZONE_LABELS_HIGH_AEROBIC:
            seconds["high"] += dt
        elif label is not None:
            seconds["anaerobic"] += dt
    return seconds


def compute_load_focus(target_date, window_days=LOAD_FOCUS_WINDOW_DAYS):
    """Belastungsfokus-Verteilung über die letzten window_days Tage bis einschließlich target_date.
    Gibt ein Dict mit low_aerobic_pct/high_aerobic_pct/anaerobic_pct (None, falls gar keine
    Aktivität einbezogen werden konnte) sowie included_activities/total_activities_in_window für
    Transparenz zurück."""
    start = (date.fromisoformat(target_date) - timedelta(days=window_days)).isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    activities = cursor.execute(
        "SELECT activity_id, activity_type, date(start_time_local) AS d, has_details_synced "
        "FROM garmin_activities WHERE date(start_time_local) >= ? AND date(start_time_local) <= ?",
        (start, target_date)
    ).fetchall()

    total_low = total_high = total_anaerobic = 0.0
    included_count = 0
    zone_bounds_cache = {}

    for a in activities:
        table = ZONE_TABLE_BY_ACTIVITY_TYPE.get(a["activity_type"])
        if not table or not a["has_details_synced"]:
            continue
        cache_key = (table, a["d"])
        if cache_key not in zone_bounds_cache:
            zone_bounds_cache[cache_key] = _zone_bounds_for_date(cursor, table, a["d"])
        bounds = zone_bounds_cache[cache_key]
        if not bounds:
            continue
        seconds = _activity_zone_seconds(cursor, a["activity_id"], bounds)
        if seconds is None:
            continue
        total_low += seconds["low"]
        total_high += seconds["high"]
        total_anaerobic += seconds["anaerobic"]
        included_count += 1

    conn.close()

    total_seconds = total_low + total_high + total_anaerobic
    result = {
        "low_aerobic_pct": None,
        "high_aerobic_pct": None,
        "anaerobic_pct": None,
        "included_activities": included_count,
        "total_activities_in_window": len(activities),
    }
    if total_seconds > 0:
        result["low_aerobic_pct"] = total_low / total_seconds * 100
        result["high_aerobic_pct"] = total_high / total_seconds * 100
        result["anaerobic_pct"] = total_anaerobic / total_seconds * 100
    return result
