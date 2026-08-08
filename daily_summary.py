"""
Schicht 1 der KI-Chat-Vorbereitung: regelbasiert vorverdichtete Tageskennzahlen (Trainingsbelastung,
Erholung, Anomalien) - kein LLM-Call, reine SQL/Python-Regellogik mit Schwellenwerten. Wird bei jedem
Sync (auch Backfill-Tage) für den jeweiligen Tag berechnet, siehe
garmin_service.fetch_and_store_garmin_data().
"""
from datetime import date, timedelta
from statistics import mean, pstdev
from db import get_connection, upsert_daily_metric

# --- Tunable Konstanten (analog zu training_zones.py) ---
MIN_DAYS_FOR_BASELINE = 3            # Mindestanzahl Tage mit Daten für *_vs_Nd_avg_pct, sonst NULL
SLEEP_DEBT_WINDOW_DAYS = 14
DEFAULT_SLEEP_TARGET_HOURS = 8.0     # Fallback, falls Garmins sleepNeed für eine Nacht fehlt
WEIGHT_AVG_WINDOW_DAYS = 30

OVERREACH_RHR_PCT = 5.0              # Ruhepuls > +5% vs. 7-Tage-Schnitt
OVERREACH_HRV_PCT = 10.0             # HRV < -10% vs. 7-Tage-Schnitt
OVERREACH_SLEEP_PCT = 15.0           # Schlaf < -15% vs. 7-Tage-Schnitt
OVERREACH_MIN_SLEEP_HOURS = 6.0

NOTABLE_DEVIATION_MULTIPLIER = 1.5   # ab dem Wievielfachen der Overreach-Schwelle notable_events_text greift
NOTABLE_ACWR_THRESHOLD = 1.5

CTL_TIME_CONSTANT_DAYS = 42          # Chronic Training Load (Fitness) - EWMA-Zeitkonstante
ATL_TIME_CONSTANT_DAYS = 7           # Acute Training Load (Ermüdung) - EWMA-Zeitkonstante


def _daterange(end_date_str, num_days, include_end=True):
    """(start, end) als ISO-Strings für ein num_days-Fenster, endend bei end_date_str."""
    end = date.fromisoformat(end_date_str)
    if not include_end:
        end -= timedelta(days=1)
    start = end - timedelta(days=num_days - 1)
    return start.isoformat(), end.isoformat()


def _pct_vs_baseline(value, baseline):
    if value is None or baseline is None or baseline == 0:
        return None
    return (value - baseline) / baseline * 100.0


def _baseline_avg(cursor, column, target_date, window_days):
    """Mittelwert von garmin_daily.column über die window_days Tage VOR target_date (exklusive)."""
    start, end = _daterange(target_date, window_days, include_end=False)
    rows = cursor.execute(
        f"SELECT {column} FROM garmin_daily WHERE date >= ? AND date <= ? AND {column} IS NOT NULL",
        (start, end)
    ).fetchall()
    values = [r[0] for r in rows]
    if len(values) < MIN_DAYS_FOR_BASELINE:
        return None
    return mean(values)


def _daily_training_loads(cursor, target_date, window_days):
    """Liste von window_days Tages-Summen (activity_training_load), älterer Tag zuerst,
    0.0 für trainingsfreie Tage (kein Trainingsreiz ist ein echter Wert, kein fehlender)."""
    start, end = _daterange(target_date, window_days, include_end=True)
    rows = cursor.execute(
        "SELECT date(start_time_local) AS d, SUM(activity_training_load) AS total FROM garmin_activities "
        "WHERE date(start_time_local) >= ? AND date(start_time_local) <= ? "
        "AND activity_training_load IS NOT NULL GROUP BY d",
        (start, end)
    ).fetchall()
    by_date = {r["d"]: r["total"] for r in rows}
    start_d = date.fromisoformat(start)
    return [by_date.get((start_d + timedelta(days=i)).isoformat(), 0.0) or 0.0 for i in range(window_days)]


