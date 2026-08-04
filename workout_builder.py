"""
Erstellung strukturierter Garmin-Workouts (Warmup/Intervalle/Erholung/Cooldown mit Pace-/
Zonen-Zielen). Reine Python-Logik, kein Streamlit-Import (Portabilitäts-Prinzip, analog zu
daily_summary.py/insight_memory.py). Vorstufe für eine spätere Chat-gesteuerte
Freitext-Übersetzungsschicht (nicht Teil dieses Moduls) - hier ausschließlich parametrisierte
Funktionen, kein Freitext-Parsing.

Ground-Truth-Hinweis: garminconnect==0.3.2s ConditionType.DISTANCE ist FALSCH (=1, tatsächlich
"lap.button" laut Garmins Server) - live gegen den echten Server verifiziert (Test-Workout
hochgeladen, zurückgelesen, wieder gelöscht). Die echte Distanz-Endbedingung ist ID 3. TIME=2 und
ITERATIONS=7 aus dem Paket sind dagegen korrekt und werden übernommen.

Zweiter Ground-Truth-Fund (Nutzer hat ein hochgeladenes Workout in der Garmin-App manuell von
km/h auf Pace-Anzeige umgestellt, danach zurückgelesen): TargetType.OPEN=6 im Paket ist ebenfalls
FALSCH/irreführend - ID 6 ist tatsächlich "pace.zone" (eigener Zieltyp, getrennt von "speed.zone"
ID 5, nötig damit Garmin das Ziel als Pace statt km/h anzeigt). Beide Typen transportieren den
Wert weiterhin in m/s, aber mit VERTAUSCHTER targetValueOne/Two-Reihenfolge: bei speed.zone ist
One die langsamere (kleinere m/s), Two die schnellere Grenze; bei pace.zone ist es umgekehrt - One
die schnellere (kleinere Pace-Zahl), Two die langsamere Grenze.
"""
from garminconnect.workout import (
    RunningWorkout,
    WorkoutSegment,
    ExecutableStep,
    StepType,
    create_warmup_step,
    create_cooldown_step,
    create_repeat_group,
)
from db import get_connection

# Siehe Docstring oben - abweichend von garminconnect.workout.ConditionType, das für
# DISTANCE fälschlich 1 angibt (tatsächlich "lap.button").
TIME_CONDITION_ID = 2
DISTANCE_CONDITION_ID = 3

# Siehe Docstring oben - abweichend von garminconnect.workout.TargetType.OPEN, das fälschlich
# ebenfalls 6 angibt (tatsächlich "pace.zone", kein "offenes" Ziel).
PACE_TARGET_TYPE_ID = 6

PACE_TARGET_TOLERANCE_SEC_PER_KM = 3.0  # schmale Ziel-Spanne um einen exakten Pace-Wert
OPEN_ZONE_END_FALLBACK_FACTOR = 1.5  # Fallback für offene Zonenenden (siehe _zone_pace_bounds_m_s)


def _normalize_zone_label(zone_label):
    """'Z1'/'z1'/'1' -> '1', '5A' -> '5a' - training_zones_running.zone speichert ohne 'Z'-Präfix."""
    label = zone_label.strip()
    if label[:1] in ("Z", "z"):
        label = label[1:]
    return label.lower()


