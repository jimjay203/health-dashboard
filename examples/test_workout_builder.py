"""
Eigenständiges Testskript für workout_builder.py (kein UI, keine Streamlit-Seite). Baut das
Schwellentraining aus einer früheren Besprechung ("10 min Einlaufen Z1, 6x1000m @ Schwellenpace
mit 90s Trabpause, 10 min Auslaufen Z1") mit fest hinterlegten Werten, zeigt die gebaute
Workout-Struktur zur Kontrolle an und lädt NICHT automatisch hoch.

Ausführen vom Repo-Root aus (nicht direkt als examples/test_workout_builder.py - sonst findet
Python die Module im Root wie garmin_auth/workout_builder nicht):
    python3 -m examples.test_workout_builder

Zum echten Hochladen: den auskommentierten Block ganz unten aktivieren und erneut ausführen.
"""
import json
from garmin_auth import get_garmin_client
from workout_builder import build_interval_running_workout, upload_workout

workout = build_interval_running_workout(
    name="Schwellentraining 6x1000m",
    warmup_minutes=10, warmup_zone="1",
    interval_count=6,
    interval_distance_m=1000.0, interval_duration_sec=None,
    interval_target_pace_min_per_km=None, interval_target_zone="4",
    recovery_duration_sec=90.0, recovery_distance_m=None,
    cooldown_minutes=10, cooldown_zone="1",
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