def _training_load_sum(cursor, target_date, window_days):
    start, end = _daterange(target_date, window_days, include_end=True)
    row = cursor.execute(
        "SELECT SUM(activity_training_load) AS total FROM garmin_activities "
        "WHERE date(start_time_local) >= ? AND date(start_time_local) <= ? "
        "AND activity_training_load IS NOT NULL",
        (start, end)
    ).fetchone()
    return row["total"] if row and row["total"] is not None else 0.0


def _training_monotony_and_strain(cursor, target_date):
    daily_loads = _daily_training_loads(cursor, target_date, 7)
    load_7d = sum(daily_loads)
    spread = pstdev(daily_loads)
    monotony = (mean(daily_loads) / spread) if spread > 0 else None
    strain = (load_7d * monotony) if monotony is not None else None
    return load_7d, monotony, strain


def _daily_training_load(cursor, target_date):
    """Tages-Summe activity_training_load für genau target_date (0.0 an trainingsfreien Tagen)."""
    row = cursor.execute(
        "SELECT SUM(activity_training_load) AS total FROM garmin_activities "
        "WHERE date(start_time_local) = ? AND activity_training_load IS NOT NULL",
        (target_date,)
    ).fetchone()
    return row["total"] if row and row["total"] is not None else 0.0


def _previous_ctl_atl(cursor, target_date):
    """CTL/ATL des Vortags aus daily_summary - (0.0, 0.0) als Kaltstart, falls noch keine
    Vortages-Zeile existiert (dann laufen sich CTL/ATL über die nächsten Wochen erst ein)."""
    prev_date = (date.fromisoformat(target_date) - timedelta(days=1)).isoformat()
    row = cursor.execute("SELECT ctl, atl FROM daily_summary WHERE date = ?", (prev_date,)).fetchone()
    if not row or row["ctl"] is None or row["atl"] is None:
        return 0.0, 0.0
    return row["ctl"], row["atl"]


def _sleep_debt(cursor, target_date):
    start, end = _daterange(target_date, SLEEP_DEBT_WINDOW_DAYS, include_end=True)
    rows = cursor.execute(
        "SELECT gd.date, gd.sleep_hours, sp.sleep_need_seconds FROM garmin_daily gd "
        "LEFT JOIN garmin_sleep_phases sp ON sp.date = gd.date "
        "WHERE gd.date >= ? AND gd.date <= ?",
        (start, end)
    ).fetchall()
    debt, found_any = 0.0, False
    for r in rows:
        if r["sleep_hours"] is None:
            continue
        target_hours = (r["sleep_need_seconds"] / 3600.0) if r["sleep_need_seconds"] else DEFAULT_SLEEP_TARGET_HOURS
        debt += r["sleep_hours"] - target_hours
        found_any = True
    return debt if found_any else None


def _overreach_flag(rhr_pct, hrv_pct, sleep_pct, sleep_hours):
    if rhr_pct is None or hrv_pct is None:
        return 0
    rhr_bad = rhr_pct > OVERREACH_RHR_PCT
    hrv_bad = hrv_pct < -OVERREACH_HRV_PCT
    sleep_bad = (sleep_pct is not None and sleep_pct < -OVERREACH_SLEEP_PCT) or \
                (sleep_hours is not None and sleep_hours < OVERREACH_MIN_SLEEP_HOURS)
    return int(rhr_bad and hrv_bad and sleep_bad)


def _days_until_next_race(cursor, target_date):
    row = cursor.execute(
        "SELECT MIN(event_date) AS next_race FROM garmin_scheduled_events "
        "WHERE is_race = 1 AND event_date >= ?",
        (target_date,)
    ).fetchone()
    if not row or not row["next_race"]:
        return None
    return (date.fromisoformat(row["next_race"]) - date.fromisoformat(target_date)).days