def _zone_pace_bounds_m_s(zone_label):
    """Liest den neuesten training_zones_running-Snapshot für zone_label und rechnet
    pace_min/max_sec_per_km in eine (min_m_s, max_m_s)-Geschwindigkeitsspanne um. pace_min_sec_per_km
    ist per Konvention die schnellere (kleinere) Sekundenzahl, pace_max_sec_per_km die langsamere
    (größere) - siehe training_zones.py. Offene Zonenenden (NULL an Zone 1 langsam / 5c schnell)
    werden über OPEN_ZONE_END_FALLBACK_FACTOR auf einen plausiblen endlichen Wert abgebildet, da
    Garmin für ein speed.zone-Ziel immer zwei endliche Werte erwartet."""
    label = _normalize_zone_label(zone_label)
    conn = get_connection()
    row = conn.execute(
        "SELECT pace_min_sec_per_km, pace_max_sec_per_km FROM training_zones_running "
        "WHERE zone = ? ORDER BY date DESC LIMIT 1",
        (label,)
    ).fetchone()
    conn.close()

    if not row:
        raise ValueError(
            f"Zone '{zone_label}' nicht in training_zones_running gefunden. "
            "Verfügbare Zonen prüfen (recompute_zones() muss mindestens einmal gelaufen sein)."
        )

    pace_min, pace_max = row["pace_min_sec_per_km"], row["pace_max_sec_per_km"]
    if pace_min is None and pace_max is None:
        raise ValueError(
            f"Zone '{zone_label}' hat keine Pace-Grenzen (fehlende Schwellenpace?). "
            "Kann kein Pace-Ziel daraus ableiten."
        )
    if pace_max is None:
        pace_max = pace_min * OPEN_ZONE_END_FALLBACK_FACTOR
    if pace_min is None:
        pace_min = pace_max / OPEN_ZONE_END_FALLBACK_FACTOR

    # Rückgabe-Reihenfolge (faster, slower) passend zu pace.zone-Konvention (targetValueOne =
    # schnellere/kleinere Pace-Zahl, targetValueTwo = langsamere) - siehe Docstring oben.
    speed_faster_m_s = 1000.0 / pace_min  # schnellere Pace (kleinere Sek./km) -> größere Geschwindigkeit
    speed_slower_m_s = 1000.0 / pace_max  # langsamere Pace (größere Sek./km) -> kleinere Geschwindigkeit
    return speed_faster_m_s, speed_slower_m_s


def _zone_range_pace_bounds_m_s(zone_labels):
    """Wie _zone_pace_bounds_m_s(), aber für ein Ziel, das mehrere benachbarte Zonen überspannt
    (z.B. "5b bis 5c") - nimmt die schnellste Grenze und die langsamste Grenze über alle
    übergebenen Zonen zusammen, offene Enden werden erst nach dem Zusammenführen über
    OPEN_ZONE_END_FALLBACK_FACTOR aufgelöst (nicht pro Einzelzone)."""
    conn = get_connection()
    pace_mins, pace_maxs = [], []
    for zone_label in zone_labels:
        label = _normalize_zone_label(zone_label)
        row = conn.execute(
            "SELECT pace_min_sec_per_km, pace_max_sec_per_km FROM training_zones_running "
            "WHERE zone = ? ORDER BY date DESC LIMIT 1",
            (label,)
        ).fetchone()
        if not row:
            conn.close()
            raise ValueError(
                f"Zone '{zone_label}' nicht in training_zones_running gefunden. "
                "Verfügbare Zonen prüfen (recompute_zones() muss mindestens einmal gelaufen sein)."
            )
        pace_mins.append(row["pace_min_sec_per_km"])
        pace_maxs.append(row["pace_max_sec_per_km"])
    conn.close()

    # Ein offenes Ende (None) in IRGENDEINER der zusammengefassten Zonen macht auch das Ende der
    # Gesamtspanne offen - z.B. darf die schnelle Grenze von "5b bis 5c" nicht stillschweigend auf
    # 5bs eigene (definierte) Grenze zurückfallen, nur weil 5c selbst keine feste Obergrenze hat.
    pace_min_overall = None if any(v is None for v in pace_mins) else min(pace_mins)
    pace_max_overall = None if any(v is None for v in pace_maxs) else max(pace_maxs)

    if pace_min_overall is None and pace_max_overall is None:
        raise ValueError(f"Keine Pace-Grenzen für Zonen {zone_labels} gefunden.")
    if pace_max_overall is None:
        pace_max_overall = pace_min_overall * OPEN_ZONE_END_FALLBACK_FACTOR
    if pace_min_overall is None:
        pace_min_overall = pace_max_overall / OPEN_ZONE_END_FALLBACK_FACTOR

    return 1000.0 / pace_min_overall, 1000.0 / pace_max_overall  # (faster, slower) - pace.zone-Reihenfolge


