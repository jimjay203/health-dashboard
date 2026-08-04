"""
Schicht 3 der KI-Chat-Vorbereitung: LLM-gestütztes Erkenntnis-Gedächtnis. Im Gegensatz zu
Schicht 1/2 (daily_summary.py/weekly_summary.py, rein regelbasiert) nutzt dieses Modul echte
Gemini-Calls, um ein kompaktes, sich selbst aktualisierendes Wissens-Gedächtnis über den
Athleten zu pflegen - gespeist aus manuellen Freitext-Einträgen (Teil A) und täglich aus den
bereits vorhandenen Schicht-1/2-Kennzahlen (Teil B).
"""
import json
from datetime import date, timedelta
from google.genai import types
from db import get_connection
from gemini_client import MODEL_NAME, get_client

DAILY_CONTEXT_LOOKBACK_DAYS = 7
DAILY_COMPRESSION_WORD_TARGET = 500

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"updated_compressed_text": {"type": "STRING"}},
    "required": ["updated_compressed_text"],
}

MANUAL_SYSTEM_PROMPT = """
Du pflegst ein kompaktes, aktuelles Wissens-Gedächtnis über einen Ausdauersportler (Marathon und
Triathlon), das später als Kontext für einen KI-Coach/Chat dient. Du bekommst den bisherigen
verdichteten Text sowie einen neuen Rohtext-Eintrag des Athleten.

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

DAILY_SYSTEM_PROMPT = f"""
Du pflegst dasselbe Wissens-Gedächtnis, diesmal anhand automatisch berechneter Trainings- und
Erholungskennzahlen der letzten Tage (nicht Freitext des Athleten).

Aktualisiere den bestehenden Text um wirklich bemerkenswerte neue Erkenntnisse (z.B. veränderte
Belastungslage, auffällige Trends, erreichte/verpasste Meilensteine, dauerhafte Muster) -
ignoriere normale Tagesschwankungen ohne Aussagekraft.

WICHTIG: Halte den Text ausdrücklich KOMPAKT - Zielgröße ca. {DAILY_COMPRESSION_WORD_TARGET} Wörter,
eher kürzer. Wenn der Text an diese Grenze stößt, fasse bestehende Punkte weiter zusammen statt nur
anzuhängen, und lass veraltete, nicht mehr relevante Details bewusst fallen.

Gib AUSSCHLIESSLICH valides JSON zurück im Format:
{{"updated_compressed_text": "<vollständiger aktualisierter Text>"}}
"""


def _fmt(value, suffix="", fallback="n/a"):
    return f"{value}{suffix}" if value is not None else fallback


def _compress(system_prompt, user_content):
    """Gemeinsamer Gemini-Call für Teil A (manuell) und Teil B (täglich). Striktes response_schema
    statt nur response_mime_type="application/json" - ohne Schema keine garantiert valide
    JSON-Ausgabe (siehe ai_coach.py, dort schon einmal zu einem Parse-Crash geführt)."""
    client = get_client()
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
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
    """Teil A: speichert den Rohtext sofort (unabhängig vom Gemini-Erfolg im Archiv gesichert),
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

    updated_text = _compress(MANUAL_SYSTEM_PROMPT, _manual_user_content(current_text, raw_text))

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


def _already_ran_today(cursor, target_date):
    row = cursor.execute(
        "SELECT 1 FROM insight_memory_daily_run WHERE date = ?", (target_date,)
    ).fetchone()
    return row is not None


def _mark_ran_today(cursor, target_date):
    cursor.execute(
        "INSERT INTO insight_memory_daily_run (date) VALUES (?) ON CONFLICT(date) DO NOTHING",
        (target_date,)
    )