def _weight_for_date(cursor, target_date):
    """Neuester Gewichtswert für target_date - Withings bevorzugt (vollständigere Datenquelle,
    siehe withings_service.py: Garmin bekommt Withings-Messungen nur lückenhaft weitergeleitet),
    Garmin als Fallback (z.B. Tage vor der Withings-Integration oder ohne Withings-Sync)."""
    row = cursor.execute(
        "SELECT weight FROM withings_weigh_ins WHERE date = ? AND weight IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 1",
        (target_date,)
    ).fetchone()
    if row:
        return row["weight"]
    row = cursor.execute(
        "SELECT weight FROM garmin_weigh_ins WHERE date = ? AND weight IS NOT NULL "
        "ORDER BY timestamp_gmt DESC LIMIT 1",
        (target_date,)
    ).fetchone()
    return row["weight"] if row else None


def _weight_series_for_range(cursor, start, end):
    """Ein Gewichtswert pro Tag im Bereich [start, end] - Withings bevorzugt, sonst Garmin.
    Vermeidet Doppelzählung an Tagen, an denen beide Quellen dieselbe physische Messung haben
    (Garmin leitet Withings-Messungen teilweise weiter) - ohne diese Dedup-Logik würde ein
    Tag mit beiden Quellen die Baseline doppelt gewichten."""
    withings_rows = cursor.execute(
        "SELECT date, weight FROM withings_weigh_ins WHERE date >= ? AND date <= ? "
        "AND weight IS NOT NULL",
        (start, end)
    ).fetchall()
    covered_dates = {r["date"] for r in withings_rows}
    values = [r["weight"] for r in withings_rows]

    garmin_rows = cursor.execute(
        "SELECT date, weight FROM garmin_weigh_ins WHERE date >= ? AND date <= ? "
        "AND weight IS NOT NULL",
        (start, end)
    ).fetchall()
    for row in garmin_rows:
        if row["date"] not in covered_dates:
            values.append(row["weight"])
            covered_dates.add(row["date"])

    return values


def _weight_vs_avg_pct(cursor, target_date):
    today_weight = _weight_for_date(cursor, target_date)
    if today_weight is None:
        return None
    start, end = _daterange(target_date, WEIGHT_AVG_WINDOW_DAYS, include_end=False)
    values = _weight_series_for_range(cursor, start, end)
    if not values:
        return None
    return _pct_vs_baseline(today_weight, mean(values))


def _data_quality_flag(garmin_row):
    if not garmin_row:
        return "missing_core_data"
    fields = [garmin_row["resting_hr"], garmin_row["avg_hrv"], garmin_row["sleep_hours"]]
    missing = sum(1 for f in fields if f is None)
    if missing == len(fields):
        return "missing_core_data"
    if missing > 0:
        return "partial_data"
    return None


def _notable_events_text(overreach_flag, journal_filled, days_until_race, hrv_pct, sleep_pct, rhr_pct, acute_chronic_ratio):
    if overreach_flag:
        if not journal_filled:
            return ("Objektive Warnsignale (Ruhepuls/HRV/Schlaf) vorhanden, "
                    "subjektives Befinden noch nicht erfasst.")
        return "Übertrainingsrisiko: Ruhepuls erhöht, HRV niedrig und Schlaf schlecht zugleich."
    if days_until_race is not None and 0 <= days_until_race <= 7:
        return f"Nur noch {days_until_race} Tage bis zum nächsten Rennen."
    if hrv_pct is not None and hrv_pct < -OVERREACH_HRV_PCT * NOTABLE_DEVIATION_MULTIPLIER:
        return f"HRV deutlich unter Schnitt ({hrv_pct:.0f}%)."
    if sleep_pct is not None and sleep_pct < -OVERREACH_SLEEP_PCT * NOTABLE_DEVIATION_MULTIPLIER:
        return f"Schlafdauer deutlich unter Schnitt ({sleep_pct:.0f}%)."
    if rhr_pct is not None and rhr_pct > OVERREACH_RHR_PCT * NOTABLE_DEVIATION_MULTIPLIER:
        return f"Ruhepuls deutlich über Schnitt ({rhr_pct:.0f}%)."
    if acute_chronic_ratio is not None and acute_chronic_ratio > NOTABLE_ACWR_THRESHOLD:
        return f"Akute Belastung deutlich über chronischer Basis (ACWR {acute_chronic_ratio:.2f})."
    return "Keine Auffälligkeiten."


