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
from db import get_connection, upsert_daily_metric
from gemini_client import MODEL_NAME, get_client
from context_blocks import strip_markdown_fences

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"insight_text": {"type": "STRING"}},
    "required": ["insight_text"],
}

SYSTEM_PROMPT = """
Du ordnest für einen Marathon-/Triathlon-Athleten vier bereits BERECHNETE Korrelationen zwischen
Vorabend-Faktoren und seinem Sleep Score der letzten 28 Nächte ein. Du bekommst zu jeder
Korrelation den Pearson-Korrelationskoeffizienten (bzw. bei der binären "späte Einheit"-Auswertung
die Gruppen-Mittelwerte), die Stichprobengröße und eine bereits vorberechnete Stärke-Einordnung.

WICHTIG: Erfinde oder berechne KEINE eigenen Zahlen - nutze ausschließlich die gegebenen Werte.
Bei kleiner Stichprobe (n < 10) weise explizit auf die geringe Aussagekraft hin. Korrelation ist
keine Kausalität - formuliere entsprechend vorsichtig ("könnte", "deutet an" statt "beweist").

Schreibe 3-5 kurze Sätze/Stichpunkte auf Deutsch, die die vier Zusammenhänge einordnen und - falls
plausibel - eine konkrete Handlungsidee für besseren Schlaf ableiten.

Gib AUSSCHLIESSLICH valides JSON zurück im Format: {"insight_text": "<Text>"}
"""


def _pearson(pairs):
    n = len(pairs)
    if n < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def _strength_label(r):
    abs_r = abs(r)
    direction = "positiver" if r > 0 else "negativer"
    if abs_r < 0.1:
        return "kein erkennbarer Zusammenhang"
    if abs_r < 0.3:
        return f"schwacher {direction} Zusammenhang"
    if abs_r < 0.5:
        return f"moderater {direction} Zusammenhang"
    return f"starker {direction} Zusammenhang"


def _correlation_block(label, pairs):
    n = len(pairs)
    r = _pearson(pairs)
    if r is None:
        return f"{label}: n={n} - zu wenig Datenpunkte oder keine Varianz für eine Korrelation."
    return f"{label}: r={r:.2f} ({_strength_label(r)}), n={n}"


def _late_workout_block(late_scores, not_late_scores):
    if len(late_scores) < 2 or len(not_late_scores) < 2:
        return (
            f"Späte Einheit (Training ab 18 Uhr) vs. Sleep Score: n_spät={len(late_scores)}, "
            f"n_nicht_spät={len(not_late_scores)} - zu wenig Datenpunkte."
        )
    avg_late = sum(late_scores) / len(late_scores)
    avg_not_late = sum(not_late_scores) / len(not_late_scores)
    return (
        f"Späte Einheit (Training ab 18 Uhr) vs. Sleep Score: "
        f"Ø mit später Einheit={avg_late:.1f} (n={len(late_scores)}), "
        f"Ø ohne={avg_not_late:.1f} (n={len(not_late_scores)}), Differenz={avg_late - avg_not_late:+.1f} Punkte."
    )


def _gather_context(points):
    """points: Liste von SleepTrendPoint (siehe backend/routers/sleep.py::get_sleep_trend) -
    exakt dieselben Paare wie die vier Korrelations-Charts im Frontend (SleepCorrelations,
    SleepView.tsx), damit Text und Charts nie auseinanderlaufen."""
    training_load_pairs = [
        (p.prev_day_training_load, p.sleep_score) for p in points
        if p.prev_day_training_load is not None and p.sleep_score is not None
    ]
    hrv_pairs = [
        (p.avg_overnight_hrv, p.sleep_score) for p in points
        if p.avg_overnight_hrv is not None and p.sleep_score is not None
    ]
    rpe_pairs = [
        (p.prev_day_rpe, p.sleep_score) for p in points
        if p.prev_day_rpe is not None and p.sleep_score is not None
    ]
    late_scores = [p.sleep_score for p in points if p.prev_day_late_workout and p.sleep_score is not None]
    not_late_scores = [
        p.sleep_score for p in points
        if not p.prev_day_late_workout and p.prev_day_training_load is not None and p.sleep_score is not None
    ]

    return "\n".join([
        _correlation_block("Trainingslast am Vorabend vs. Sleep Score", training_load_pairs),
        _late_workout_block(late_scores, not_late_scores),
        _correlation_block("Overnight-HRV vs. Sleep Score", hrv_pairs),
        _correlation_block("Belastungsempfinden (RPE) am Vorabend vs. Sleep Score", rpe_pairs),
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