def _pace_value_to_speed_bounds(pace_min_per_km):
    """Einzelner Pace-Wert (min/km) -> schmale (faster_m_s, slower_m_s)-Spanne ± Toleranz (Garmin
    erwartet immer eine Spanne, keinen Einzelwert), in pace.zone-Reihenfolge (siehe oben)."""
    pace_sec_per_km = pace_min_per_km * 60.0
    slower_sec_per_km = pace_sec_per_km + PACE_TARGET_TOLERANCE_SEC_PER_KM
    faster_sec_per_km = pace_sec_per_km - PACE_TARGET_TOLERANCE_SEC_PER_KM
    return 1000.0 / faster_sec_per_km, 1000.0 / slower_sec_per_km


def _pace_target_type():
    return {
        "workoutTargetTypeId": PACE_TARGET_TYPE_ID,
        "workoutTargetTypeKey": "pace.zone",
        "displayOrder": 6,
    }


def _no_target_type():
    return {
        "workoutTargetTypeId": 1,  # TargetType.NO_TARGET aus dem Paket - live verifiziert korrekt
        "workoutTargetTypeKey": "no.target",
        "displayOrder": 1,
    }


def _build_step(step_order, step_type_id, step_type_key, step_display_order,
                 condition_id, condition_key, condition_display_order,
                 end_condition_value, target_type, target_value_bounds=None, description=None):
    """Generischer Baustein für ExecutableStep inkl. Zielwert-Feldern - die Paket-Helfer
    (create_interval_step etc.) unterstützen weder Zielwerte noch Distanz-Endbedingungen.
    target_value_bounds wird 1:1 als (targetValueOne, targetValueTwo) übernommen - Reihenfolge
    liegt beim Aufrufer (abhängig vom Zieltyp, siehe _zone_pace_bounds_m_s())."""
    step = ExecutableStep(
        stepOrder=step_order,
        stepType={
            "stepTypeId": step_type_id,
            "stepTypeKey": step_type_key,
            "displayOrder": step_display_order,
        },
        endCondition={
            "conditionTypeId": condition_id,
            "conditionTypeKey": condition_key,
            "displayOrder": condition_display_order,
            "displayable": True,
        },
        endConditionValue=float(end_condition_value),
        targetType=target_type,
    )
    if target_value_bounds is not None:
        step.targetValueOne, step.targetValueTwo = target_value_bounds
    if description is not None:
        step.description = description
    return step


def _require_exactly_one(name_a, value_a, name_b, value_b):
    if (value_a is None) == (value_b is None):
        raise ValueError(
            f"Genau eines von '{name_a}' oder '{name_b}' muss angegeben werden, nicht beide und nicht keines."
        )


