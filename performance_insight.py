"""
Gemini-Einschätzung zu den Leistungszielen auf der "Leistung"-Seite (PerformanceView.tsx):
Erreichbarkeit der hinterlegten Ziele + konkrete Tipps, auf Basis derselben Kennzahlen, die die
Seite selbst zeigt (Ziele, Trainingszustand/CTL-ATL-TSB, Belastungsfokus, Schwellenwerte,
Wettkampf-Prognosen, Rad-Wirkungsgrad, Schwimm-Diagnostik) sowie des geteilten Erkenntnis-
Gedächtnisses (context_blocks.py::insight_memory_block, siehe insight_memory.py) - dort trägt der
Athlet Dinge ein, die sich nicht aus den Daten ablesen lassen (Datenlücken, Korrekturen an
ungenauen Garmin-Schätzungen, Bestzeiten). Reine Python-Logik, kein Streamlit-/
FastAPI-Import (gleiches Muster wie body_trend_insight.py). Kontext-Werte werden bewusst über
eigene, schlanke SQL-Abfragen direkt ermittelt statt aus backend/routers/performance.py importiert
- der Router lebt nur innerhalb der Docker-Flattening-Struktur (siehe backend/Dockerfile), dieses
Modul soll wie alle anderen *_insight.py-Module unabhängig davon lauffähig/testbar bleiben. Cache
pro Tag (wie body_trend_insight.py) - zusätzlich invalidiert bei jeder Ziel-Änderung (siehe
invalidate_today_cache(), aufgerufen aus backend/routers/performance.py bei PUT/DELETE /goals),
da die Einschätzung sonst bis zum nächsten Tag auf einem veralteten Ziel-Stand stehen bliebe.

Ziele/Schwellenwerte/Wettkampf-Prognosen/Schwimm-Diagnostik kommen aus performance_snapshot.py
(geteilt mit weekly_planner.py, damit beide KI-Aufrufe auf denselben Zahlen basieren) - nur
Trainingszustand (CTL/ATL/TSB) und Belastungsfokus (load_focus.py) bleiben hier, da beide
Aufrufer dafür ihre eigenen, unterschiedlich geformten Kontext-Blöcke haben.
"""
import json
from datetime import date, datetime, timedelta

from google.genai import types
from db import get_connection, upsert_daily_metric
from gemini_client import MODEL_NAME, get_client
from context_blocks import strip_markdown_fences, insight_memory_block
from load_focus import compute_load_focus, LOAD_FOCUS_WINDOW_DAYS
from performance_snapshot import gather_performance_snapshot

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"insight_text": {"type": "STRING"}},
    "required": ["insight_text"],
}

SYSTEM_PROMPT = """
Du bist Trainingscoach für einen Marathon-/Triathlon-Athleten und schätzt seine hinterlegten
Leistungsziele ein: wie erreichbar sind sie (insbesondere falls ein Zieldatum gesetzt ist), und was
sollte er konkret tun, um dahin zu kommen?

Du bekommst bereits BERECHNETE Kennzahlen: die Ziele selbst (Ziel- vs. aktueller Wert, Zieldatum),
den aktuellen Trainingszustand (CTL/ATL/TSB, akute vs. chronische Belastung, Trend der letzten 90
Tage), die Belastungsfokus-Verteilung (Anteil niedrig-aerob/hoch-aerob/anaerob der letzten 28 Tage,
mit dem gängigen 80/20-Polarisierungsrichtwert), Leistungsdiagnostik-Schwellenwerte je Disziplin,
Wettkampf-Prognosen sowie einen Block "ZUSATZKONTEXT VOM ATHLETEN" mit vom Athleten selbst
eingetragenen Hintergrundinfos (z.B. Korrekturen an ungenauen Garmin-Schätzungen, Bestzeiten,
Datenlücken) - diese Infos haben Vorrang vor den berechneten Werten, falls sie sich widersprechen
(z.B. eine vom Athleten korrigierte Pace-Schätzung statt der rohen Garmin-Prognose).

WICHTIG: Erfinde oder berechne KEINE eigenen Zahlen - nutze ausschließlich die gegebenen Werte. Bei
fehlenden Daten (kein Ziel gesetzt, kein Zieldatum, keine Diagnostik-Messung) das explizit benennen
statt eine Einschätzung vorzutäuschen. Beachte den CTL-Trend nur für den Zeitraum, für den laut
Zusatzkontext tatsächlich durchgängige Garmin-Daten vorliegen - ein Sprung von 0 davor ist meist nur
ein Datenlücken-Artefakt, keine reale Fitness-Entwicklung.

Gehe wenn möglich auf JEDES hinterlegte Ziel einzeln ein (kurz), ordne dann übergreifend ein, ob der
aktuelle Trainingszustand/Belastungsfokus die Ziele unterstützt oder eher bremst, und schließe mit
2-3 konkreten, auf die Daten gestützten Tipps (z.B. Belastungsfokus verschieben, TSB-Lage beachten,
disziplinspezifisch).

Schreibe 4-7 kurze Sätze/Stichpunkte auf Deutsch.

Gib AUSSCHLIESSLICH valides JSON zurück im Format: {"insight_text": "<Text>"}
"""

