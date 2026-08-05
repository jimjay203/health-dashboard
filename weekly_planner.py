"""
Rolling-Horizon-Wochenplaner: generiert einmal wöchentlich (sonntags, siehe auto_sync.py) einen
Grobvorschlag für die kommende Woche (Mo-So), inkl. Workout-Entwürfen für Lauf-Tage. Reine
Python-Logik, kein Streamlit-Import (Portabilitäts-Prinzip, analog zu daily_summary.py/
daily_recommendation.py).

Nutzt bewusst nur real vorhandene Signale (kein Intensitätsverteilungs-Ziel, kein
Frühwarnsystem - stattdessen daily_summary.overreach_flag). Signal-Sammlung (_gather_weekly_
context) ist klar von der Gemini-Aufruf-Logik getrennt, damit sich weitere Signale später
nachrüsten lassen, ohne die Struktur umzubauen.

Ground-Truth-Hinweis: weekly_summary wird ausschließlich rückwirkend befüllt (ein Wochen-Eintrag
entsteht erst, sobald mind. ein Tag dieser Woche synchronisiert wurde) - für die KOMMENDE Woche
existiert beim Sonntags-Lauf noch kein Eintrag. Der Planer liest deshalb die zuletzt
abgeschlossene weekly_summary-Zeile (Ist-Zustand) und überlässt die Projektion "welche Phase
sollte die kommende Woche haben" dem Gemini-Kontext (Renn-Countdown + CTL/ATL/TSB-Trend) - es
wird keine nicht-reale "Phase der kommenden Woche" selbst berechnet.
"""
import json
from collections import Counter
from datetime import date, datetime, timedelta

from google.genai import types
from db import get_connection, upsert_daily_metric
from gemini_client import MODEL_NAME, get_client
from context_blocks import insight_memory_block, strip_markdown_fences
from weekly_summary import TAPER_DAYS_THRESHOLD, PEAK_DAYS_THRESHOLD
from workout_builder import build_interval_running_workout, build_steady_running_workout

WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# Stichwort-Heuristik: welche session_type-Texte deuten auf ein Intervall-/Tempo-Workout hin
# (-> build_interval_running_workout) statt auf einen durchgehenden Lauf (-> build_steady_
# running_workout)? Bewusst einfach gehalten - der Entwurf ist ein Ausgangspunkt für die manuelle
# Verfeinerung über "Workout anpassen" (pages/6_🏗️_Workout_Builder.py), keine Endfassung.
INTERVAL_KEYWORDS = ("intervall", "tempo", "schwellen", "wiederholung")

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "week_rationale": {"type": "STRING"},
        "days": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "date": {"type": "STRING"},
                    "sport_type": {"type": "STRING"},
                    "session_type": {"type": "STRING"},
                    "target_zone": {"type": "STRING"},
                    "target_duration_minutes": {"type": "NUMBER"},
                    "target_distance_m": {"type": "NUMBER"},
                },
                "required": ["date", "sport_type", "session_type"],
            },
        },
    },
    "required": ["week_rationale", "days"],
}

