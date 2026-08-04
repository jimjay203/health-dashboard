"""
Eigenständiges Testskript (kein UI) für ein komplexeres, mehrsegmentiges Workout, das nicht in
die generische build_interval_running_workout()-Signatur passt (mehrere aufeinanderfolgende
Tempo-/Erholungsblöcke vor einer Wiederholungsgruppe, plus ein Zonen-Range-Ziel "5b bis 5c").
Baut direkt mit den Low-Level-Bausteinen aus workout_builder.py, analog zur Vorlage
"8km / 4km Tempo + 3x 1km VO2max" - Pace-Werte kommen bewusst NICHT aus der Vorlage, sondern
werden live aus den aktuellen Trainingszonen (training_zones_running) berechnet.

Trabpause (Erholung zwischen den VO2max-Intervallen) hat in der Vorlage keine explizite Zonen-
Angabe (anders als alle anderen Blöcke) - deshalb hier ohne Zielwert (NO_TARGET), nicht geraten.

Zeigt die gebaute Struktur, lädt NICHT automatisch hoch - der Upload-Block steht auskommentiert
am Ende.

Ausführen vom Repo-Root aus (nicht direkt als examples/test_workout_marathon_tempo.py - sonst
findet Python die Module im Root wie garmin_auth/workout_builder nicht):
    python3 -m examples.test_workout_marathon_tempo
"""
import json
from garmin_auth import get_garmin_client
from garminconnect.workout import RunningWorkout, WorkoutSegment, StepType, create_repeat_group
from workout_builder import (
    _build_step,
    _zone_pace_bounds_m_s,
    _zone_range_pace_bounds_m_s,
    _pace_target_type,
    _no_target_type,
    TIME_CONDITION_ID,
    DISTANCE_CONDITION_ID,
    upload_workout,
)

zone1 = _zone_pace_bounds_m_s("1")
zone3 = _zone_pace_bounds_m_s("3")
zone5b_5c = _zone_range_pace_bounds_m_s(["5b", "5c"])


def _distance_step(step_order, distance_m, pace_bounds, description):
    return _build_step(
        step_order, StepType.INTERVAL, "interval", 3,
        DISTANCE_CONDITION_ID, "distance", 3,
        distance_m, _pace_target_type(), pace_bounds, description=description,
    )


steps = [
    _build_step(1, StepType.WARMUP, "warmup", 1, DISTANCE_CONDITION_ID, "distance", 3,
                2000.0, _pace_target_type(), zone1, description="Einlaufen"),
    _distance_step(2, 8000.0, zone3, "Marathon-Pace"),
    _distance_step(3, 1000.0, zone1, "DL FatMax"),
    _distance_step(4, 4000.0, zone3, "Marathon-Pace"),
    _distance_step(5, 1000.0, zone1, "DL FatMax"),
]

vo2max_step = _distance_step(1, 1000.0, zone5b_5c, "VO2max")
recovery_step = _build_step(2, StepType.RECOVERY, "recovery", 4, TIME_CONDITION_ID, "time", 2,
                             180.0, _no_target_type(), description="Trabpause")
repeat_group = create_repeat_group(iterations=3, workout_steps=[vo2max_step, recovery_step], step_order=6)
steps.append(repeat_group)

steps.append(
    _build_step(7, StepType.COOLDOWN, "cooldown", 2, DISTANCE_CONDITION_ID, "distance", 3,
                2000.0, _pace_target_type(), zone1, description="Auslaufen")
)

# Grobe Gesamtdauer-Schätzung (nur Anzeigezweck, kein Garmin-Zielwert).
def _avg_speed(bounds):
    return sum(bounds) / 2


estimated_sec = (
    2000.0 / _avg_speed(zone1)
    + 8000.0 / _avg_speed(zone3)
    + 1000.0 / _avg_speed(zone1)
    + 4000.0 / _avg_speed(zone3)
    + 1000.0 / _avg_speed(zone1)
    + 3 * (1000.0 / _avg_speed(zone5b_5c) + 180.0)
    + 2000.0 / _avg_speed(zone1)
)

workout = RunningWorkout(
    workoutName="8km / 4km Tempo + 3x 1km VO2max",
    estimatedDurationInSecs=round(estimated_sec),
    workoutSegments=[
        WorkoutSegment(
            segmentOrder=1,
            sportType={"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
            workoutSteps=steps,
        )
    ],
)

print("=== Gebaute Workout-Struktur (noch NICHT hochgeladen) ===")
print(json.dumps(workout.to_dict(), indent=2))
print()
print(f"Geschätzte Gesamtdauer: {workout.estimatedDurationInSecs} Sek. "
      f"({workout.estimatedDurationInSecs / 60:.1f} Min.)")

# --- Echter Upload erst nach manueller Prüfung der obigen Ausgabe ---
# Zum Hochladen die folgenden Zeilen einkommentieren und das Skript erneut ausführen:
#
# client = get_garmin_client()
# result = upload_workout(workout, client)
# print()
# print("=== Upload-Ergebnis ===")
# print(result)