def _daily_context_text(cursor, target_date):
    ds = cursor.execute("SELECT * FROM daily_summary WHERE date = ?", (target_date,)).fetchone()

    target = date.fromisoformat(target_date)
    iso_year, iso_week, _ = target.isocalendar()
    week_id = f"{iso_year}-W{iso_week:02d}"
    ws_current = cursor.execute("SELECT * FROM weekly_summary WHERE week_id = ?", (week_id,)).fetchone()

    py, pw, _ = (target - timedelta(weeks=1)).isocalendar()
    prev_week_id = f"{py}-W{pw:02d}"
    ws_prev = cursor.execute("SELECT * FROM weekly_summary WHERE week_id = ?", (prev_week_id,)).fetchone()

    start = (target - timedelta(days=DAILY_CONTEXT_LOOKBACK_DAYS - 1)).isoformat()
    activities = cursor.execute("""
        SELECT a.activity_name, a.activity_type, date(a.start_time_local) AS d,
               ROUND(a.distance_meters / 1000.0, 1) AS km, a.activity_training_load,
               aa.decoupling_pct, aa.outlier_flag
        FROM garmin_activities a
        LEFT JOIN activity_analytics aa ON aa.activity_id = a.activity_id
        WHERE date(a.start_time_local) >= ? AND date(a.start_time_local) <= ?
        ORDER BY a.start_time_local
    """, (start, target_date)).fetchall()

    lines = [f"Datum: {target_date}", ""]

    lines.append("Tageskennzahlen (daily_summary):")
    if ds:
        d = dict(ds)
        lines.append(f"- HRV vs. 7-Tage-Schnitt: {_fmt(d.get('hrv_vs_7d_avg_pct'), '%')}")
        lines.append(f"- Schlaf vs. 7-Tage-Schnitt: {_fmt(d.get('sleep_vs_7d_avg_pct'), '%')}")
        lines.append(f"- ACWR: {_fmt(d.get('acute_chronic_ratio'))}")
        lines.append(f"- CTL/ATL/TSB (Fitness/Ermüdung/Form): {_fmt(d.get('ctl'))} / "
                      f"{_fmt(d.get('atl'))} / {_fmt(d.get('tsb'))}")
        lines.append(f"- Übertrainingsrisiko-Flag: {_fmt(d.get('overreach_flag'))}")
        lines.append(f"- Auffälligkeit: {_fmt(d.get('notable_events_text'))}")
    else:
        lines.append("- keine daily_summary für heute vorhanden")

    lines.append("")
    lines.append("Aktuelle Woche (weekly_summary):")
    if ws_current:
        w = dict(ws_current)
        lines.append(f"- Volumen: Laufen {_fmt(w.get('volume_running_km'))} km, "
                      f"Rad {_fmt(w.get('volume_cycling_km'))} km, "
                      f"Schwimmen {_fmt(w.get('volume_swimming_km'))} km")
        lines.append(f"- Zonen-Verteilung Z1-2/Z3+: {_fmt(w.get('zone_distribution_z1_z2_pct'), '%')} / "
                      f"{_fmt(w.get('zone_distribution_z3_plus_pct'), '%')}")
        lines.append(f"- Trainingsphase: {_fmt(w.get('training_phase'))}, "
                      f"Tage bis Rennen: {_fmt(w.get('days_until_next_race'))}")
        lines.append(f"- Discipline-Limiter: {_fmt(w.get('discipline_limiter'))}")
        lines.append(f"- Auffälligkeit: {_fmt(w.get('notable_events_text'))}")
    else:
        lines.append("- keine weekly_summary für die aktuelle Woche vorhanden")
    if ws_prev:
        wp = dict(ws_prev)
        lines.append(f"- Vorwoche zum Vergleich: {_fmt(wp.get('volume_total_minutes'))} Min. gesamt, "
                      f"Phase {_fmt(wp.get('training_phase'))}")

    lines.append("")
    lines.append(f"Aktivitäten der letzten {DAILY_CONTEXT_LOOKBACK_DAYS} Tage:")
    if activities:
        for a in activities:
            ad = dict(a)
            entry = (f"- {ad['d']} {ad['activity_type']} \"{ad['activity_name']}\": "
                     f"{_fmt(ad.get('km'))} km, Load {_fmt(ad.get('activity_training_load'))}")
            if ad.get("decoupling_pct") is not None:
                entry += f", Decoupling {_fmt(ad.get('decoupling_pct'), '%')}"
            if ad.get("outlier_flag"):
                entry += ", ⚠️ Ausreißer"
            lines.append(entry)
    else:
        lines.append("- keine Aktivitäten in diesem Zeitraum")

    return "\n".join(lines)


def _daily_user_content(current_text, context_text):
    return (
        f"BISHERIGER VERDICHTETER TEXT:\n{current_text or '(noch leer)'}\n\n"
        f"AKTUELLE TRAININGS-/ERHOLUNGSKENNZAHLEN:\n{context_text}"
    )


def run_daily_memory_update(target_date=None):
    """Teil B: läuft pro Kalendertag höchstens einmal (Trigger-Gate insight_memory_daily_run),
    unabhängig davon, wie oft der Garmin-Sync an diesem Tag aufgerufen wird. Ein Gemini-Fehler
    wird abgefangen und geloggt statt hochgereicht, damit der umgebende Garmin-Sync nicht
    abbricht (analog zu garmin_service._safe_call)."""
    if not target_date:
        target_date = date.today().isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    if _already_ran_today(cursor, target_date):
        conn.close()
        return None

    context_text = _daily_context_text(cursor, target_date)
    current_text = _current_text(cursor)
    conn.close()

    try:
        updated_text = _compress(DAILY_SYSTEM_PROMPT, _daily_user_content(current_text, context_text))
    except Exception as e:
        print(f"⚠️  Schicht-3-Tageslauf übersprungen ({target_date}): {e}")
        return None

    conn = get_connection()
    cursor = conn.cursor()
    _save_new_version(cursor, updated_text)
    _mark_ran_today(cursor, target_date)
    conn.commit()
    conn.close()
    return updated_text