SYSTEM_PROMPT = """
Du bist ein Trainings-Coach-Assistent für einen Marathon-/Triathlon-Athleten. Du planst die
KOMMENDE Trainingswoche (Montag bis Sonntag) basierend auf der zuletzt abgeschlossenen Woche,
dem CTL/ATL/TSB-Trend, einem Übertrainings-Signal, festen Vereinsterminen, dem
Erkenntnis-Gedächtnis, einem Compliance-Vergleich zur Vorwoche (falls vorhanden) und dem
nächsten Rennen.

Für JEDEN der 7 Tage gibst du einen Vorschlag ab - auch für Tage mit festem Vereinstermin (siehe
"FESTE VEREINSTERMINE KOMMENDE WOCHE"). An Vereinstermin-Tagen sind Sportart und die Tatsache,
dass eine Einheit stattfindet, bereits fix - trotzdem bestimmst du Session-Typ/Fokus innerhalb
dieses Rahmens selbst, passend zu dem, was an diesem Slot realistisch möglich ist (die
Zusatzinfo hinter jedem Termin, falls vorhanden, beschreibt das - z.B. "Bahntraining: meist
Intervalle, 400-1000m Wiederholungen") UND zum aktuellen Kontext (z.B. in einer Taper-Woche
trotz Bahntraining nur eine kurze, lockere Aktivierungseinheit vorschlagen). An freien Tagen
bestimmst du Sportart, Session-Typ, Zielzone und Dauer/Distanz komplett selbst - auch Ruhetage
sind ein gültiger Vorschlag (sport_type dann leer lassen, session_type z.B. "Ruhetag").

Falls die Eingabedaten lückenhaft sind (z.B. keine CTL/ATL/TSB-Werte oder keine
zuletzt-abgeschlossene Woche), fixiere trotzdem einen vollständigen Plan, aber benenne die Lücken
kurz in week_rationale statt still auf Annahmen zurückzufallen.

An Wettkampftagen (siehe "WETTKAMPFTAGE IN DIESER WOCHE") schlägst du KEIN Training vor - diese
Tage werden ohnehin automatisch als Wettkampf markiert, unabhängig davon, was du zurückgibst
(sport_type für diesen Tag also einfach leer lassen). Berücksichtige einen Wettkampftag aber bei
der Planung der UMLIEGENDEN Tage (z.B. die Tage direkt davor entlasten, danach Regeneration).

target_zone MUSS - falls gesetzt - exakt einer dieser Werte sein (Friel-Trainingszonen, wie sie
in der App gespeichert sind): "1", "2", "3", "4", "5a", "5b", "5c" - keine Bereiche wie "4-5",
kein "Z"-Präfix, keine anderen Bezeichnungen. Bei Unsicherheit lieber eine einzelne naheliegende
Zone wählen als einen ungültigen Wert.

sport_type MUSS - falls nicht leer (Ruhetag) - exakt einer dieser Werte sein (dieselbe feste
Sportart-Liste, die auch für Vereinstermine verwendet wird): "Schwimmen", "Laufen", "Rad",
"Krafttraining", "Mobility" - keine Synonyme oder andere Schreibweisen (z.B. NICHT "Radfahren"
oder "Joggen").

Gib AUSSCHLIESSLICH valides JSON zurück im Format:
{"week_rationale": "<2-3 Sätze Gesamt-Begründung für die Woche>",
 "days": [{"date": "YYYY-MM-DD", "sport_type": "<Sportart, leer für Ruhetag>",
           "session_type": "<z.B. Intervalltraining, lockerer Dauerlauf, Ruhetag>",
           "target_zone": "<z.B. 2, optional>", "target_duration_minutes": <Zahl, optional>,
           "target_distance_m": <Zahl, optional>}, ... genau 7 Einträge, Montag bis Sonntag]}
"""


def _week_bounds(reference_date):
    """Normalisiert ein beliebiges Datum auf dessen Woche (Montag-Start) - (week_id, week_start,
    [7 date-Objekte Mo-So]). Gleiche isocalendar()-Logik wie weekly_summary.py::_iso_week_info."""
    d = date.fromisoformat(reference_date)
    iso_year, iso_week, iso_weekday = d.isocalendar()
    week_start = d - timedelta(days=iso_weekday - 1)
    week_id = f"{iso_year}-W{iso_week:02d}"
    days = [week_start + timedelta(days=i) for i in range(7)]
    return week_id, week_start, days


def _previous_week_id(week_id):
    """Vorwoche-week_id, über das Montags-Datum berechnet - korrekt über Jahresgrenzen hinweg."""
    year, week = week_id.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    prev_monday = monday - timedelta(days=7)
    prev_iso_year, prev_iso_week, _ = prev_monday.isocalendar()
    return f"{prev_iso_year}-W{prev_iso_week:02d}"


def _recent_weekly_summary_block(cursor, week_id):
    prev_week_id = _previous_week_id(week_id)
    row = cursor.execute(
        "SELECT * FROM weekly_summary WHERE week_id = ?", (prev_week_id,)
    ).fetchone()
    if not row:
        return f"Für die zuletzt abgeschlossene Woche ({prev_week_id}) liegt noch keine weekly_summary vor."
    parts = [f"{k}={row[k]}" for k in row.keys() if k != "week_id" and row[k] is not None]
    return f"LETZTE ABGESCHLOSSENE WOCHE ({prev_week_id}): " + ", ".join(parts)


