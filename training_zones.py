"""
Trainingszonen nach Joe Friels 7-Zonen-Modell (Lauf-/Rad-HF, Lauf-Pace) bzw. 6-Zonen-Modell
(Rad-Leistung). Wird nach jedem "heute"-Sync automatisch aus garmin_lactate_threshold und
garmin_cycling_ftp neu berechnet (siehe garmin_service.fetch_and_store_garmin_data) und
historisch mit Datum in eigenen Tabellen abgelegt - kein Upsert, jeder Lauf ersetzt nur den
Zonen-"Snapshot" des jeweiligen Tages (siehe db.replace_timeseries).
"""
from db import get_connection, replace_timeseries

# (Zonen-Label, unterer %-Grenzwert oder None für offenes Ende, oberer %-Grenzwert oder None)
# Werte 1:1 aus der Vorgabe übernommen. Friels Bänder haben zwischen benachbarten Zonen kleine
# Lücken (z.B. 89% -> 90%); die werden über _close_integer_gaps()/_close_continuous_gaps()
# unten lückenlos gemacht, statt sie so stehen zu lassen.
RUNNING_HR_ZONES_PCT = [
    ("1", None, 0.85),
    ("2", 0.85, 0.89),
    ("3", 0.90, 0.94),
    ("4", 0.95, 0.99),
    ("5a", 1.00, 1.02),
    ("5b", 1.03, 1.06),
    ("5c", 1.06, None),
]

# Pace in % der Schwellenpace - höherer % = langsamer (mehr Sekunden/km). low_pct/high_pct sind
# hier bewusst nicht "numerisch min/max", sondern die beiden Prozent-Grenzen der Zone in der
# Reihenfolge aus der Vorgabe; die tatsächliche min/max-Zuordnung passiert in _pace_zone_rows().
RUNNING_PACE_ZONES_PCT = [
    ("1", 1.29, None),   # langsamer als 129%
    ("2", 1.14, 1.29),
    ("3", 1.06, 1.13),
    ("4", 0.99, 1.05),
    ("5a", 0.97, 1.00),
    ("5b", 0.90, 0.96),
    ("5c", None, 0.90),  # schneller als 90%
]

CYCLING_HR_ZONES_PCT = [
    ("1", None, 0.81),
    ("2", 0.81, 0.89),
    ("3", 0.90, 0.93),
    ("4", 0.94, 0.99),
    ("5a", 1.00, 1.02),
    ("5b", 1.03, 1.06),
    ("5c", 1.06, None),
]

# Friel-Leistungszonen sind ein 6-Zonen-Modell, bewusst nicht auf 7 gestreckt.
CYCLING_POWER_ZONES_PCT = [
    ("1", None, 0.55),
    ("2", 0.55, 0.74),
    ("3", 0.75, 0.89),
    ("4", 0.90, 1.04),
    ("5", 1.05, 1.20),
    ("6", 1.20, None),
]


def zone_bounds_for_date(cursor, table, target_date):
    """Neuester Zonen-Snapshot <= target_date aus table, sonst der früheste verfügbare (Zonen-
    Snapshots existieren nur für "heute"-Syncs, nicht für jeden Backfill-Tag - siehe
    recompute_zones-Docstring). Verschoben aus load_focus.py (dort ursprünglich privat), da
    body_composition.py::_ga1_pace_by_date denselben Lookup für Lauf-Aktivitäten braucht."""
    row = cursor.execute(f"SELECT MAX(date) AS d FROM {table} WHERE date <= ?", (target_date,)).fetchone()
    snapshot_date = row["d"]
    if not snapshot_date:
        row = cursor.execute(f"SELECT MIN(date) AS d FROM {table}").fetchone()
        snapshot_date = row["d"]
    if not snapshot_date:
        return None
    rows = cursor.execute(f"SELECT zone, hr_min, hr_max FROM {table} WHERE date = ?", (snapshot_date,)).fetchall()
    return [(r["zone"], r["hr_min"], r["hr_max"]) for r in rows]


