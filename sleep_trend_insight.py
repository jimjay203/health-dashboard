"""
Gemini-Einordnung der "Trend (28 Tage)"-Charts auf der Schlaf-Seite (SleepView.tsx): Schlafdauer
vs. persönlichem Bedarf, Schlafphasen-Verteilung, Regelmäßigkeit (Bettzeit/Aufwachzeit). Reine
Python-Logik, kein Streamlit-Import (gleiches Muster wie sleep_insight.py/daily_recommendation.py).
Die Kennzahlen (Mittelwerte/Standardabweichung) werden hier selbst in Python berechnet - Gemini
bekommt nur die fertigen Zahlen zur Einordnung/Formulierung. Cache pro Tag, da sich der
zugrundeliegende 28-Tage-Trend innerhalb eines Tages nicht ändert.
"""
import json
import statistics
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
Du ordnest für einen Marathon-/Triathlon-Athleten seinen 28-Tage-Schlaftrend ein. Du bekommst
bereits BERECHNETE Kennzahlen zu drei Aspekten: (1) Schlafdauer im Verhältnis zum persönlich
berechneten Schlafbedarf inkl. Schlafschuld-Trend, (2) durchschnittliche Schlafphasen-Verteilung
(Tief/Kern/REM), (3) Regelmäßigkeit von Bettzeit und Aufwachzeit (Standardabweichung in Minuten -
je kleiner, desto regelmäßiger).

WICHTIG: Erfinde oder berechne KEINE eigenen Zahlen - nutze ausschließlich die gegebenen Werte.
Bei kleiner Stichprobe (n < 10) weise explizit auf die geringe Aussagekraft hin.

Schreibe 3-5 kurze Sätze/Stichpunkte auf Deutsch, die die drei Aspekte einordnen und - falls
plausibel - eine konkrete Handlungsidee ableiten.

Gib AUSSCHLIESSLICH valides JSON zurück im Format: {"insight_text": "<Text>"}
"""


def _hours_after_noon(iso_local):
    """Wie hoursAfterNoon in SleepView.tsx (0=12:00, 12=Mitternacht, 24=12:00 Folgetag) - dieselbe
    Skala, damit die hier berechnete Standardabweichung zur gleichen Uhrzeit-Interpretation wie im
    Regelmäßigkeits-Chart führt."""
    if not iso_local:
        return None
    hour = int(iso_local[11:13])
    minute = int(iso_local[14:16])
    h = hour + minute / 60
    return h + 12 if h < 12 else h - 12


def _clock_from_hours_after_noon(value):
    normalized = value % 24
    clock_hour = int((normalized + 12) % 24)
    clock_minute = round((normalized % 1) * 60)
    return f"{clock_hour:02d}:{clock_minute:02d}"


def _duration_block(points):
    pairs = [
        (p.sleep_hours, p.sleep_need_seconds) for p in points
        if p.sleep_hours is not None and p.sleep_need_seconds is not None
    ]
    n = len(pairs)
    if n == 0:
        return "Schlafdauer vs. Schlafbedarf: keine Daten."
    avg_hours = sum(h for h, _ in pairs) / n
    avg_need_hours = sum(need / 3600 for _, need in pairs) / n
    pct_met = sum(1 for h, need in pairs if h * 3600 >= need) / n * 100

    debts = [(p.date, p.sleep_debt_cumulative) for p in points if p.sleep_debt_cumulative is not None]
    debt_trend = ""
    if debts:
        latest_date, latest_debt = debts[-1]
        debt_trend = f", aktuelle kumulierte Schlafschuld ({latest_date})={latest_debt:+.1f}h"

    return (
        f"Schlafdauer vs. Schlafbedarf: Ø Schlafdauer={avg_hours:.1f}h, Ø Schlafbedarf={avg_need_hours:.1f}h, "
        f"Bedarf gedeckt an {pct_met:.0f}% der Nächte (n={n}){debt_trend}."
    )


def _phase_block(points):
    deep = [p.deep_pct for p in points if p.deep_pct is not None]
    light = [p.light_pct for p in points if p.light_pct is not None]
    rem = [p.rem_pct for p in points if p.rem_pct is not None]
    n = len(deep)
    if n == 0:
        return "Schlafphasen-Verteilung: keine Daten."
    return (
        f"Schlafphasen-Verteilung (Ø über n={n} Nächte): "
        f"Tief={sum(deep) / len(deep):.0f}%, Kern={sum(light) / len(light):.0f}%, REM={sum(rem) / len(rem):.0f}%."
    )


def _regularity_block(points):
    bedtimes = [_hours_after_noon(p.sleep_start_local) for p in points]
    bedtimes = [b for b in bedtimes if b is not None]
    wake_times = [_hours_after_noon(p.sleep_end_local) for p in points]
    wake_times = [w for w in wake_times if w is not None]

    if len(bedtimes) < 2 or len(wake_times) < 2:
        return f"Regelmäßigkeit: n_bettzeit={len(bedtimes)}, n_aufwachzeit={len(wake_times)} - zu wenig Datenpunkte."

    bedtime_avg = statistics.mean(bedtimes)
    bedtime_stdev_min = statistics.pstdev(bedtimes) * 60
    wake_avg = statistics.mean(wake_times)
    wake_stdev_min = statistics.pstdev(wake_times) * 60

    return (
        f"Regelmäßigkeit: Ø Bettzeit={_clock_from_hours_after_noon(bedtime_avg)} Uhr "
        f"(Streuung ±{bedtime_stdev_min:.0f} Min, n={len(bedtimes)}), "
        f"Ø Aufwachzeit={_clock_from_hours_after_noon(wake_avg)} Uhr "
        f"(Streuung ±{wake_stdev_min:.0f} Min, n={len(wake_times)})."
    )


def _gather_context(points):
    """points: Liste von SleepTrendPoint (siehe backend/routers/sleep.py::get_sleep_trend) -
    dieselben Daten wie SleepDurationChart/SleepPhaseTrendChart/SleepRegularityChart im Frontend."""
    return "\n".join([
        _duration_block(points),
        _phase_block(points),
        _regularity_block(points),
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

    upsert_daily_metric("sleep_trend_insight", {
        "date": target_date,
        "insight_text": insight_text,
        "generated_at": generated_at,
    })

    return {"date": target_date, "insight_text": insight_text, "generated_at": generated_at}


def get_cached_trend_insight(target_date):
    conn = get_connection()
    row = conn.execute("SELECT * FROM sleep_trend_insight WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    if not row:
        return None
    return {"date": row["date"], "insight_text": row["insight_text"], "generated_at": row["generated_at"]}