def _ctl_atl_tsb_trend_block(cursor, week_start):
    start = (week_start - timedelta(days=14)).isoformat()
    end = (week_start - timedelta(days=1)).isoformat()
    rows = cursor.execute(
        "SELECT date, ctl, atl, tsb FROM daily_summary WHERE date >= ? AND date <= ? "
        "AND ctl IS NOT NULL ORDER BY date",
        (start, end)
    ).fetchall()
    if not rows:
        return "Keine CTL/ATL/TSB-Daten für die letzten 14 Tage vorhanden."
    return "\n".join(f"{r['date']}: CTL={r['ctl']:.1f}, ATL={r['atl']:.1f}, TSB={r['tsb']:.1f}" for r in rows)


def _overreach_block(cursor, week_start):
    row = cursor.execute(
        "SELECT date, overreach_flag FROM daily_summary WHERE date < ? AND overreach_flag IS NOT NULL "
        "ORDER BY date DESC LIMIT 1",
        (week_start.isoformat(),)
    ).fetchone()
    if not row:
        return "Kein Übertrainings-Signal vorhanden."
    status = "AKTIV - Warnsignal" if row["overreach_flag"] else "kein Warnsignal"
    return f"Übertrainings-Flag (Stand {row['date']}): {status}"


def _club_slots_for_days(cursor, days):
    """weekday(int) -> Zeile (oder None) für jeden der 7 Tage - einmal berechnet, für Kontext-Text
    UND für is_club_slot/source beim Speichern wiederverwendet."""
    result = {}
    for day in days:
        day_str = day.isoformat()
        row = cursor.execute(
            "SELECT sport_type, label, typical_character FROM club_training_slots "
            "WHERE weekday = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to >= ?) LIMIT 1",
            (day.weekday(), day_str, day_str)
        ).fetchone()
        result[day_str] = row
    return result


def _club_slots_block(days, club_slots_by_day):
    lines = []
    for day in days:
        row = club_slots_by_day.get(day.isoformat())
        if not row:
            continue
        character = f" - {row['typical_character']}" if row["typical_character"] else ""
        lines.append(
            f"{day.isoformat()} ({WEEKDAY_NAMES[day.weekday()]}): {row['sport_type']} "
            f"({row['label']}){character}"
        )
    if not lines:
        return "Keine festen Vereinstermine in der kommenden Woche."
    return "\n".join(lines)


def _race_days_for(cursor, days):
    """date_str -> Renn-Titel für Renntage INNERHALB der geplanten Woche (nicht zu verwechseln mit
    _race_countdown_block, das auch ein Rennen in einer SPÄTEREN Woche referenzieren kann). Wird
    zweifach genutzt: als Kontext-Hinweis fürs Modell UND als programmatische Überschreibung in
    generate_weekly_plan() - Renntage bekommen NIE einen Workout-Vorschlag, unabhängig davon, was
    das Modell zurückgibt (Code-Garantie statt reiner Prompt-Anweisung)."""
    result = {}
    for day in days:
        day_str = day.isoformat()
        row = cursor.execute(
            "SELECT title FROM garmin_scheduled_events WHERE event_date = ? AND is_race = 1 LIMIT 1",
            (day_str,)
        ).fetchone()
        if row:
            result[day_str] = row["title"]
    return result


def _race_days_block(days, race_days):
    if not race_days:
        return "Keine Wettkampftage in dieser Woche."
    lines = [
        f"{day.isoformat()} ({WEEKDAY_NAMES[day.weekday()]}): {race_days[day.isoformat()]}"
        for day in days if day.isoformat() in race_days
    ]
    return "\n".join(lines)