def build_interval_running_workout(
    name,
    warmup_minutes, warmup_zone,
    interval_count,
    interval_distance_m, interval_duration_sec,
    interval_target_pace_min_per_km, interval_target_zone,
    recovery_duration_sec, recovery_distance_m,
    cooldown_minutes, cooldown_zone,
):
    """Baut ein strukturiertes Intervall-Lauf-Workout (Warmup, N x Intervall+Erholung, Cooldown)
    als RunningWorkout-Objekt - lädt NICHT hoch, siehe upload_workout(). Zonen-Ziele nutzen
    ausschließlich Pace (über training_zones_running), keine Garmin-HF-Zonennummer - dadurch ist
    keine Umrechnung vom 7-Zonen-Friel-Modell auf Garmins 5-Zonen-HF-Modell nötig."""
    if interval_count < 1:
        raise ValueError(f"interval_count muss mindestens 1 sein, war {interval_count}.")
    if warmup_minutes <= 0:
        raise ValueError(f"warmup_minutes muss größer als 0 sein, war {warmup_minutes}.")
    if cooldown_minutes <= 0:
        raise ValueError(f"cooldown_minutes muss größer als 0 sein, war {cooldown_minutes}.")

    _require_exactly_one("interval_distance_m", interval_distance_m,
                          "interval_duration_sec", interval_duration_sec)
    _require_exactly_one("interval_target_pace_min_per_km", interval_target_pace_min_per_km,
                          "interval_target_zone", interval_target_zone)
    _require_exactly_one("recovery_duration_sec", recovery_duration_sec,
                          "recovery_distance_m", recovery_distance_m)

    warmup_pace_bounds = _zone_pace_bounds_m_s(warmup_zone)
    cooldown_pace_bounds = _zone_pace_bounds_m_s(cooldown_zone)
    if interval_target_zone is not None:
        interval_pace_bounds = _zone_pace_bounds_m_s(interval_target_zone)
    else:
        interval_pace_bounds = _pace_value_to_speed_bounds(interval_target_pace_min_per_km)

    warmup_step = create_warmup_step(warmup_minutes * 60.0, step_order=1)
    warmup_step.targetType = _pace_target_type()
    warmup_step.targetValueOne, warmup_step.targetValueTwo = warmup_pace_bounds

    if interval_distance_m is not None:
        interval_step = _build_step(
            1, StepType.INTERVAL, "interval", 3,
            DISTANCE_CONDITION_ID, "distance", 3,
            interval_distance_m, _pace_target_type(), interval_pace_bounds,
        )
        avg_interval_speed_m_s = sum(interval_pace_bounds) / 2
        estimated_interval_sec = interval_distance_m / avg_interval_speed_m_s
    else:
        interval_step = _build_step(
            1, StepType.INTERVAL, "interval", 3,
            TIME_CONDITION_ID, "time", 2,
            interval_duration_sec, _pace_target_type(), interval_pace_bounds,
        )
        estimated_interval_sec = interval_duration_sec

    if recovery_distance_m is not None:
        recovery_step = _build_step(
            2, StepType.RECOVERY, "recovery", 4,
            DISTANCE_CONDITION_ID, "distance", 3,
            recovery_distance_m, _no_target_type(),
        )
        # Grobe Schätzung für estimatedDurationInSecs - nur Anzeigezweck, kein Garmin-Zielwert.
        # min(): unabhängig von der targetValueOne/Two-Reihenfolge immer die langsamere Grenze.
        estimated_recovery_sec = recovery_distance_m / (min(interval_pace_bounds) * 0.6)
    else:
        recovery_step = _build_step(
            2, StepType.RECOVERY, "recovery", 4,
            TIME_CONDITION_ID, "time", 2,
            recovery_duration_sec, _no_target_type(),
        )
        estimated_recovery_sec = recovery_duration_sec

    repeat_group = create_repeat_group(
        iterations=interval_count,
        workout_steps=[interval_step, recovery_step],
        step_order=2,
    )

    cooldown_step = create_cooldown_step(cooldown_minutes * 60.0, step_order=3)
    cooldown_step.targetType = _pace_target_type()
    cooldown_step.targetValueOne, cooldown_step.targetValueTwo = cooldown_pace_bounds

    estimated_total_sec = (
        warmup_minutes * 60
        + interval_count * (estimated_interval_sec + estimated_recovery_sec)
        + cooldown_minutes * 60
    )

    return RunningWorkout(
        workoutName=name,
        estimatedDurationInSecs=round(estimated_total_sec),
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType={"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
                workoutSteps=[warmup_step, repeat_group, cooldown_step],
            )
        ],
    )


def upload_workout(workout, client, schedule_date=None):
    """Lädt ein zuvor mit build_*() erstelltes Workout zu Garmin hoch und plant es optional ein.
    Kein automatischer Aufruf durch build_*() - bewusst getrennt."""
    result = {
        "workout_id": None, "success": False, "error": None,
        "scheduled": False, "scheduled_date": None,
    }
    try:
        response = client.upload_running_workout(workout)
    except Exception as e:
        result["error"] = str(e)
        return result

    workout_id = response.get("workoutId")
    result["workout_id"] = workout_id
    result["success"] = workout_id is not None

    if schedule_date and workout_id is not None:
        try:
            client.schedule_workout(workout_id, schedule_date)
            result["scheduled"] = True
            result["scheduled_date"] = schedule_date
        except Exception as e:
            result["error"] = f"Upload erfolgreich, aber Einplanen fehlgeschlagen: {e}"

    return result
