"""
Kleine, wiederverwendbare Kontext-Bausteine für Gemini-Prompts - geteilt zwischen chat_engine.py
(Schicht 4), daily_recommendation.py (Heute-Ansicht) und weekly_planner.py (Wochenplaner). Reine
Lesefunktionen auf einem bereits offenen sqlite3.Cursor, kein eigener Connect (Aufrufer verwaltet
die Connection).
"""
import re
from datetime import date


def strip_markdown_fences(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


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


def weekly_plan_block(cursor, target_date):
    """Wochenplan-Kontext für target_date (siehe weekly_planner.py) - wird ausgelassen (eigener
    Hinweistext statt Wochenplan-Daten), falls heute ein fester Vereinstermin vorliegt, da der
    ohnehin schon fix ist und keinen zusätzlichen Wochenplan-Kontext braucht (gleiche
    Prioritäts-Query wie backend/routers/today.py::get_week_strip)."""
    weekday = date.fromisoformat(target_date).weekday()  # 0=Montag..6=Sonntag
    club_row = cursor.execute(
        "SELECT label FROM club_training_slots WHERE weekday = ? AND valid_from <= ? "
        "AND (valid_to IS NULL OR valid_to >= ?) LIMIT 1",
        (weekday, target_date, target_date)
    ).fetchone()
    if club_row:
        return (
            f"Heute ist ein fester Vereinstermin ({club_row['label']}) - kein zusätzlicher "
            "Wochenplan-Kontext nötig."
        )

    row = cursor.execute("SELECT * FROM weekly_plan WHERE date = ?", (target_date,)).fetchone()
    if not row:
        return f"Für {target_date} liegt kein Wochenplan-Eintrag vor."
    parts = [
        f"{k}={row[k]}" for k in row.keys()
        if k not in ("date", "week_id", "weekday", "generated_at") and row[k] is not None
    ]
    return f"WOCHENPLAN-VORSCHLAG ({target_date}): " + ", ".join(parts)