def _race_countdown_block(cursor, week_start):
    # event_date ist der echte Kalendertag, siehe garmin_scheduled_events-Schema-Kommentar in db.py.
    row = cursor.execute(
        "SELECT event_date, title, distance_meters FROM garmin_scheduled_events "
        "WHERE is_race = 1 AND event_date >= ? ORDER BY event_date ASC LIMIT 1",
        (week_start.isoformat(),)
    ).fetchone()
    if not row:
        return "Kein bevorstehendes Rennen geplant."
    days_until = (date.fromisoformat(row["event_date"]) - week_start).days
    distance = f", {row['distance_meters']}m" if row["distance_meters"] else ""
    return f"Nächstes Rennen: {row['title']} am {row['event_date']} (in {days_until} Tagen{distance})"


def _compliance_block(cursor, prev_week_id, prev_week_start, prev_week_end):
    """None, falls für die Vorwoche noch kein weekly_plan existiert (z.B. allererster Lauf) -
    Aufrufer lässt den ganzen Abschnitt dann aus, statt mit Nullen aufzufüllen."""
    planned = cursor.execute(
        "SELECT date, sport_type, session_type, target_duration_minutes, target_distance_m "
        "FROM weekly_plan WHERE week_id = ?", (prev_week_id,)
    ).fetchall()
    if not planned:
        return None

    actual = cursor.execute(
        "SELECT activity_type, distance_meters, duration_seconds, start_time_local "
        "FROM garmin_activities WHERE date(start_time_local) >= ? AND date(start_time_local) <= ?",
        (prev_week_start, prev_week_end)
    ).fetchall()

    planned_lines = []
    for p in planned:
        detail = []
        if p["target_duration_minutes"]:
            detail.append(f"{p['target_duration_minutes']:.0f}min")
        if p["target_distance_m"]:
            detail.append(f"{p['target_distance_m']/1000:.1f}km")
        planned_lines.append(
            f"{p['date']}: {p['sport_type'] or 'Ruhetag'} - {p['session_type']}"
            + (f" ({', '.join(detail)})" if detail else "")
        )

    actual_lines = [
        f"{a['start_time_local'][:10]}: {a['activity_type']}, "
        f"{(a['distance_meters'] or 0) / 1000:.1f}km, {(a['duration_seconds'] or 0) / 60:.0f}min"
        for a in actual
    ]

    return (
        "Geplant:\n" + "\n".join(planned_lines)
        + "\n\nTatsächlich:\n" + ("\n".join(actual_lines) if actual_lines else "(keine Aktivitäten erfasst)")
    )


def _gather_weekly_context(cursor, week_id, week_start, days, club_slots_by_day, race_days):
    prev_week_id = _previous_week_id(week_id)
    prev_week_start = (week_start - timedelta(days=7)).isoformat()
    prev_week_end = (week_start - timedelta(days=1)).isoformat()

    parts = [
        "=== LETZTE ABGESCHLOSSENE WOCHE ===",
        _recent_weekly_summary_block(cursor, week_id),
        "\n=== CTL/ATL/TSB-TREND (14 TAGE) ===",
        _ctl_atl_tsb_trend_block(cursor, week_start),
        "\n=== ÜBERTRAININGS-SIGNAL ===",
        _overreach_block(cursor, week_start),
        "\n=== FESTE VEREINSTERMINE KOMMENDE WOCHE ===",
        _club_slots_block(days, club_slots_by_day),
        "\n=== WETTKAMPFTAGE IN DIESER WOCHE ===",
        _race_days_block(days, race_days),
        "\n=== ERKENNTNIS-GEDÄCHTNIS ===",
        insight_memory_block(cursor),
        "\n=== RENN-COUNTDOWN ===",
        _race_countdown_block(cursor, week_start),
    ]

    compliance = _compliance_block(cursor, prev_week_id, prev_week_start, prev_week_end)
    if compliance is not None:
        parts.append("\n=== COMPLIANCE VORWOCHE (GEPLANT VS. TATSÄCHLICH) ===")
        parts.append(compliance)

    return "\n".join(parts)


def _looks_like_interval_session(session_type):
    text = (session_type or "").lower()
    return any(keyword in text for keyword in INTERVAL_KEYWORDS)


