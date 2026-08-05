"""
Kleine, wiederverwendbare Kontext-Bausteine für Gemini-Prompts - geteilt zwischen chat_engine.py
(Schicht 4) und daily_recommendation.py (Heute-Ansicht). Reine Lesefunktionen auf einem bereits
offenen sqlite3.Cursor, kein eigener Connect (Aufrufer verwaltet die Connection).
"""


def insight_memory_block(cursor):
    row = cursor.execute(
        "SELECT compressed_text FROM insight_memory_compressed ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if not row or not row["compressed_text"]:
        return "(Kein Eintrag vorhanden.)"
    return row["compressed_text"]


def daily_summary_block(cursor, target_date):
    row = cursor.execute("SELECT * FROM daily_summary WHERE date = ?", (target_date,)).fetchone()
    if not row:
        return f"Für {target_date} liegt noch keine daily_summary vor."
    parts = [f"{k}={row[k]}" for k in row.keys() if k not in ("date", "created_at") and row[k] is not None]
    return f"KENNZAHLEN ({target_date}): " + ", ".join(parts)