def compute_daily_summary(target_date):
    """Berechnet und speichert die daily_summary-Zeile für target_date. Rein lesend/rechnend auf
    bereits synchronisierten Daten - kein API-Call."""
    conn = get_connection()
    cursor = conn.cursor()

    garmin_row = cursor.execute("SELECT * FROM garmin_daily WHERE date = ?", (target_date,)).fetchone()

    avg_hrv = garmin_row["avg_hrv"] if garmin_row else None
    sleep_hours = garmin_row["sleep_hours"] if garmin_row else None
    resting_hr = garmin_row["resting_hr"] if garmin_row else None

    hrv_vs_7d = _pct_vs_baseline(avg_hrv, _baseline_avg(cursor, "avg_hrv", target_date, 7))
    hrv_vs_28d = _pct_vs_baseline(avg_hrv, _baseline_avg(cursor, "avg_hrv", target_date, 28))
    sleep_vs_7d = _pct_vs_baseline(sleep_hours, _baseline_avg(cursor, "sleep_hours", target_date, 7))
    rhr_vs_7d = _pct_vs_baseline(resting_hr, _baseline_avg(cursor, "resting_hr", target_date, 7))
    rhr_vs_28d = _pct_vs_baseline(resting_hr, _baseline_avg(cursor, "resting_hr", target_date, 28))

    training_load_7d, training_monotony, training_strain = _training_monotony_and_strain(cursor, target_date)
    training_load_28d = _training_load_sum(cursor, target_date, 28)
    acute_chronic_ratio = (
        training_load_7d / (training_load_28d / 4)
        if training_load_28d else None
    )

    daily_load = _daily_training_load(cursor, target_date)
    prev_ctl, prev_atl = _previous_ctl_atl(cursor, target_date)
    ctl = prev_ctl + (daily_load - prev_ctl) / CTL_TIME_CONSTANT_DAYS
    atl = prev_atl + (daily_load - prev_atl) / ATL_TIME_CONSTANT_DAYS
    tsb = ctl - atl

    sleep_debt = _sleep_debt(cursor, target_date)
    overreach = _overreach_flag(rhr_vs_7d, hrv_vs_7d, sleep_vs_7d, sleep_hours)
    days_until_race = _days_until_next_race(cursor, target_date)
    weight_pct = _weight_vs_avg_pct(cursor, target_date)
    data_quality = _data_quality_flag(garmin_row)

    # daily_journal ist die Quelle der Wahrheit dafür, ob für target_date bereits subjektiv
    # journalisiert wurde - unabhängig davon, ob das Journal vor oder nach diesem Sync gespeichert
    # wurde (Reihenfolge-unabhängigkeit, siehe sync_journal_columns() unten).
    journal_filled = cursor.execute(
        "SELECT 1 FROM daily_journal WHERE date = ?", (target_date,)
    ).fetchone() is not None
    notable_text = _notable_events_text(
        overreach, journal_filled, days_until_race, hrv_vs_7d, sleep_vs_7d, rhr_vs_7d, acute_chronic_ratio
    )

    conn.close()

    upsert_daily_metric("daily_summary", {
        "date": target_date,
        "hrv_vs_7d_avg_pct": hrv_vs_7d,
        "hrv_vs_28d_avg_pct": hrv_vs_28d,
        "sleep_vs_7d_avg_pct": sleep_vs_7d,
        "resting_hr_vs_7d_avg_pct": rhr_vs_7d,
        "resting_hr_vs_28d_avg_pct": rhr_vs_28d,
        "training_load_7d": training_load_7d,
        "training_load_28d": training_load_28d,
        "acute_chronic_ratio": acute_chronic_ratio,
        "training_monotony": training_monotony,
        "training_strain": training_strain,
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "sleep_debt_cumulative": sleep_debt,
        "overreach_flag": overreach,
        "days_until_next_race": days_until_race,
        "weight_vs_avg_pct": weight_pct,
        "data_quality_flag": data_quality,
        "notable_events_text": notable_text,
    })


