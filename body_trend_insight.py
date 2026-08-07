"""
Gemini-Einordnung der "Trend (90 Tage)"-Charts auf der Körper-Seite (BodyView.tsx): Gewicht,
Muskelmasse vs. Fettmasse, Körperfett %, Wasser & Knochenmasse. Reine Python-Logik, kein
Streamlit-Import (gleiches Muster wie sleep_trend_insight.py). Kennzahlen werden hier selbst in
Python berechnet - Gemini bekommt nur die fertigen Zahlen zur Einordnung/Formulierung. Cache pro
Tag, da sich der zugrundeliegende 90-Tage-Trend innerhalb eines Tages nicht ändert.
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
Du ordnest für einen Marathon-/Triathlon-Athleten seinen 90-Tage-Körperzusammensetzungstrend ein.
Du bekommst bereits BERECHNETE Kennzahlen: Gewichtsveränderung (Anfang vs. Ende des Zeitraums, auf
Basis des gleitenden 7-Tage-Durchschnitts), Veränderung von Muskelmasse und Fettmasse, Veränderung
des Körperfettanteils, sowie zur Kontrolle Wasser-/Knochenmasse.

WICHTIG: Erfinde oder berechne KEINE eigenen Zahlen - nutze ausschließlich die gegebenen Werte. Bei
kleiner Stichprobe (n < 10) weise explizit auf die geringe Aussagekraft hin.

Ordne besonders ein, ob es sich um reinen Gewichtsverlust/-zuwachs oder um eine "Rekomposition"
handelt (Gewicht ändert sich kaum, aber Muskelmasse und Fettmasse verändern sich gegenläufig) - das
ist für Ausdauersportler oft aussagekräftiger als die reine Gewichtszahl.

Schreibe 3-5 kurze Sätze/Stichpunkte auf Deutsch.

Gib AUSSCHLIESSLICH valides JSON zurück im Format: {"insight_text": "<Text>"}
"""


def _first_last_avg(values, window=3):
    """Ø der ersten/letzten `window` vorhandenen Werte - robuster gegen Tagesrauschen als ein
    einzelner erster/letzter Messwert (gleiches Prinzip wie die 7-Tage-Gewichtsglättung in
    body_composition.py::get_body_trend)."""
    if len(values) < 2:
        return None, None
    first = values[:window]
    last = values[-window:]
    return sum(first) / len(first), sum(last) / len(last)


def _weight_block(points):
    values = [(p["date"], p["weight_rolling_avg_kg"]) for p in points if p["weight_rolling_avg_kg"] is not None]
    if len(values) < 2:
        return f"Gewicht: n={len(values)} - zu wenig Datenpunkte."
    dates = [v[0] for v in values]
    weights = [v[1] for v in values]
    first_avg, last_avg = _first_last_avg(weights)
    return (
        f"Gewicht (gleitender 7-Tage-Schnitt, Ø erste/letzte 3 Messungen): {dates[0]}={first_avg:.1f}kg -> "
        f"{dates[-1]}={last_avg:.1f}kg (Δ{last_avg - first_avg:+.1f}kg), n={len(values)} Tage mit Messung."
    )


def _composition_block(points):
    muscle = [p["muscle_mass_kg"] for p in points if p["muscle_mass_kg"] is not None]
    fat = [p["fat_mass_kg"] for p in points if p["fat_mass_kg"] is not None]
    body_fat_pct = [p["body_fat_pct"] for p in points if p["body_fat_pct"] is not None]
    if len(muscle) < 2 or len(fat) < 2:
        return f"Körperzusammensetzung: n_muskel={len(muscle)}, n_fett={len(fat)} - zu wenig Datenpunkte."

    m_first, m_last = _first_last_avg(muscle)
    f_first, f_last = _first_last_avg(fat)
    parts = [
        f"Muskelmasse {m_first:.1f}kg -> {m_last:.1f}kg (Δ{m_last - m_first:+.1f}kg)",
        f"Fettmasse {f_first:.1f}kg -> {f_last:.1f}kg (Δ{f_last - f_first:+.1f}kg)",
    ]
    if len(body_fat_pct) >= 2:
        bf_first, bf_last = _first_last_avg(body_fat_pct)
        parts.append(f"Körperfett {bf_first:.1f}% -> {bf_last:.1f}% (Δ{bf_last - bf_first:+.1f}pp)")
    return f"Körperzusammensetzung (Ø erste/letzte 3 Messungen, n={len(muscle)}): " + ", ".join(parts) + "."


def _hydration_block(points):
    water = [p["body_water_kg"] for p in points if p["body_water_kg"] is not None]
    bone = [p["bone_mass_kg"] for p in points if p["bone_mass_kg"] is not None]
    if len(water) < 2 or len(bone) < 2:
        return "Wasser/Knochenmasse: zu wenig Datenpunkte."
    w_first, w_last = _first_last_avg(water)
    b_first, b_last = _first_last_avg(bone)
    return (
        f"Zur Kontrolle - Wasser {w_first:.1f}kg -> {w_last:.1f}kg (Δ{w_last - w_first:+.1f}kg), "
        f"Knochenmasse {b_first:.1f}kg -> {b_last:.1f}kg (Δ{b_last - b_first:+.1f}kg)."
    )


def _gather_context(points):
    """points: Liste von Dicts aus body_composition.py::get_body_trend()["points"] - dieselben
    Daten wie die Trend-Charts im Frontend (CompositionTrendCharts, BodyView.tsx)."""
    return "\n".join([
        _weight_block(points),
        _composition_block(points),
        _hydration_block(points),
    ])


def generate_trend_insight(target_date, points):
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

    upsert_daily_metric("body_trend_insight", {
        "date": target_date,
        "insight_text": insight_text,
        "generated_at": generated_at,
    })

    return {"date": target_date, "insight_text": insight_text, "generated_at": generated_at}


def get_cached_trend_insight(target_date):
    conn = get_connection()
    row = conn.execute("SELECT * FROM body_trend_insight WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    if not row:
        return None
    return {"date": row["date"], "insight_text": row["insight_text"], "generated_at": row["generated_at"]}
