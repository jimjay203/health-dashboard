"""
Habit-Tracker (siehe "Schlaf"-Seite) - Faktoren, die Garmin nicht liefert, aber den Schlaf
plausibel beeinflussen (Koffein, letzte Bildschirmnutzung, letzte Mahlzeit). Reine Python-Logik,
kein Streamlit-Import. Bewusst ein fester Spaltensatz statt eines generischen Key-Value-Modells -
neue Habits kommen bei Bedarf per ALTER TABLE dazu (siehe db.py), wie bei jeder anderen Tabelle in
diesem Projekt auch. last_screen_time/last_meal_time als "HH:MM"-Freitext statt Minuten-Schätzung -
eine Uhrzeit ("wann zuletzt?") ist leichter zu erinnern, die Minuten bis zur Bettzeit lassen sich
serverseitig aus sleep_start_local ableiten (siehe backend/routers/sleep.py).
"""
from db import get_connection, upsert_daily_metric


def get_habit_entry(date_str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM habit_tracker WHERE date = ?", (date_str,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_habit_entry(date_str, caffeine_after_noon, last_screen_time, last_meal_time):
    data = {
        "date": date_str,
        "caffeine_after_noon": int(bool(caffeine_after_noon)),
        "last_screen_time": last_screen_time,
        "last_meal_time": last_meal_time,
    }
    upsert_daily_metric("habit_tracker", data)
    return data


def list_habit_entries(start_date, end_date):
    """Für die Korrelationsauswertung auf der Schlaf-Seite (siehe backend/routers/sleep.py) -
    alle Einträge in einem Datumsbereich, aufsteigend sortiert."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM habit_tracker WHERE date >= ? AND date <= ? ORDER BY date", (start_date, end_date)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