def _build_workout_drafts(cursor, rows):
    """Für jeden Tag mit sport_type="Laufen": Workout-Entwurf bauen (nur zur Validierung, dass die
    Parameter wirklich ein bauartfähiges Workout ergeben) und als builder_name+builder_params_json
    speichern (NICHT das Objekt selbst - siehe Moduldocstring/PROJECT_OVERVIEW.md). Andere
    Sportarten/Ruhetage bekommen bewusst keinen Entwurf (workout_builder.py unterstützt nur
    Laufen)."""
    for row in rows:
        date_str = row["date"]
        cursor.execute("DELETE FROM weekly_plan_workout_draft WHERE date = ?", (date_str,))

        if row["sport_type"] != "Laufen":
            continue

        zone = row["target_zone"] or "2"
        try:
            if _looks_like_interval_session(row["session_type"]):
                # Feste, sinnvolle Default-Struktur (5x1000m) - der Wochenplan liefert nur ein
                # Gesamt-Zielvolumen, keine Intervall-Feinstruktur (Wiederholungsanzahl/-distanz).
                # Der Entwurf ist ein Ausgangspunkt für "Workout anpassen", keine Endfassung.
                builder_name = "build_interval_running_workout"
                params = {
                    "name": f"{row['session_type']} ({date_str})",
                    "warmup_minutes": 10, "warmup_zone": "1",
                    "interval_count": 5,
                    "interval_distance_m": 1000, "interval_duration_sec": None,
                    "interval_target_pace_min_per_km": None, "interval_target_zone": zone,
                    "recovery_duration_sec": 120, "recovery_distance_m": None,
                    "cooldown_minutes": 10, "cooldown_zone": "1",
                }
                build_interval_running_workout(**params)
            else:
                builder_name = "build_steady_running_workout"
                duration = row["target_duration_minutes"]
                distance = row["target_distance_m"] if not duration else None
                params = {
                    "name": f"{row['session_type']} ({date_str})",
                    "target_zone": zone, "target_pace_min_per_km": None,
                    "duration_minutes": duration, "distance_m": distance,
                }
                build_steady_running_workout(**params)
        except Exception as e:
            print(f"⚠️  weekly_planner: Workout-Entwurf für {date_str} übersprungen: {e}")
            continue

        cursor.execute(
            "INSERT INTO weekly_plan_workout_draft (date, builder_name, builder_params_json) "
            "VALUES (?, ?, ?)",
            (date_str, builder_name, json.dumps(params, ensure_ascii=False))
        )