# Gleiche 5 Bänder wie backend/routers/performance.py::TSB_BANDS - bewusst hier dupliziert statt
# importiert (siehe Moduldocstring), stabile/kleine Lookup-Tabelle, geringes Drift-Risiko.
TSB_BANDS = [
    (-1e9, -30, "Hohes Ermüdungsrisiko"),
    (-30, -10, "Produktiv"),
    (-10, 5, "Erhaltend"),
    (5, 25, "Frisch"),
    (25, 1e9, "Formverlust-Risiko"),
]

CTL_TREND_WINDOW_DAYS = 90


def _classify_tsb(tsb):
    if tsb is None:
        return None
    for low, high, label in TSB_BANDS:
        if low <= tsb < high:
            return label
    return None


def _load_status_block(conn, target_date):
    daily = conn.execute(
        "SELECT date, ctl, atl, tsb FROM daily_summary WHERE date <= ? AND tsb IS NOT NULL "
        "ORDER BY date DESC LIMIT 1",
        (target_date,)
    ).fetchone()
    if not daily:
        return "Trainingszustand: keine CTL/ATL/TSB-Daten vorhanden.", (None, None)

    trend_start = (date.fromisoformat(target_date) - timedelta(days=CTL_TREND_WINDOW_DAYS)).isoformat()
    trend_rows = conn.execute(
        "SELECT date, ctl FROM daily_summary WHERE date >= ? AND date <= ? AND ctl IS NOT NULL "
        "ORDER BY date ASC",
        (trend_start, target_date)
    ).fetchall()
    trend_text = ""
    if len(trend_rows) >= 2:
        first, last = trend_rows[0], trend_rows[-1]
        trend_text = (
            f" CTL-Trend {CTL_TREND_WINDOW_DAYS} Tage: {first['date']}={first['ctl']:.1f} -> "
            f"{last['date']}={last['ctl']:.1f} (Δ{last['ctl'] - first['ctl']:+.1f})."
        )

    state_label = _classify_tsb(daily["tsb"])
    text = (
        f"Trainingszustand ({daily['date']}): CTL(Fitness)={daily['ctl']:.1f}, "
        f"ATL(akute Belastung)={daily['atl']:.1f}, TSB(Form)={daily['tsb']:+.1f} "
        f"({state_label})." + trend_text
    )
    return text, (daily["ctl"], daily["tsb"])


def _load_focus_block(target_date):
    """Nutzt load_focus.py (App-eigene Friel-HF-Zonen statt Garmins eigenen hrTimeInZone-Werten,
    siehe dortiger Ground-Truth-Fund vom 2026-08-07) - included_activities/total_activities_in_window
    werden explizit mitgegeben, damit Gemini die Aussagekraft bei geringer Abdeckung einordnen kann."""
    lf = compute_load_focus(target_date, window_days=LOAD_FOCUS_WINDOW_DAYS)
    if lf["low_aerobic_pct"] is None:
        return (
            f"Belastungsfokus (letzte {LOAD_FOCUS_WINDOW_DAYS} Tage): keine auswertbaren "
            "HF-Zeitreihen vorhanden (nur Laufen/Rad mit synchronisierter Detail-Zeitreihe möglich)."
        )
    return (
        f"Belastungsfokus (letzte {LOAD_FOCUS_WINDOW_DAYS} Tage, berechnet aus {lf['included_activities']} von "
        f"{lf['total_activities_in_window']} Aktivitäten im Fenster - nur Laufen/Rad mit synchronisierter "
        f"Detail-Zeitreihe auswertbar): niedrig-aerob(Z1+Z2)={lf['low_aerobic_pct']:.0f}%, "
        f"hoch-aerob(Z3)={lf['high_aerobic_pct']:.0f}%, anaerob(Z4+Z5)={lf['anaerobic_pct']:.0f}% "
        f"(gängiger Polarisierungsrichtwert: niedrig-aerob ≥70%)."
    )


def _gather_context(target_date):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        memory_text = insight_memory_block(cursor)
        load_status_text, _ = _load_status_block(conn, target_date)
        load_focus_text = _load_focus_block(target_date)
    finally:
        conn.close()

    return "\n".join([
        f"ZUSATZKONTEXT VOM ATHLETEN: {memory_text}",
        gather_performance_snapshot(target_date),
        load_status_text,
        load_focus_text,
    ])


def generate_goals_insight(target_date):
    context = _gather_context(target_date)

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

    upsert_daily_metric("performance_goals_insight", {
        "date": target_date,
        "insight_text": insight_text,
        "generated_at": generated_at,
    })

    return {"date": target_date, "insight_text": insight_text, "generated_at": generated_at}


def get_cached_goals_insight(target_date):
    conn = get_connection()
    row = conn.execute("SELECT * FROM performance_goals_insight WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    if not row:
        return None
    return {"date": row["date"], "insight_text": row["insight_text"], "generated_at": row["generated_at"]}


def invalidate_today_cache():
    """Wird bei jeder Ziel-Änderung (PUT/DELETE /api/performance/goals/{key}) aufgerufen - ohne
    das würde die Einschätzung bis zum nächsten Tages-Cache-Ablauf auf einem veralteten Ziel-Stand
    stehen bleiben."""
    today = date.today().isoformat()
    conn = get_connection()
    conn.execute("DELETE FROM performance_goals_insight WHERE date = ?", (today,))
    conn.commit()
    conn.close()
