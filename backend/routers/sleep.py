"""
Backend-Endpoints für die "Schlaf"-Seite: letzte Nacht im Detail (garmin_sleep_phases +
garmin_daily.sleep_score/-hours + daily_summary.sleep_debt_cumulative) sowie ein 28-Tage-Trend,
der zusätzlich die Zutaten für die Regelmäßigkeits- und Korrelations-Charts im Frontend mitliefert
(Trainingslast/späte Einheit/RPE des VORABENDS, Habit-Tracker-Eintrag des Vorabends) - alle Werte
sind bereits vorhandene, real synchronisierte Daten, keine neuen Garmin-API-Aufrufe.

Datums-Konvention: eine Schlaf-Zeile mit date=D beschreibt die Nacht, die am Abend von D-1 beginnt
und am Morgen von D endet (Garmins eigene calendarDate-Konvention, ground-truth verifiziert). Für
die Korrelation werden deshalb bewusst Trainings-/Journal-/Habit-Daten von D-1 herangezogen, nicht
von D selbst.
"""
import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_connection
import habit_tracker
from sleep_insight import generate_correlations_insight, get_cached_correlations_insight
from sleep_trend_insight import generate_trend_insight, get_cached_trend_insight

router = APIRouter(prefix="/api/sleep", tags=["sleep"])

SLEEP_TREND_MAX_DAYS = 90


def _validate_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum muss im Format YYYY-MM-DD sein.")


def _mins_to_clock(mins):
    """recommended_bedtime_*_mins sind Minuten seit Mitternacht des Vortages, können >=1440 sein,
    wenn das Fenster über Mitternacht reicht (siehe db.py-Migrationskommentar)."""
    if mins is None:
        return None
    normalized = mins % 1440
    return f"{normalized // 60:02d}:{normalized % 60:02d}"


