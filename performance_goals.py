"""
CRUD für Leistungsziele (siehe "Leistung"-Seite). Reine Python-Logik, kein Streamlit-Import.
performance_goals hat einen natürlichen TEXT-Key (z.B. "marathon_pace") statt eines
AUTOINCREMENT-id - Zeilen bleiben jederzeit manuell editierbar, auch wenn sie ursprünglich aus
einem race_goals-Eintrag abgeleitet wurden (derived_from_race_goal_id ist reine Herkunfts-Info,
keine Sperre). race_goals-Schreibzugriff (renn-spezifische Zielzeiten) ist bewusst nicht Teil
dieser CRUD-API - das befüllt ein separater Auftrag (KI-Zielgespräch), hier nur lesend für die
Herkunfts-Anzeige eines abgeleiteten performance_goals-Eintrags.
"""
from datetime import datetime

from db import get_connection, upsert_by_key


def list_performance_goals():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM performance_goals ORDER BY key").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_performance_goal(key, label, target_value, unit, derived_from_race_goal_id=None, notes=None, target_date=None, start_date=None):
    row_data = {
        "key": key,
        "label": label,
        "target_value": target_value,
        "unit": unit,
        "derived_from_race_goal_id": derived_from_race_goal_id,
        "notes": notes,
        "target_date": target_date,
        "start_date": start_date,
        "updated_at": datetime.now().isoformat(),
    }
    upsert_by_key("performance_goals", "key", row_data)
    return row_data


def delete_performance_goal(key):
    conn = get_connection()
    conn.execute("DELETE FROM performance_goals WHERE key = ?", (key,))
    conn.commit()
    conn.close()
