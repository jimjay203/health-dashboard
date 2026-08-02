import os
import json
import sqlite3
from datetime import date
from google import genai
from google.genai import types
from db import get_connection

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def _fetch_dict(cursor, table, target_date):
    cursor.execute(f"SELECT * FROM {table} WHERE date = ?", (target_date,))
    row = cursor.fetchone()
    return dict(row) if row else {}


def generate_daily_coaching(target_date=None):
    if not target_date:
        target_date = date.today().isoformat()

    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY fehlt in der .env Datei!")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM garmin_daily WHERE date = ?", (target_date,))
    garmin = cursor.fetchone()

    cursor.execute("SELECT * FROM daily_journal WHERE date = ?", (target_date,))
    journal = cursor.fetchone()

    # Erweiterte Metrik-Gruppen für einen reichhaltigeren Coaching-Kontext
    readiness = _fetch_dict(cursor, "garmin_training_readiness", target_date)
    fitness_age = _fetch_dict(cursor, "garmin_fitness_age", target_date)
    spo2 = _fetch_dict(cursor, "garmin_spo2", target_date)
    respiration = _fetch_dict(cursor, "garmin_respiration_summary", target_date)
    hydration = _fetch_dict(cursor, "garmin_hydration", target_date)
    intensity = _fetch_dict(cursor, "garmin_intensity_minutes", target_date)
    running_tolerance = _fetch_dict(cursor, "garmin_running_tolerance", target_date)
    race_predictions = _fetch_dict(cursor, "garmin_race_predictions", target_date)

    conn.close()

    if not garmin:
        return {"error": "Keine Garmin-Daten für diesen Tag gefunden. Bitte zuerst synchronisieren!"}

    garmin_dict = dict(garmin) if garmin else {}
    journal_dict = dict(journal) if journal else {}

    def fmt(value, suffix="", fallback="Nicht verfügbar"):
        return f"{value}{suffix}" if value is not None else fallback

    system_prompt = """
    Du bist ein hochklassiger Ausdauersport-Coach und Datenanalyst. Deine Aufgabe ist es, die harten physiologischen Daten (Schlaf, HRV, Ruhepuls, erweiterte Garmin-Metriken) und die subjektiven Empfindungen des Athleten zu analysieren.

    LEITPLANKEN FÜR DEN READINESS SCORE (0 bis 100):
    - Wenn Schlaf < 6 Stunden ODER HRV deutlich unter Schnitt -> Score MAXIMAL 55 (Fokus: Aktive Erholung / Grundlagen leicht).
    - Wenn Schlaf > 7.5 Stunden UND Ruhepuls normal UND Muskelkater gering -> Score 75 bis 95 (Fokus: Belastung/Intervalle möglich).
    - Berücksichtige zusätzlich Garmins eigenen Trainingsbereitschafts-Score/Level und die weiteren Kennzahlen (SpO2, Atemfrequenz, Belastungstoleranz, Hydration) als Kontext, um deine Einschätzung zu schärfen.
      Dein Score muss nicht mit Garmins Score übereinstimmen, aber kommentiere relevante Abweichungen kurz in der Begründung.
    - Sei realistisch, präzise und gib konkrete Handlungsempfehlungen für das heutige Training.

    WICHTIG FÜR training_focus UND key_recommendations: Diese werden dem Athleten OHNE den
    Fließtext von coaching_advice angezeigt, direkt und auf einen Blick lesbar - also nicht
    "siehe unten" oder vage, sondern selbsterklärend und konkret formuliert.
    - training_focus: 2-5 Wörter, die den heutigen Trainingsfokus auf einen Blick zusammenfassen
      (z.B. "Aktive Erholung", "Lockerer Dauerlauf möglich", "Intervalle/Tempo möglich").
    - key_recommendations: 2-4 kurze, konkrete Stichpunkte (je max. ca. 8 Wörter), keine ganzen
      Absätze - jeder Punkt für sich verständlich (z.B. "Kein intensives Training heute",
      "Fokus auf Schlaf & Hydration", "Max. 30-45 Min. locker, RPE < 3").

    GIB DEINE ANTWORT AUSSCHLIESSLICH IM FOLGENDEN VALIDEN JSON-FORMAT ZURÜCK:
    {
      "readiness_score": <Zahl zwischen 0 und 100>,
      "status_summary": "<Kurzer Prägnanter Satz zum Tageszustand>",
      "training_focus": "<Trainingsfokus heute in 2-5 Wörtern>",
      "key_recommendations": ["<Stichpunkt 1>", "<Stichpunkt 2>", "<Stichpunkt 3>"],
      "coaching_advice": "<Ausführliche Begründung/Details für das heutige Training und die Regeneration>"
    }
    """

    user_input = f"""
    Datum: {target_date}
    Physiologische Kern-Daten (Garmin):
    - Ruhepuls: {garmin_dict.get('resting_hr')} bpm
    - HRV-Schnitt: {garmin_dict.get('avg_hrv')} ms
    - Schlaf-Score: {garmin_dict.get('sleep_score')}/100 ({garmin_dict.get('sleep_hours')} Std)
    - Stress-Level: {garmin_dict.get('stress_avg')}

    Garmin Trainingsbereitschaft:
    - Score: {fmt(readiness.get('score'), '/100')} (Level: {fmt(readiness.get('level'))})
    - Feedback: {fmt(readiness.get('feedback_long'))}
    - Schlaf-Historie-Faktor: {fmt(readiness.get('sleep_history_factor_percent'), '%')}
    - HRV-Faktor: {fmt(readiness.get('hrv_factor_percent'), '%')}
    - Belastungsverhältnis (ACWR): {fmt(readiness.get('acwr_factor_percent'), '%')}
    - Stress-Historie-Faktor: {fmt(readiness.get('stress_history_factor_percent'), '%')}
    - Empfohlene Erholungszeit: {fmt(round(readiness['recovery_time'] / 60, 1) if readiness.get('recovery_time') else None, ' Std')}

    Weitere Kennzahlen:
    - SpO2 (Ø / niedrigster): {fmt(spo2.get('average_spo2'))} / {fmt(spo2.get('lowest_spo2'))}
    - Atemfrequenz (Ø Schlaf): {fmt(respiration.get('avg_sleep'))}
    - Belastungstoleranz (Running Tolerance): {fmt(running_tolerance.get('tolerance'))} (aktuelle Belastung: {fmt(running_tolerance.get('total_impact_load'))})
    - Intensity Minutes diese Woche: {fmt(intensity.get('weekly_total'))} / Ziel {fmt(intensity.get('week_goal'))}
    - Hydration: {fmt(hydration.get('value_ml'))} / Ziel {fmt(hydration.get('goal_ml'))} ml
    - Fitness-Alter: {fmt(fitness_age.get('fitness_age'))} (chronologisches Alter: {fmt(fitness_age.get('chronological_age'))})
    - Marathon-Zielzeit-Prognose: {fmt(race_predictions.get('time_marathon'), ' Sek.')}

    Subjektives Befinden (Athleten-Eingabe):
    - Belastungseindruck (RPE): {journal_dict.get('rpe_score', 'Nicht angegeben')}/10
    - Muskelkater: {journal_dict.get('muscle_soreness', 'Nicht angegeben')}/5
    - Energielevel: {journal_dict.get('energy_level', 'Nicht angegeben')}/5
    - Tagesnotizen: {journal_dict.get('notes', 'Keine Notizen')}
    """

    # Striktes Response-Schema statt nur response_mime_type="application/json" - ohne Schema
    # garantiert Gemini keine wirklich valide JSON-Ausgabe (nur "JSON-artig"), und ein
    # unescaptes Anführungszeichen im frei generierten coaching_advice-Text kann den
    # String vorzeitig beenden und json.loads mit "Expecting ',' delimiter" crashen lassen.
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "readiness_score": {"type": "INTEGER"},
            "status_summary": {"type": "STRING"},
            "training_focus": {"type": "STRING"},
            "key_recommendations": {"type": "ARRAY", "items": {"type": "STRING"}},
            "coaching_advice": {"type": "STRING"},
        },
        "required": ["readiness_score", "status_summary", "training_focus", "key_recommendations", "coaching_advice"],
    }

    # Gemini API Aufruf
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model='models/gemini-3.5-flash',  # ✅ Aktuelles Flash-Modell
        contents=user_input,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.2
        ),
    )

    try:
        result_json = json.loads(response.text)
    except json.JSONDecodeError as e:
        snippet = response.text[:500] if response.text else "(leere Antwort)"
        raise RuntimeError(f"Gemini-Antwort war kein valides JSON ({e}). Rohtext (Anfang): {snippet}") from e

    # In Datenbank cachen
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO ai_coach_insights (date, readiness_score, status_summary, training_focus, key_recommendations, coaching_advice, model_used)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(date) DO UPDATE SET
        readiness_score=excluded.readiness_score,
        status_summary=excluded.status_summary,
        training_focus=excluded.training_focus,
        key_recommendations=excluded.key_recommendations,
        coaching_advice=excluded.coaching_advice,
        model_used=excluded.model_used;
    """, (
        target_date, result_json["readiness_score"], result_json["status_summary"],
        result_json["training_focus"], json.dumps(result_json["key_recommendations"]),
        result_json["coaching_advice"], "gemini-3.5-flash"
    ))
    conn.commit()
    conn.close()

    return result_json
