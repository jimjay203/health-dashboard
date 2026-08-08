"""
Gemini-Einordnung der "Korrelationen"-Charts auf der Schlaf-Seite (SleepView.tsx). Reine
Python-Logik, kein Streamlit-Import (gleiches Muster wie daily_recommendation.py). Die
Kennzahlen (Pearson-Korrelation/Gruppen-Mittelwerte) werden hier selbst in Python berechnet -
Gemini bekommt nur die fertigen Zahlen zur Einordnung/Formulierung, damit es keine eigenen
Statistik-Werte "schätzt" oder erfindet. Cache pro Tag (wie daily_recommendation.py), da sich der
zugrundeliegende 28-Tage-Trend innerhalb eines Tages nicht ändert.
"""
import json
from datetime import datetime

from google.genai import types
from correlation_stats import pearson_r, strength_bucket
from db import get_connection, upsert_daily_metric
from gemini_client import MODEL_NAME, get_client
from context_blocks import strip_markdown_fences

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"insight_text": {"type": "STRING"}},
    "required": ["insight_text"],
}

SYSTEM_PROMPT = """
Du ordnest für einen Marathon-/Triathlon-Athleten fünf bereits BERECHNETE Korrelationen zwischen
Trainings-Faktoren des Vorabends und Schlaf-/Erholungskennzahlen der letzten 28 Nächte ein
(Sleep Score, Ruhepuls der ersten 3 Schlafstunden, Ruhepuls-/HRV-Abweichung vs. 28-Tage-Schnitt).
Du bekommst zu jeder Korrelation den Pearson-Korrelationskoeffizienten (bzw. bei der binären
"späte Einheit"-Auswertung die Gruppen-Mittelwerte), die Stichprobengröße und eine bereits
vorberechnete Stärke-Einordnung.

WICHTIG: Erfinde oder berechne KEINE eigenen Zahlen - nutze ausschließlich die gegebenen Werte.
Bei kleiner Stichprobe (n < 10) weise explizit auf die geringe Aussagekraft hin. Korrelation ist
keine Kausalität - formuliere entsprechend vorsichtig ("könnte", "deutet an" statt "beweist"). Beim
Ruhepuls/HRV bedeutet ein NIEDRIGERER Ruhepuls bzw. eine POSITIVE HRV-Abweichung bessere Erholung -
anders als beim Sleep Score, wo ein höherer Wert besser ist. Achte bei der Einordnung auf diese
unterschiedliche Richtung.

Schreibe 3-5 kurze Sätze/Stichpunkte auf Deutsch, die die fünf Zusammenhänge einordnen und - falls
plausibel - eine konkrete Handlungsidee für besseren Schlaf/bessere Erholung ableiten.

Gib AUSSCHLIESSLICH valides JSON zurück im Format: {"insight_text": "<Text>"}
"""


_STRENGTH_TEXT = {
    "none": "kein erkennbarer Zusammenhang",
    "weak": "schwacher {direction} Zusammenhang",
    "moderate": "moderater {direction} Zusammenhang",
    "strong": "starker {direction} Zusammenhang",
}


def _strength_label(r):
    direction = "positiver" if r > 0 else "negativer"
    template = _STRENGTH_TEXT[strength_bucket(r)]
    return template.format(direction=direction) if "{direction}" in template else template


def _correlation_block(label, pairs):
    n = len(pairs)
    r = pearson_r(pairs)
    if r is None:
        return f"{label}: n={n} - zu wenig Datenpunkte oder keine Varianz für eine Korrelation."
    return f"{label}: r={r:.2f} ({_strength_label(r)}), n={n}"