def _screen_time_gap_minutes(last_screen_time, sleep_start_local):
    """Minuten zwischen der im Habit-Tracker eingetragenen letzten Bildschirmnutzung (Vorabend,
    "HH:MM") und der tatsächlichen Bettzeit dieser Nacht - eine Uhrzeit ist leichter zu erinnern
    als eine geschätzte Minutenzahl (siehe HabitTrackerCard.tsx), die Dauer wird stattdessen hier
    berechnet. Negative Werte (Bildschirm nach der Bettzeit eingetragen) werden auf 0 gekappt statt
    ein verwirrendes Minuszeichen zu zeigen - kein Versuch, eine Bildschirmnutzung nach Mitternacht
    zu erkennen, das wäre ohne Datumsangabe im Eingabefeld nicht zuverlässig unterscheidbar."""
    if not last_screen_time or not sleep_start_local:
        return None
    try:
        screen_dt = datetime.strptime(f"{sleep_start_local[:10]} {last_screen_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    sleep_start_dt = datetime.fromisoformat(sleep_start_local)
    gap_minutes = (sleep_start_dt - screen_dt).total_seconds() / 60
    return max(0, round(gap_minutes))


# --- Letzte Nacht im Detail ---

class SleepOverviewResponse(BaseModel):
    date: str
    sleep_score: int | None = None
    sleep_hours: float | None = None
    sleep_start_local: str | None = None
    sleep_end_local: str | None = None
    deep_sleep_seconds: int | None = None
    light_sleep_seconds: int | None = None
    rem_sleep_seconds: int | None = None
    awake_sleep_seconds: int | None = None
    deep_pct: int | None = None
    light_pct: int | None = None
    rem_pct: int | None = None
    deep_qualifier: str | None = None
    light_qualifier: str | None = None
    rem_qualifier: str | None = None
    total_duration_qualifier: str | None = None
    stress_qualifier: str | None = None
    restlessness_qualifier: str | None = None
    awake_count: int | None = None
    awake_count_qualifier: str | None = None
    avg_sleep_stress: float | None = None
    avg_sleep_hr: float | None = None
    sleep_need_seconds: int | None = None
    sleep_need_baseline_seconds: int | None = None
    sleep_need_hrv_adjustment: str | None = None
    sleep_need_training_feedback: str | None = None
    recommended_bedtime_start: str | None = None
    recommended_bedtime_end: str | None = None
    restless_moments_count: int | None = None
    avg_overnight_hrv: float | None = None
    body_battery_change: int | None = None
    avg_skin_temp_deviation_c: float | None = None
    avg_sleep_spo2: float | None = None
    lowest_sleep_spo2: float | None = None
    avg_sleep_respiration: float | None = None
    sleep_score_feedback: str | None = None
    sleep_score_insight: str | None = None
    sleep_score_qualifier: str | None = None
    sleep_debt_cumulative: float | None = None
    sleep_vs_7d_avg_pct: float | None = None


@router.get("/overview/{date_str}", response_model=SleepOverviewResponse)
def get_sleep_overview(date_str: str) -> SleepOverviewResponse:
    _validate_date(date_str)
    conn = get_connection()
    phases = conn.execute("SELECT * FROM garmin_sleep_phases WHERE date = ?", (date_str,)).fetchone()
    daily = conn.execute("SELECT sleep_score, sleep_hours FROM garmin_daily WHERE date = ?", (date_str,)).fetchone()
    summary = conn.execute(
        "SELECT sleep_debt_cumulative, sleep_vs_7d_avg_pct FROM daily_summary WHERE date = ?", (date_str,)
    ).fetchone()
    conn.close()

    p = dict(phases) if phases else {}
    return SleepOverviewResponse(
        date=date_str,
        sleep_score=daily["sleep_score"] if daily else None,
        sleep_hours=daily["sleep_hours"] if daily else None,
        sleep_start_local=p.get("sleep_start_local"),
        sleep_end_local=p.get("sleep_end_local"),
        deep_sleep_seconds=p.get("deep_sleep_seconds"),
        light_sleep_seconds=p.get("light_sleep_seconds"),
        rem_sleep_seconds=p.get("rem_sleep_seconds"),
        awake_sleep_seconds=p.get("awake_sleep_seconds"),
        deep_pct=p.get("deep_pct"),
        light_pct=p.get("light_pct"),
        rem_pct=p.get("rem_pct"),
        deep_qualifier=p.get("deep_qualifier"),
        light_qualifier=p.get("light_qualifier"),
        rem_qualifier=p.get("rem_qualifier"),
        total_duration_qualifier=p.get("total_duration_qualifier"),
        stress_qualifier=p.get("stress_qualifier"),
        restlessness_qualifier=p.get("restlessness_qualifier"),
        awake_count=p.get("awake_count"),
        awake_count_qualifier=p.get("awake_count_qualifier"),
        avg_sleep_stress=p.get("avg_sleep_stress"),
        avg_sleep_hr=p.get("avg_sleep_hr"),
        sleep_need_seconds=p.get("sleep_need_seconds"),
        sleep_need_baseline_seconds=p.get("sleep_need_baseline_seconds"),
        sleep_need_hrv_adjustment=p.get("sleep_need_hrv_adjustment"),
        sleep_need_training_feedback=p.get("sleep_need_training_feedback"),
        recommended_bedtime_start=_mins_to_clock(p.get("recommended_bedtime_start_mins")),
        recommended_bedtime_end=_mins_to_clock(p.get("recommended_bedtime_end_mins")),
        restless_moments_count=p.get("restless_moments_count"),
        avg_overnight_hrv=p.get("avg_overnight_hrv"),
        body_battery_change=p.get("body_battery_change"),
        avg_skin_temp_deviation_c=p.get("avg_skin_temp_deviation_c"),
        avg_sleep_spo2=p.get("avg_sleep_spo2"),
        lowest_sleep_spo2=p.get("lowest_sleep_spo2"),
        avg_sleep_respiration=p.get("avg_sleep_respiration"),
        sleep_score_feedback=p.get("sleep_score_feedback"),
        sleep_score_insight=p.get("sleep_score_insight"),
        sleep_score_qualifier=p.get("sleep_score_qualifier"),
        sleep_debt_cumulative=summary["sleep_debt_cumulative"] if summary else None,
        sleep_vs_7d_avg_pct=summary["sleep_vs_7d_avg_pct"] if summary else None,
    )


# --- Minuten-genauer Phasenverlauf ("Letzte Nacht"-Diagramm, Apple-Health-Vorbild) ---

# Ground-truth aus garmin_api_exploration/get_sleep_data.json: activityLevel ist ein Float-Code
# (0.0/1.0/2.0/3.0), keine eigene Tabelle nötig - sleepLevels kommt bereits mit derselben
# get_sleep_data()-Antwort wie garmin_sleep_phases mit und steckt unverändert in
# garmin_daily.raw_json (siehe garmin_service.py: json.dumps({"stats":..., "sleep": sleep_data,
# "hrv":...})) - hier nur bei Bedarf pro Anfrage neu geparst statt dauerhaft in einer eigenen
# Tabelle gespeichert (Minuten-Zeitreihe nur für die Grafik der jeweils abgefragten Nacht relevant).
SLEEP_STAGE_KEYS = {0: "deep", 1: "light", 2: "rem", 3: "awake"}


class SleepLevelSegment(BaseModel):
    start_local: str
    end_local: str
    stage: str  # deep | light | rem | awake


class SleepLevelsResponse(BaseModel):
    date: str
    segments: list[SleepLevelSegment] = []


@router.get("/levels/{date_str}", response_model=SleepLevelsResponse)
def get_sleep_levels(date_str: str) -> SleepLevelsResponse:
    _validate_date(date_str)
    conn = get_connection()
    row = conn.execute("SELECT raw_json FROM garmin_daily WHERE date = ?", (date_str,)).fetchone()
    conn.close()
    if not row or not row["raw_json"]:
        return SleepLevelsResponse(date=date_str)

    try:
        blob = json.loads(row["raw_json"])
    except json.JSONDecodeError:
        return SleepLevelsResponse(date=date_str)

    sleep_blob = blob.get("sleep") or {}
    sleep_levels = sleep_blob.get("sleepLevels") or []
    dto = sleep_blob.get("dailySleepDTO") or {}
    # startGMT/endGMT sind naive ISO-Strings ohne Zeitzone, faktisch in GMT - derselbe
    # Millisekunden-Offset wie bei garmin_service.py::_epoch_ms_local_to_iso verschiebt sie auf
    # lokale Wanduhrzeit (ground-truth: sleepStartTimestampLocal - sleepStartTimestampGMT).
    gmt_start = dto.get("sleepStartTimestampGMT")
    local_start = dto.get("sleepStartTimestampLocal")
    offset = timedelta(milliseconds=(local_start - gmt_start)) if gmt_start is not None and local_start is not None else timedelta(0)

    segments = []
    for lvl in sleep_levels:
        level = lvl.get("activityLevel")
        stage = SLEEP_STAGE_KEYS.get(int(level)) if level is not None else None
        start_gmt, end_gmt = lvl.get("startGMT"), lvl.get("endGMT")
        if stage is None or not start_gmt or not end_gmt:
            continue
        segments.append(SleepLevelSegment(
            start_local=(datetime.fromisoformat(start_gmt) + offset).isoformat(),
            end_local=(datetime.fromisoformat(end_gmt) + offset).isoformat(),
            stage=stage,
        ))

    return SleepLevelsResponse(date=date_str, segments=segments)


# --- 28-Tage-Trend inkl. Korrelations-Zutaten ---

# Kein wissenschaftlich hergeleiteter Wert, sondern eine plausible, transparent offengelegte
# Annahme ("Training ab 18 Uhr zählt als spät") - analog zu CYCLING_FLAT_ELEVATION_GAIN_PER_KM in
# performance.py. Frontend beschriftet den Wert entsprechend, keine versteckte Kennzahl.
LATE_WORKOUT_HOUR_THRESHOLD = 18


class SleepTrendPoint(BaseModel):
    date: str
    sleep_hours: float | None = None
    sleep_score: int | None = None
    deep_pct: int | None = None
    light_pct: int | None = None
    rem_pct: int | None = None
    sleep_start_local: str | None = None
    sleep_end_local: str | None = None
    sleep_need_seconds: int | None = None
    sleep_debt_cumulative: float | None = None
    avg_overnight_hrv: float | None = None
    # Korrelations-Inputs - beschreiben den VORABEND dieser Nacht (siehe Moduldocstring).
    prev_day_training_load: float | None = None
    prev_day_late_workout: bool = False
    prev_day_rpe: int | None = None
    prev_day_caffeine_after_noon: bool | None = None
    # Abgeleitet aus habit_tracker.last_screen_time (Vorabend) + sleep_start_local dieser Nacht,
    # siehe _screen_time_gap_minutes.
    prev_day_screen_time_gap_minutes: int | None = None


class SleepTrendResponse(BaseModel):
    late_workout_hour_threshold: int = LATE_WORKOUT_HOUR_THRESHOLD
    points: list[SleepTrendPoint] = []


@router.get("/trend", response_model=SleepTrendResponse)
def get_sleep_trend(days: int = 28) -> SleepTrendResponse:
    days = min(days, SLEEP_TREND_MAX_DAYS)
    end = date.today()
    start = end - timedelta(days=days - 1)

    conn = get_connection()
    sleep_rows = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT date, sleep_start_local, sleep_end_local, sleep_need_seconds, avg_overnight_hrv, "
            "deep_pct, light_pct, rem_pct FROM garmin_sleep_phases WHERE date >= ? AND date <= ?",
            (start.isoformat(), end.isoformat())
        ).fetchall()
    }
    daily_rows = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT date, sleep_score, sleep_hours FROM garmin_daily WHERE date >= ? AND date <= ?",
            (start.isoformat(), end.isoformat())
        ).fetchall()
    }
    summary_rows = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT date, sleep_debt_cumulative FROM daily_summary WHERE date >= ? AND date <= ?",
            (start.isoformat(), end.isoformat())
        ).fetchall()
    }
    journal_rows = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT date, rpe_score FROM daily_journal WHERE date >= ? AND date <= ?",
            ((start - timedelta(days=1)).isoformat(), end.isoformat())
        ).fetchall()
    }
    activity_rows = conn.execute(
        "SELECT date(start_time_local) AS date, start_time_local, activity_training_load "
        "FROM garmin_activities WHERE date(start_time_local) >= ? AND date(start_time_local) <= ?",
        ((start - timedelta(days=1)).isoformat(), end.isoformat())
    ).fetchall()
    conn.close()

    activities_by_date: dict[str, list] = {}
    for r in activity_rows:
        activities_by_date.setdefault(r["date"], []).append(r)

    habit_rows = {
        h["date"]: h for h in habit_tracker.list_habit_entries((start - timedelta(days=1)).isoformat(), end.isoformat())
    }

    points = []
    d = start
    while d <= end:
        date_str = d.isoformat()
        prev_date_str = (d - timedelta(days=1)).isoformat()
        s = sleep_rows.get(date_str, {})
        daily = daily_rows.get(date_str, {})
        summary = summary_rows.get(date_str, {})
        prev_journal = journal_rows.get(prev_date_str, {})
        prev_habits = habit_rows.get(prev_date_str, {})
        prev_activities = activities_by_date.get(prev_date_str, [])

        training_load_sum = None
        late_workout = False
        if prev_activities:
            loads = [a["activity_training_load"] for a in prev_activities if a["activity_training_load"] is not None]
            training_load_sum = sum(loads) if loads else None
            for a in prev_activities:
                start_time = a["start_time_local"]
                if start_time and int(start_time[11:13]) >= LATE_WORKOUT_HOUR_THRESHOLD:
                    late_workout = True

        points.append(SleepTrendPoint(
            date=date_str,
            sleep_hours=daily.get("sleep_hours"),
            sleep_score=daily.get("sleep_score"),
            deep_pct=s.get("deep_pct"),
            light_pct=s.get("light_pct"),
            rem_pct=s.get("rem_pct"),
            sleep_start_local=s.get("sleep_start_local"),
            sleep_end_local=s.get("sleep_end_local"),
            sleep_need_seconds=s.get("sleep_need_seconds"),
            sleep_debt_cumulative=summary.get("sleep_debt_cumulative"),
            avg_overnight_hrv=s.get("avg_overnight_hrv"),
            prev_day_training_load=training_load_sum,
            prev_day_late_workout=late_workout,
            prev_day_rpe=prev_journal.get("rpe_score"),
            prev_day_caffeine_after_noon=(
                bool(prev_habits["caffeine_after_noon"]) if prev_habits.get("caffeine_after_noon") is not None else None
            ),
            prev_day_screen_time_gap_minutes=_screen_time_gap_minutes(
                prev_habits.get("last_screen_time"), s.get("sleep_start_local")
            ),
        ))
        d += timedelta(days=1)

    return SleepTrendResponse(points=points)