def generate_weekly_plan(reference_date):
    """Generiert den Wochenplan für die Woche, die reference_date enthält (auf Montag normalisiert
    - siehe _week_bounds). Sammelt Kontext, ruft Gemini mit striktem response_schema auf (gleiches
    Muster wie daily_recommendation.py), speichert eine Zeile pro Tag in weekly_plan und baut
    anschließend Workout-Entwürfe für Lauf-Tage. Gibt die gespeicherten Zeilen zurück."""
    week_id, week_start, days = _week_bounds(reference_date)

    conn = get_connection()
    cursor = conn.cursor()
    club_slots_by_day = _club_slots_for_days(cursor, days)
    race_days = _race_days_for(cursor, days)
    context = _gather_weekly_context(cursor, week_id, week_start, days, club_slots_by_day, race_days)
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
    raw = strip_markdown_fences(response.text or "")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        snippet = raw[:500] if raw else "(leere Antwort)"
        raise RuntimeError(f"Gemini-Antwort war kein valides JSON ({e}). Rohtext (Anfang): {snippet}") from e

    week_rationale = result["week_rationale"]
    by_date = {entry["date"]: entry for entry in result["days"]}
    generated_at = datetime.now().isoformat()
    data_quality_flag = None if len(by_date) >= 7 else "unvollständige Modell-Antwort (nicht alle 7 Tage)"

    saved_rows = []
    for day in days:
        day_str = day.isoformat()
        entry = by_date.get(day_str)
        race_title = race_days.get(day_str)

        if entry is None and race_title is None:
            # Datenlücken-Fallback: Tag auslassen statt still auf einen erfundenen Wert
            # zurückzufallen - data_quality_flag oben macht das sichtbar. Wettkampftage
            # (race_title gesetzt) werden dagegen IMMER gespeichert, unabhängig davon, ob das
            # Modell diesen Tag überhaupt beantwortet hat - siehe _race_days_for-Docstring.
            continue

        club_row = club_slots_by_day.get(day_str)

        if race_title:
            # Code-Garantie statt reiner Prompt-Anweisung: Wettkampftage bekommen NIE einen
            # Workout-Vorschlag, egal was das Modell zurückgibt (siehe _race_days_for-Docstring).
            row_data = {
                "date": day_str,
                "week_id": week_id,
                "weekday": day.weekday(),
                "sport_type": None,
                "session_type": f"Wettkampf: {race_title}",
                "target_zone": None,
                "target_duration_minutes": None,
                "target_distance_m": None,
                "is_club_slot": 0,
                "source": "race",
                "week_rationale_text": week_rationale,
                "data_quality_flag": data_quality_flag,
                "generated_at": generated_at,
            }
        else:
            row_data = {
                "date": day_str,
                "week_id": week_id,
                "weekday": day.weekday(),
                "sport_type": entry.get("sport_type") or None,
                "session_type": entry.get("session_type"),
                "target_zone": entry.get("target_zone"),
                "target_duration_minutes": entry.get("target_duration_minutes"),
                "target_distance_m": entry.get("target_distance_m"),
                "is_club_slot": int(club_row is not None),
                "source": "club" if club_row is not None else "generated",
                "week_rationale_text": week_rationale,
                "data_quality_flag": data_quality_flag,
                "generated_at": generated_at,
            }
        upsert_daily_metric("weekly_plan", row_data)
        saved_rows.append(row_data)

    conn = get_connection()
    cursor = conn.cursor()
    _build_workout_drafts(cursor, saved_rows)
    conn.commit()
    conn.close()

    return saved_rows


def get_week_plan(reference_date):
    """Liest die bereits gespeicherten weekly_plan-Zeilen für die Woche um reference_date, ohne
    neu zu generieren - für den Lazy-Fallback in backend/routers/weekly_plan.py."""
    _, week_start, days = _week_bounds(reference_date)
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM weekly_plan WHERE date >= ? AND date <= ? ORDER BY date",
        (days[0].isoformat(), days[-1].isoformat())
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _typical_weekday_pattern(cursor, weekday, sample_weeks=8):
    """Häufigstes sport_type/session_type-Muster für einen Wochentag aus der eigenen
    weekly_plan-Historie - KEIN Gemini-Call. Für einen so weit entfernten, unsicheren Horizont
    (Woche 3) reicht eine aus dem eigenen bisherigen Muster abgeleitete Andeutung, kein neuer
    LLM-Aufruf nötig (und ehrlicher als eine frisch spekulierende Modell-Antwort)."""
    rows = cursor.execute(
        "SELECT sport_type, session_type FROM weekly_plan WHERE weekday = ? AND sport_type IS NOT NULL "
        "AND source != 'race' ORDER BY date DESC LIMIT ?",
        (weekday, sample_weeks)
    ).fetchall()
    if not rows:
        return None, None
    most_common_sport = Counter(r["sport_type"] for r in rows).most_common(1)[0][0]
    matching_sessions = [r["session_type"] for r in rows if r["sport_type"] == most_common_sport and r["session_type"]]
    session_hint = Counter(matching_sessions).most_common(1)[0][0] if matching_sessions else None
    return most_common_sport, session_hint


