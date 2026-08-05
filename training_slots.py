"""
Wiederkehrende Vereins-Trainingstermine (Heute-Ansicht, Wochenstreifen). Reine Python-Logik, kein
Streamlit-Import. Handgeschriebenes SQL nach dem Vorbild von insight_memory.py::add_raw_entry/
delete_raw_entry - die generischen Upsert-Helfer in db.py sind auf "ein Datensatz pro natürlichem
Schlüssel, komplett ersetzt" ausgelegt, nicht auf inkrementelles Feld-CRUD über eine id.
"""
from db import get_connection


def list_slots():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM club_training_slots ORDER BY weekday, valid_from"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_slot(weekday, sport_type, label, valid_from, valid_to=None, typical_character=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO club_training_slots (weekday, sport_type, label, valid_from, valid_to, "
        "typical_character) VALUES (?, ?, ?, ?, ?, ?)",
        (weekday, sport_type, label, valid_from, valid_to, typical_character)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": new_id, "weekday": weekday, "sport_type": sport_type, "label": label,
        "valid_from": valid_from, "valid_to": valid_to, "typical_character": typical_character,
    }


def update_slot(slot_id, weekday, sport_type, label, valid_from, valid_to=None, typical_character=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE club_training_slots SET weekday=?, sport_type=?, label=?, valid_from=?, valid_to=?, "
        "typical_character=? WHERE id=?",
        (weekday, sport_type, label, valid_from, valid_to, typical_character, slot_id)
    )
    changed = cursor.rowcount
    conn.commit()
    conn.close()
    if not changed:
        return None
    return {
        "id": slot_id, "weekday": weekday, "sport_type": sport_type, "label": label,
        "valid_from": valid_from, "valid_to": valid_to, "typical_character": typical_character,
    }


def delete_slot(slot_id):
    conn = get_connection()
    conn.execute("DELETE FROM club_training_slots WHERE id = ?", (slot_id,))
    conn.commit()
    conn.close()
