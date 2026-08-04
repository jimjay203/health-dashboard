"""
Schicht 3 der KI-Chat-Vorbereitung: LLM-gestütztes Erkenntnis-Gedächtnis. Enthält AUSSCHLIESSLICH
zusätzlichen Kontext, den der Athlet selbst in normaler Sprache einträgt und der sich nicht aus
den Garmin-/Trainingsdaten ablesen lässt (z.B. feste Wochenroutinen wie Vereinstraining) - keine
aus daily_summary/weekly_summary/activity_analytics abgeleiteten Inhalte, die stünden bereits dort.
compressed_text dampft die Rohtext-Einträge auf das Wesentliche ein, damit er später komplett als
Kontext an einen KI-Chat mitgegeben werden kann, ohne dass die Kosten mit der Zeit explodieren.
"""
import json
from google.genai import types
from db import get_connection
from gemini_client import MODEL_NAME, get_client

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"updated_compressed_text": {"type": "STRING"}},
    "required": ["updated_compressed_text"],
}

SYSTEM_PROMPT = """
Du pflegst ein kompaktes Wissens-Gedächtnis mit Zusatzinfos, die ein Ausdauersportler (Marathon
und Triathlon) selbst über sich einträgt und die sich NICHT aus Trainingsdaten ablesen lassen -
z.B. feste Wochenroutinen ("mittwochs Bahntraining mit dem Verein"), Vorlieben, chronische
Eigenheiten (Hitzeverträglichkeit, Verletzungshistorie). Du bekommst den bisherigen verdichteten
Text sowie einen neuen Rohtext-Eintrag des Athleten.

Aktualisiere den verdichteten Text so, dass er weiterhin kompakt und widerspruchsfrei bleibt:
- Wenn der neue Eintrag eine bestehende Aussage präzisiert oder korrigiert, ERSETZE die
  betroffene Stelle (nicht duplizieren).
- Wenn der neue Eintrag inhaltlich bereits abgedeckt ist (redundant), ignoriere ihn und gib den
  Text unverändert zurück.
- Wenn er wirklich neue Information enthält, ergänze sie kompakt an passender Stelle.
- Formuliere in kurzen Stichpunkten/Sätzen, keine Wiederholungen, kein Blabla.

Gib AUSSCHLIESSLICH valides JSON zurück im Format:
{"updated_compressed_text": "<vollständiger aktualisierter Text>"}
"""


def _compress(user_content):
    """Striktes response_schema statt nur response_mime_type="application/json" - ohne Schema
    keine garantiert valide JSON-Ausgabe (hat in einer früheren Gemini-Integration dieses Repos
    schon einmal zu einem Parse-Crash geführt)."""
    client = get_client()
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.2,
        ),
    )
    try:
        result = json.loads(response.text)
    except json.JSONDecodeError as e:
        snippet = response.text[:500] if response.text else "(leere Antwort)"
        raise RuntimeError(f"Gemini-Antwort war kein valides JSON ({e}). Rohtext (Anfang): {snippet}") from e
    return result["updated_compressed_text"]


def _current_text(cursor):
    row = cursor.execute(
        "SELECT compressed_text FROM insight_memory_compressed ORDER BY version DESC LIMIT 1"
    ).fetchone()
    return row["compressed_text"] if row else ""


def _next_version(cursor):
    row = cursor.execute("SELECT MAX(version) AS v FROM insight_memory_compressed").fetchone()
    return (row["v"] or 0) + 1


def _save_new_version(cursor, text):
    version = _next_version(cursor)
    cursor.execute(
        "INSERT INTO insight_memory_compressed (compressed_text, version) VALUES (?, ?)",
        (text, version)
    )
    return version


def get_current_compressed_text():
    conn = get_connection()
    text = _current_text(conn.cursor())
    conn.close()
    return text


def list_raw_entries():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, created_at, raw_text, source FROM insight_memory_raw ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return rows


def list_compressed_versions():
    conn = get_connection()
    rows = conn.execute(
        "SELECT version, updated_at, compressed_text FROM insight_memory_compressed ORDER BY version DESC"
    ).fetchall()
    conn.close()
    return rows


def _manual_user_content(current_text, raw_text):
    return (
        f"BISHERIGER VERDICHTETER TEXT:\n{current_text or '(noch leer)'}\n\n"
        f"NEUER ROHTEXT-EINTRAG DES ATHLETEN:\n{raw_text}"
    )


def add_raw_entry(raw_text, source="user"):
    """Speichert den Rohtext sofort (unabhängig vom Gemini-Erfolg im Archiv gesichert),
    verdichtet danach synchron. Ein Gemini-Fehler wird hochgereicht, damit die UI ihn anzeigen
    kann - der Rohtext ist zu diesem Zeitpunkt aber schon sicher gespeichert."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO insight_memory_raw (raw_text, source) VALUES (?, ?)",
        (raw_text, source)
    )
    current_text = _current_text(cursor)
    conn.commit()
    conn.close()

    updated_text = _compress(_manual_user_content(current_text, raw_text))

    conn = get_connection()
    cursor = conn.cursor()
    _save_new_version(cursor, updated_text)
    conn.commit()
    conn.close()
    return updated_text


def delete_raw_entry(entry_id):
    """Löscht nur aus insight_memory_raw - löst ausdrücklich KEINE Neuverdichtung aus."""
    conn = get_connection()
    conn.execute("DELETE FROM insight_memory_raw WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