def get_week_outlook(reference_date):
    """Grobe Tages-Andeutungen für eine weiter entfernte Woche (Woche 3 im Kalender-Widget) -
    KEINE Workout-Details, nur ein kurzer Hinweis pro Tag ("Mittwoch: vermutlich Intervalle"),
    kein Gemini-Call. Club-Slot-/Wettkampf-Tage nutzen die feste Information (Slot-Sportart +
    kurzer typical_character-Auszug bzw. Renn-Titel); freie Tage nutzen das häufigste eigene
    Muster dieses Wochentags aus der weekly_plan-Historie (siehe _typical_weekday_pattern)."""
    _, week_start, days = _week_bounds(reference_date)
    conn = get_connection()
    cursor = conn.cursor()
    club_slots_by_day = _club_slots_for_days(cursor, days)
    race_days = _race_days_for(cursor, days)

    outlook = []
    for day in days:
        day_str = day.isoformat()
        race_title = race_days.get(day_str)
        club_row = club_slots_by_day.get(day_str)

        if race_title:
            outlook.append({
                "date": day_str, "weekday": day.weekday(),
                "sport_type": None, "hint": f"Wettkampf: {race_title}",
            })
            continue

        if club_row:
            hint = club_row["sport_type"]
            if club_row["typical_character"]:
                teaser = club_row["typical_character"].split(":")[0].split(",")[0]
                hint = f"{club_row['sport_type']} ({teaser})"
            outlook.append({
                "date": day_str, "weekday": day.weekday(),
                "sport_type": club_row["sport_type"], "hint": hint,
            })
            continue

        sport_type, session_hint = _typical_weekday_pattern(cursor, day.weekday())
        hint = (f"{sport_type} ({session_hint})" if session_hint else sport_type) if sport_type else None
        outlook.append({"date": day_str, "weekday": day.weekday(), "sport_type": sport_type, "hint": hint})

    conn.close()
    return outlook


def get_far_weeks_outlook(reference_date):
    """Ein Eintrag pro Woche ab Woche 4 (3 Wochen nach der Woche von reference_date) bis
    einschließlich der Woche des nächsten Rennens - je Woche week_id/iso_week, Start-/Enddatum und
    eine ehrlich berechnete Trainingsphase. Taper/Peak sind reine Datums-Schwellenwerte (siehe
    weekly_summary.py::_training_phase, TAPER_DAYS_THRESHOLD/PEAK_DAYS_THRESHOLD) und daher sicher
    auf zukünftige Wochen projizierbar; Build/Base benötigen echtes synchronisiertes
    Trainingsvolumen der jeweiligen Woche, das für die Zukunft nicht existiert - dort bleibt
    training_phase bewusst None statt geraten (Anti-Fabrikations-Prinzip, siehe Moduldocstring).
    Gibt [] zurück, falls kein Rennen ab Woche 4 bevorsteht - dann endet die Anzeige nach Woche 3."""
    _, week_start, _ = _week_bounds(reference_date)
    week4_start = week_start + timedelta(weeks=3)

    conn = get_connection()
    cursor = conn.cursor()
    race_row = cursor.execute(
        "SELECT event_date, title FROM garmin_scheduled_events WHERE is_race = 1 AND event_date >= ? "
        "ORDER BY event_date ASC LIMIT 1",
        (week4_start.isoformat(),)
    ).fetchone()
    conn.close()

    if not race_row:
        return []

    race_date = date.fromisoformat(race_row["event_date"])
    _, race_week_start, _ = _week_bounds(race_row["event_date"])

    weeks = []
    cursor_week_start = week4_start
    while cursor_week_start <= race_week_start:
        iso_year, iso_week, _ = cursor_week_start.isocalendar()
        week_end = cursor_week_start + timedelta(days=6)
        days_until_race = (race_date - cursor_week_start).days
        is_race_week = cursor_week_start == race_week_start

        if days_until_race <= TAPER_DAYS_THRESHOLD:
            training_phase = "Taper"
        elif days_until_race <= PEAK_DAYS_THRESHOLD:
            training_phase = "Peak"
        else:
            training_phase = None

        weeks.append({
            "week_id": f"{iso_year}-W{iso_week:02d}",
            "iso_week": iso_week,
            "week_start": cursor_week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "training_phase": training_phase,
            # Nur in der Woche des Rennens selbst gesetzt - dort darf der Balken den Wettkampf und
            # das genaue Datum explizit benennen statt nur KW/Datumsbereich zu zeigen.
            "race_title": race_row["title"] if is_race_week else None,
            "race_date": race_date.isoformat() if is_race_week else None,
        })
        cursor_week_start += timedelta(weeks=1)

    return weeks