def _late_workout_rhr_block(late_values, not_late_values):
    """Vergleicht Ruhepuls der ersten 3 Schlafstunden (first_3h_resting_hr) zwischen Nächten nach
    einer späten Einheit und Nächten ohne - ersetzt den früheren Sleep-Score-Vergleich (siehe
    Plan-Entscheidung: Boxplot/Gruppenvergleich statt Balkendiagramm, präziserer Erholungsmarker
    als der Ganznacht-Score). Niedrigerer Ruhepuls = bessere Erholung (umgekehrte Richtung
    ggü. Sleep Score - siehe SYSTEM_PROMPT)."""
    if len(late_values) < 2 or len(not_late_values) < 2:
        return (
            f"Späte Einheit (Training ab 18 Uhr) vs. Ruhepuls erste 3 Schlafstunden: "
            f"n_spät={len(late_values)}, n_nicht_spät={len(not_late_values)} - zu wenig Datenpunkte."
        )
    avg_late = sum(late_values) / len(late_values)
    avg_not_late = sum(not_late_values) / len(not_late_values)
    return (
        f"Späte Einheit (Training ab 18 Uhr) vs. Ruhepuls erste 3 Schlafstunden: "
        f"Ø mit später Einheit={avg_late:.1f} bpm (n={len(late_values)}), "
        f"Ø ohne={avg_not_late:.1f} bpm (n={len(not_late_values)}), Differenz={avg_late - avg_not_late:+.1f} bpm."
    )


def _gather_context(points):
    """points: Liste von SleepTrendPoint (siehe backend/routers/sleep.py::get_sleep_trend) -
    exakt dieselben Paare wie die fünf Korrelations-Charts im Frontend (SleepView.tsx), damit Text
    und Charts nie auseinanderlaufen. Overnight-HRV-vs-Sleep-Score entfällt (redundant, HRV ist
    bereits Teil des Sleep Scores - siehe Plan-Entscheidung "Bereinigung")."""
    training_load_pairs = [
        (p.prev_day_training_load, p.sleep_score) for p in points
        if p.prev_day_training_load is not None and p.sleep_score is not None
    ]
    rpe_pairs = [
        (p.prev_day_rpe, p.sleep_score) for p in points
        if p.prev_day_rpe is not None and p.sleep_score is not None
    ]
    late_values = [
        p.first_3h_resting_hr for p in points if p.prev_day_late_workout and p.first_3h_resting_hr is not None
    ]
    not_late_values = [
        p.first_3h_resting_hr for p in points
        if not p.prev_day_late_workout and p.prev_day_training_load is not None and p.first_3h_resting_hr is not None
    ]
    training_load_vs_rhr_pairs = [
        (p.prev_day_training_load, p.resting_hr_vs_28d_avg_pct) for p in points
        if p.prev_day_training_load is not None and p.resting_hr_vs_28d_avg_pct is not None
    ]
    anaerobic_vs_hrv_pairs = [
        (p.prev_day_anaerobic_seconds, p.hrv_vs_28d_avg_pct) for p in points
        if p.prev_day_anaerobic_seconds is not None and p.hrv_vs_28d_avg_pct is not None
    ]

    return "\n".join([
        _correlation_block("Trainingslast am Vorabend vs. Sleep Score", training_load_pairs),
        _late_workout_rhr_block(late_values, not_late_values),
        _correlation_block("Belastungsempfinden (RPE) am Vorabend vs. Sleep Score", rpe_pairs),
        _correlation_block(
            "Trainingslast am Vorabend vs. Ruhepuls-Abweichung (Nacht, vs. 28-Tage-Schnitt)",
            training_load_vs_rhr_pairs
        ),
        _correlation_block(
            "Trainings-Intensität am Vorabend (Zone 4/5-Sekunden) vs. Overnight-HRV-Abweichung (vs. 28-Tage-Schnitt)",
            anaerobic_vs_hrv_pairs
        ),
    ])


def generate_correlations_insight(target_date, points):
    context = _gather_context(points)

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
    raw = strip_markdown_fences(response.text or "")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        snippet = raw[:500] if raw else "(leere Antwort)"
        raise RuntimeError(f"Gemini-Antwort war kein valides JSON ({e}). Rohtext (Anfang): {snippet}") from e

    insight_text = result["insight_text"]
    generated_at = datetime.now().isoformat()

    upsert_daily_metric("sleep_correlations_insight", {
        "date": target_date,
        "insight_text": insight_text,
        "generated_at": generated_at,
    })

    return {"date": target_date, "insight_text": insight_text, "generated_at": generated_at}


def get_cached_correlations_insight(target_date):
    conn = get_connection()
    row = conn.execute("SELECT * FROM sleep_correlations_insight WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    if not row:
        return None
    return {"date": row["date"], "insight_text": row["insight_text"], "generated_at": row["generated_at"]}