# --- Gemini-Einordnung der Korrelationen (siehe sleep_insight.py) ---

class CorrelationsInsightResponse(BaseModel):
    date: str
    insight_text: str | None = None
    generated_at: str | None = None


@router.get("/correlations-insight", response_model=CorrelationsInsightResponse)
def get_correlations_insight() -> CorrelationsInsightResponse:
    """Reines Cache-Lesen, KEIN automatisches Generieren mehr (Nutzer-Vorgabe vom 2026-08-08 -
    KI-Texte sollen nur noch explizit per "Neu generieren"-Button entstehen). Leere Response
    (insight_text=None), falls für heute noch nichts generiert wurde."""
    today = date.today().isoformat()
    cached = get_cached_correlations_insight(today)
    if cached:
        return CorrelationsInsightResponse(**cached)
    return CorrelationsInsightResponse(date=today)


@router.post("/correlations-insight/regenerate", response_model=CorrelationsInsightResponse)
def regenerate_correlations_insight() -> CorrelationsInsightResponse:
    """Erzwingt eine Neu-Generierung unabhängig vom Tages-Cache, gleiches Muster wie
    backend/routers/weekly_plan.py::regenerate_weekly_plan."""
    today = date.today().isoformat()
    try:
        points = get_sleep_trend(days=28).points
        fresh = generate_correlations_insight(today, points)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Einordnung konnte nicht generiert werden: {e}")
    return CorrelationsInsightResponse(**fresh)


# --- Gemini-Einordnung des 28-Tage-Trends (siehe sleep_trend_insight.py) ---

class TrendInsightResponse(BaseModel):
    date: str
    insight_text: str | None = None
    generated_at: str | None = None


@router.get("/trend-insight", response_model=TrendInsightResponse)
def get_trend_insight() -> TrendInsightResponse:
    """Reines Cache-Lesen, kein automatisches Generieren mehr - siehe get_correlations_insight."""
    today = date.today().isoformat()
    cached = get_cached_trend_insight(today)
    if cached:
        return TrendInsightResponse(**cached)
    return TrendInsightResponse(date=today)


@router.post("/trend-insight/regenerate", response_model=TrendInsightResponse)
def regenerate_trend_insight() -> TrendInsightResponse:
    """Erzwingt eine Neu-Generierung unabhängig vom Tages-Cache, gleiches Muster wie
    backend/routers/weekly_plan.py::regenerate_weekly_plan."""
    today = date.today().isoformat()
    try:
        points = get_sleep_trend(days=28).points
        fresh = generate_trend_insight(today, points)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Einordnung konnte nicht generiert werden: {e}")
    return TrendInsightResponse(**fresh)
