import os
import json
import sqlite3
from datetime import date
from google import genai
from google.genai import types
from db import get_connection

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def generate_daily_coaching(target_date=None):
    if not target_date:
        target_date = date.today().isoformat()

    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY fehlt in der .env Datei!")

    conn = get_connection()
    cursor = conn.cursor()

    # 1. Garmin-Daten des Tages laden
    cursor.execute("SELECT * FROM garmin_daily WHERE date = ?", (target_date,))
    garmin = cursor.fetchone()

    # 2. Subjektives Tagesjournal laden
    cursor.execute("SELECT * FROM daily_journal WHERE date = ?", (target_date,))
    journal = cursor.fetchone()

    conn.close()

    if not garmin:
        return {"error": "Keine Garmin-Daten für diesen Tag gefunden. Bitte zuerst synchronisieren!"}

    # Daten für den Prompt aufbereiten
    garmin_dict = dict(garmin) if garmin else {}
    journal_dict = dict(journal) if journal else {}

    # System-Instruction & Guardrails definieren
    system_prompt = """
    Du bist ein hochklassiger Ausdauersport-Coach und Datenanalyst. Deine Aufgabe ist es, die harten physiologischen Daten (Schlaf, HRV, Ruhepuls) und die subjektiven Empfindungen des Athleten zu analysieren.
    
    LEITPLANKEN FÜR DEN READINESS SCORE (0 bis 100):
    - Wenn Schlaf < 6 Stunden ODER HRV deutlich unter Schnitt -> Score MAXIMAL 55 (Fokus: Aktive Erholung / Grundlagen leicht).
    - Wenn Schlaf > 7.5 Stunden UND Ruhepuls normal UND Muskelkater gering -> Score 75 bis 95 (Fokus: Belastung/Intervalle möglich).
    - Sei realistisch, präzise und gib konkrete Handlungsempfehlungen für das heutige Training.

    GIB DEINE ANTWORT AUSSCHLIESSLICH IM FOLGENDEN VALIDEN JSON-FORMAT ZURÜCK:
    {
      "readiness_score": <Zahl zwischen 0 und 100>,
      "status_summary": "<Kurzer Prägnanter Satz zum Tageszustand>",
      "coaching_advice": "<Detaillierte Empfehlung für das heutige Training und die Regeneration>"
    }
    """

    user_input = f"""
    Datum: {target_date}
    Physiologische Daten (Garmin):
    - Ruhepuls: {garmin_dict.get('resting_hr')} bpm
    - HRV-Schnitt: {garmin_dict.get('avg_hrv')} ms
    - Schlaf-Score: {garmin_dict.get('sleep_score')}/100 ({garmin_dict.get('sleep_hours')} Std)
    - Stress-Level: {garmin_dict.get('stress_avg')}

    Subjektives Befinden (Athleten-Eingabe):
    - Belastungseindruck (RPE): {journal_dict.get('rpe_score', 'Nicht angegeben')}/10
    - Muskelkater: {journal_dict.get('muscle_soreness', 'Nicht angegeben')}/5
    - Energielevel: {journal_dict.get('energy_level', 'Nicht angegeben')}/5
    - Tagesnotizen: {journal_dict.get('notes', 'Keine Notizen')}
    """

    # Gemini API Aufruf
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model='models/gemini-3.5-flash',  # ✅ Aktuelles Flash-Modell
        contents=user_input,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=0.2
        ),
    )

    result_json = json.loads(response.text)

    # In Datenbank cachen
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO ai_coach_insights (date, readiness_score, status_summary, coaching_advice, model_used)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(date) DO UPDATE SET
        readiness_score=excluded.readiness_score,
        status_summary=excluded.status_summary,
        coaching_advice=excluded.coaching_advice,
        model_used=excluded.model_used;
    """, (target_date, result_json["readiness_score"], result_json["status_summary"], result_json["coaching_advice"], "gemini-3.5-flash"))
    conn.commit()
    conn.close()

    return result_json