def recompute_summary_range(start_date, end_date):
    """Berechnet daily_summary/weekly_summary für jeden Tag zwischen start_date und end_date
    (inklusive) neu, in chronologischer Reihenfolge. Notwendig, weil CTL/ATL rekursiv vom Vortag
    abhängen (siehe _previous_ctl_atl) - wird nachträglich z.B. eine Aktivität für ein vergangenes
    Datum nachgeladen (garmin_activities.py, löst selbst KEINEN compute_daily_summary()-Aufruf aus,
    anders als garmin_service.fetch_and_store_garmin_data()), bleibt die gesamte CTL/ATL-Kette ab
    diesem Tag sonst auf dem alten Stand stehen. Rein lokal, kein Garmin-API-Call (im Gegensatz zum
    "Backfill über Zeitraum" auf der Einstellungen-Seite, garmin_backfill.py::run_backfill) - läuft
    deshalb ohne Drosselungspausen/Rate-Limit-Risiko durch. Gibt die Anzahl neu berechneter Tage
    zurück."""
    from weekly_summary import compute_weekly_summary

    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if current > end:
        raise ValueError("Startdatum muss vor oder gleich dem Enddatum liegen.")

    count = 0
    while current <= end:
        target_date = current.isoformat()
        compute_daily_summary(target_date)
        compute_weekly_summary(target_date)
        count += 1
        current += timedelta(days=1)
    return count


def sync_journal_columns(target_date, rpe, soreness, energy):
    """Wird beim Speichern des Tagesjournals aufgerufen (siehe pages/1_🏠_Home.py) - eigenständiger
    zweiter Trigger neben compute_daily_summary(). Aktualisiert NUR die drei Journal-Spiegel-
    Spalten (legt die Zeile an, falls sie noch nicht existiert) und frischt notable_events_text
    anhand des bereits vorhandenen overreach_flag auf (journal_filled wird jetzt wahr) - berechnet
    aber keine objektiven Kennzahlen neu, die ändern sich durch einen Journal-Eintrag nicht.
    Reihenfolge-unabhängig zu compute_daily_summary(): beide Trigger lassen die jeweils andere
    Spalten-Gruppe unangetastet (upsert_daily_metric() aktualisiert nur die übergebenen Spalten)."""
    conn = get_connection()
    cursor = conn.cursor()
    existing = cursor.execute(
        "SELECT overreach_flag, days_until_next_race, hrv_vs_7d_avg_pct, sleep_vs_7d_avg_pct, "
        "resting_hr_vs_7d_avg_pct, acute_chronic_ratio FROM daily_summary WHERE date = ?",
        (target_date,)
    ).fetchone()
    conn.close()

    overreach = existing["overreach_flag"] if existing else 0
    notable_text = _notable_events_text(
        overreach, True,
        existing["days_until_next_race"] if existing else None,
        existing["hrv_vs_7d_avg_pct"] if existing else None,
        existing["sleep_vs_7d_avg_pct"] if existing else None,
        existing["resting_hr_vs_7d_avg_pct"] if existing else None,
        existing["acute_chronic_ratio"] if existing else None,
    )

    upsert_daily_metric("daily_summary", {
        "date": target_date,
        "journal_rpe": rpe,
        "journal_soreness": soreness,
        "journal_energy_level": energy,
        "notable_events_text": notable_text,
    })
