"""
Heute-Ansicht (Schritt 2 des FastAPI+React-Rebuilds): Gemini-generierte Tagesempfehlung. Reine
Python-Logik, kein Streamlit-Import (Portabilitäts-Prinzip, analog zu daily_summary.py/
insight_memory.py). Nutzt gemini_client.py (gleicher Client wie insight_memory.py/chat_engine.py).

Bewusster Neuaufbau, kein Wiederherstellen des früher entfernten ai_coach.py. Schreibt NIEMALS in
insight_memory_raw/insight_memory_compressed - das bleibt ausschließlich für vom Nutzer selbst
eingetragene Zusatzinfos reserviert (siehe insight_memory.py). Ergebnis landet stattdessen in der
eigenen daily_recommendation-Tabelle.
"""
import json
import re
from datetime import date, datetime

from google.genai import types
from db import get_connection, upsert_daily_metric
from gemini_client import MODEL_NAME, get_client
from context_blocks import insight_memory_block, daily_summary_block

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "recommendation_text": {"type": "STRING"},
        "reasoning_bullets": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["recommendation_text", "reasoning_bullets"],
}

SYSTEM_PROMPT = """
Du bist ein Trainings-Coach-Assistent für einen Marathon-/Triathlon-Athleten. Du bekommst
Tages-/Wochen-Kennzahlen, das heutige Tagesjournal, ein Erkenntnis-Gedächtnis mit dauerhaften
Zusatzinfos zum Athleten sowie heutige Termine.

Gib eine kurze, konkrete Trainingsempfehlung für heute (1-2 Sätze) und 2-4 kurze
Begründungs-Stichpunkte, die sich direkt auf die gegebenen Kennzahlen/Infos stützen. Falls eine
NUTZER-ÜBERSCHREIBUNG angegeben ist, berücksichtige sie explizit in Empfehlung und Begründung.

Gib AUSSCHLIESSLICH valides JSON zurück im Format:
{"recommendation_text": "<Empfehlung>", "reasoning_bullets": ["<Stichpunkt 1>", "<Stichpunkt 2>", ...]}
"""

OVERRIDE_PHRASES = {
    "worse": "Der Athlet fühlt sich heute SCHLECHTER als die Kennzahlen suggerieren.",
    "better": "Der Athlet fühlt sich heute BESSER als die Kennzahlen suggerieren.",
    "neutral": "Der Athlet hat den automatischen Score neutral bestätigt.",
}


def _week_id(target_date):
    d = date.fromisoformat(target_date)
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _weekly_summary_block(cursor, target_date):
    week_id = _week_id(target_date)
    row = cursor.execute("SELECT * FROM weekly_summary WHERE week_id = ?", (week_id,)).fetchone()
    if not row:
        return f"Für die aktuelle Woche ({week_id}) liegt noch keine weekly_summary vor."
    parts = [f"{k}={row[k]}" for k in row.keys() if k != "week_id" and row[k] is not None]
    return ", ".join(parts)


def _journal_block(cursor, target_date):
    row = cursor.execute("SELECT * FROM daily_journal WHERE date = ?", (target_date,)).fetchone()
    if not row:
        return "Kein Journal-Eintrag für heute."
    return (
        f"RPE={row['rpe_score']}, Muskelkater={row['muscle_soreness']}, "
        f"Energie={row['energy_level']}, Notizen={row['notes'] or '(keine)'}"
    )


def _events_block(cursor, target_date):
    # event_date ist der echte Kalendertag - die Spalte "date" in garmin_scheduled_events ist ein
    # Monats-Partitionsschlüssel (siehe db.py-Schema-Kommentar), kein Kalendertag.
    events = cursor.execute(
        "SELECT title, is_race, item_type, distance_meters FROM garmin_scheduled_events "
        "WHERE event_date = ?",
        (target_date,)
    ).fetchall()
    if not events:
        return "Keine geplanten Termine für heute."
    lines = []
    for e in events:
        kind = "RENNEN" if e["is_race"] else (e["item_type"] or "Termin")
        distance = f" ({e['distance_meters']}m)" if e["distance_meters"] else ""
        lines.append(f"- {kind}: {e['title']}{distance}")
    return "\n".join(lines)


def _gather_context(cursor, target_date, override_value=None):
    parts = [
        "=== TAGES-KENNZAHLEN ===",
        daily_summary_block(cursor, target_date),
        "\n=== WOCHEN-KENNZAHLEN ===",
        _weekly_summary_block(cursor, target_date),
        "\n=== TAGESJOURNAL ===",
        _journal_block(cursor, target_date),
        "\n=== ERKENNTNIS-GEDÄCHTNIS ===",
        insight_memory_block(cursor),
        "\n=== HEUTIGE TERMINE ===",
        _events_block(cursor, target_date),
    ]
    if override_value:
        parts.append("\n=== NUTZER-ÜBERSCHREIBUNG ===")
        parts.append(OVERRIDE_PHRASES.get(override_value, f"Override: {override_value}"))
    return "\n".join(parts)


def _strip_markdown_fences(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def generate_daily_recommendation(target_date, override_value=None):
    """Sammelt Kontext, ruft Gemini mit striktem response_schema auf (gleiches Muster wie
    insight_memory.py::_compress - MIME-Type allein reicht dort laut Kommentar nicht für
    garantiert valides JSON), cacht das Ergebnis in daily_recommendation und gibt es zurück."""
    conn = get_connection()
    cursor = conn.cursor()
    context = _gather_context(cursor, target_date, override_value)
    conn.close()

    client = get_client()
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=context,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.4,
        ),
    )
    raw = _strip_markdown_fences(response.text or "")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        snippet = raw[:500] if raw else "(leere Antwort)"
        raise RuntimeError(f"Gemini-Antwort war kein valides JSON ({e}). Rohtext (Anfang): {snippet}") from e

    recommendation_text = result["recommendation_text"]
    reasoning_bullets = result["reasoning_bullets"]
    generated_at = datetime.now().isoformat()

    upsert_daily_metric("daily_recommendation", {
        "date": target_date,
        "recommendation_text": recommendation_text,
        "reasoning_bullets_json": json.dumps(reasoning_bullets, ensure_ascii=False),
        "generated_at": generated_at,
    })

    return {
        "date": target_date,
        "recommendation_text": recommendation_text,
        "reasoning_bullets": reasoning_bullets,
        "generated_at": generated_at,
    }


def get_cached_recommendation(target_date):
    conn = get_connection()
    row = conn.execute("SELECT * FROM daily_recommendation WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "date": row["date"],
        "recommendation_text": row["recommendation_text"],
        "reasoning_bullets": json.loads(row["reasoning_bullets_json"]),
        "generated_at": row["generated_at"],
    }


def set_override_and_regenerate(target_date, override_value):
    upsert_daily_metric("daily_override", {
        "date": target_date,
        "override_value": override_value,
        "created_at": datetime.now().isoformat(),
    })
    return generate_daily_recommendation(target_date, override_value=override_value)