def _fetch_row(cursor, table, target_date):
    cursor.execute(f"SELECT * FROM {table} WHERE date = ?", (target_date,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _hr_zone_rows(threshold_hr, zones_pct):
    rows = []
    for label, low_pct, high_pct in zones_pct:
        hr_min = round(threshold_hr * low_pct) if threshold_hr is not None and low_pct is not None else None
        hr_max = round(threshold_hr * high_pct) if threshold_hr is not None and high_pct is not None else None
        rows.append((label, hr_min, hr_max))
    return rows


def _pace_zone_rows(threshold_pace_sec_per_km, zones_pct):
    rows = []
    for label, low_pct, high_pct in zones_pct:
        if threshold_pace_sec_per_km is None:
            rows.append((label, None, None))
            continue
        edge_a = threshold_pace_sec_per_km * low_pct if low_pct is not None else None
        edge_b = threshold_pace_sec_per_km * high_pct if high_pct is not None else None
        if edge_a is not None and edge_b is not None:
            pace_min, pace_max = min(edge_a, edge_b), max(edge_a, edge_b)
        elif edge_a is not None:
            pace_min, pace_max = edge_a, None
        elif edge_b is not None:
            pace_min, pace_max = None, edge_b
        else:
            pace_min, pace_max = None, None
        rows.append((label, pace_min, pace_max))
    return rows


def _power_zone_rows(ftp, zones_pct):
    rows = []
    for label, low_pct, high_pct in zones_pct:
        power_min = round(ftp * low_pct) if ftp is not None and low_pct is not None else None
        power_max = round(ftp * high_pct) if ftp is not None and high_pct is not None else None
        rows.append((label, power_min, power_max))
    return rows


def _close_integer_gaps(rows):
    """Für HF/Leistung (Ganzzahl): das obere Ende jeder Zone bleibt exakt wie aus dem Prozentsatz
    berechnet, das untere Ende der jeweils nächsten Zone wird auf (voriges Maximum + 1) gesetzt.
    Ergebnis: lückenlose, überlappungsfreie Partition statt einzelner bpm/Watt ohne Zonen-Zuordnung."""
    rows = list(rows)
    for i in range(len(rows) - 1):
        _, _, val_max = rows[i]
        if val_max is not None:
            next_label, _, next_max = rows[i + 1]
            rows[i + 1] = (next_label, val_max + 1, next_max)
    return rows


def _close_continuous_gaps(rows):
    """Für Pace (kontinuierlich, höherer Wert = langsamer): das schnellere Ende (Minimum) jeder
    Zone bleibt wie berechnet, das langsamere Ende (Maximum) der jeweils nächsten (schnelleren)
    Zone wird exakt darauf gesetzt - kein +1-Schritt nötig wie bei Ganzzahlen, da stetiger Wert."""
    rows = list(rows)
    for i in range(len(rows) - 1):
        _, val_min, _ = rows[i]
        if val_min is not None:
            next_label, next_min, _ = rows[i + 1]
            rows[i + 1] = (next_label, next_min, val_min)
    return rows


def recompute_zones(target_date):
    """Berechnet alle Trainingszonen aus den aktuellen Schwellenwerten neu und ersetzt den
    Zonen-Snapshot für target_date. Liest garmin_lactate_threshold/garmin_cycling_ftp selbst,
    damit keine Daten zwischen den _fetch_*-Funktionen in garmin_service.py durchgereicht werden müssen."""
    conn = get_connection()
    cursor = conn.cursor()
    lactate = _fetch_row(cursor, "garmin_lactate_threshold", target_date) or {}
    cycling_ftp_row = _fetch_row(cursor, "garmin_cycling_ftp", target_date) or {}
    conn.close()

    # --- Laufen: HF (LTHR) + Pace (Schwellenpace, aus m/s -> Sekunden/km) ---
    running_hr = lactate.get("heart_rate")
    running_speed = lactate.get("speed")
    running_pace = 1000.0 / running_speed if running_speed else None

    if running_hr is not None or running_pace is not None:
        hr_rows = _close_integer_gaps(_hr_zone_rows(running_hr, RUNNING_HR_ZONES_PCT))
        pace_rows = _close_continuous_gaps(_pace_zone_rows(running_pace, RUNNING_PACE_ZONES_PCT))
        # Beide Listen haben dieselben Zonen-Label in derselben Reihenfolge (siehe Konstanten oben).
        rows = [
            (target_date, hr_label, hr_min, hr_max, pace_min, pace_max)
            for (hr_label, hr_min, hr_max), (_, pace_min, pace_max) in zip(hr_rows, pace_rows)
        ]
        replace_timeseries(
            "training_zones_running", target_date,
            ["date", "zone", "hr_min", "hr_max", "pace_min_sec_per_km", "pace_max_sec_per_km"],
            rows
        )

    # --- Rad: HF (Bike-LTHR) ---
    cycling_hr = lactate.get("heart_rate_cycling")
    if cycling_hr is not None:
        hr_rows = _close_integer_gaps(_hr_zone_rows(cycling_hr, CYCLING_HR_ZONES_PCT))
        rows = [(target_date, label, hr_min, hr_max) for label, hr_min, hr_max in hr_rows]
        replace_timeseries(
            "training_zones_cycling_hr", target_date,
            ["date", "zone", "hr_min", "hr_max"],
            rows
        )

    # --- Rad: Leistung (FTP) - ausschließlich garmin_cycling_ftp. ---
    # garmin_lactate_threshold.functional_threshold_power ist KEIN Rad-FTP-Fallback: die rohe
    # Garmin-Antwort taggt dieses Feld explizit mit "sport": "RUNNING" (verifiziert per API-Call,
    # z.B. 435W Lauf-Leistung vs. 264W echte Rad-FTP aus garmin_cycling_ftp am selben Tag - zwei
    # unterschiedliche Metriken für zwei Sportarten, kein Konflikt zwischen zwei Quellen desselben
    # Werts). Ursprünglich fälschlich als Fallback mit Diskrepanz-Warnung eingebaut, korrigiert.
    ftp = cycling_ftp_row.get("functional_threshold_power")

    if ftp is not None:
        power_rows = _close_integer_gaps(_power_zone_rows(ftp, CYCLING_POWER_ZONES_PCT))
        rows = [(target_date, label, p_min, p_max) for label, p_min, p_max in power_rows]
        replace_timeseries(
            "training_zones_cycling_power", target_date,
            ["date", "zone", "power_min_watts", "power_max_watts"],
            rows
        )
