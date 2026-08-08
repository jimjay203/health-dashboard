"""
CRUD für das Schmerz-/Verletzungsprotokoll auf der Körper-Seite (siehe backend/routers/body.py).
Reine Python-Logik, kein Streamlit-Import (gleiches Muster wie performance_goals.py).
resolved_at=NULL markiert einen noch aktiven Eintrag ("aktive Baustelle").
"""
from datetime import date, datetime, timedelta

from db import get_connection
from weekly_summary import iso_week_info


def list_injuries(active_only=False):
    conn = get_connection()
    query = "SELECT * FROM injury_log"
    if active_only:
        query += " WHERE resolved_at IS NULL"
    query += " ORDER BY date DESC, id DESC"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_injury(date_str, body_part, severity, pain_type=None, context=None, notes=None):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO injury_log (date, body_part, severity, pain_type, context, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (date_str, body_part, severity, pain_type, context, notes)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return get_injury(new_id)


def get_injury(injury_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM injury_log WHERE id = ?", (injury_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_injury(injury_id, body_part=None, severity=None, pain_type=None, context=None, notes=None, resolved=None):
    """resolved=True setzt resolved_at auf jetzt, resolved=False setzt es zurück auf NULL
    (wieder aufgeflammt) - resolved=None lässt das Feld unverändert."""
    current = get_injury(injury_id)
    if not current:
        return None

    resolved_at = current["resolved_at"]
    if resolved is True:
        resolved_at = datetime.now().isoformat()
    elif resolved is False:
        resolved_at = None

    conn = get_connection()
    conn.execute(
        "UPDATE injury_log SET body_part = ?, severity = ?, pain_type = ?, context = ?, notes = ?, "
        "resolved_at = ? WHERE id = ?",
        (
            body_part if body_part is not None else current["body_part"],
            severity if severity is not None else current["severity"],
            pain_type if pain_type is not None else current["pain_type"],
            context if context is not None else current["context"],
            notes if notes is not None else current["notes"],
            resolved_at,
            injury_id,
        )
    )
    conn.commit()
    conn.close()
    return get_injury(injury_id)


def delete_injury(injury_id):
    conn = get_connection()
    conn.execute("DELETE FROM injury_log WHERE id = ?", (injury_id,))
    conn.commit()
    conn.close()


def weekly_max_severity(start_date, end_date):
    """{week_id: max_severity} für jede ISO-Woche im Zeitraum [start_date, end_date] - Maximum
    (nicht Durchschnitt) pro Woche, da ein einzelner starker Schmerztag die klinisch relevantere
    Belastungsgrenze ist als ein geglätteter Wochenschnitt (siehe Plan-Entscheidung). Wochen ohne
    Eintrag zählen als 0 (schmerzfrei), nicht als fehlend - sonst wäre die Stichprobe der
    "Wöchentlicher Lauf-Load vs. Schmerz-Intensität"-Korrelation zu "nur schlechte Wochen" verzerrt."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, severity FROM injury_log WHERE date >= ? AND date <= ? AND severity IS NOT NULL",
        (start_date, end_date)
    ).fetchall()
    conn.close()

    result = {}
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    while current <= end:
        week_id, *_ = iso_week_info(current.isoformat())
        result.setdefault(week_id, 0)
        current += timedelta(days=1)

    for r in rows:
        week_id, *_ = iso_week_info(r["date"])
        result[week_id] = max(result[week_id], r["severity"])

    return result
