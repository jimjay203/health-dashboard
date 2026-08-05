import json
import streamlit as st
from datetime import date, datetime
from db import get_connection, init_db
from garmin_auth import get_garmin_client
from workout_builder import build_interval_running_workout, build_steady_running_workout, upload_workout

st.set_page_config(page_title="Workout Builder", page_icon="🏗️")
init_db()

st.title("🏗️ Workout Builder")
st.caption(
    "Baut ein strukturiertes Lauf-Workout und lädt es zu Garmin Connect hoch. "
    "Zonen-Ziele nutzen deine aktuellen Trainingszonen (training_zones_running), die immer auf "
    "der zuletzt gemessenen Schwellenpace basieren."
)

ZONE_ORDER = ["1", "2", "3", "4", "5a", "5b", "5c"]


def _available_zones():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT zone FROM training_zones_running").fetchall()
    conn.close()
    present = {r["zone"] for r in rows}
    return [z for z in ZONE_ORDER if z in present]


zones = _available_zones()
if not zones:
    st.warning(
        "Keine Trainingszonen gefunden (training_zones_running ist leer). "
        "Zuerst einen Sync für heute durchführen, um die Zonen zu berechnen."
    )
    st.stop()

# Vorbefüllung aus einem Wochenplaner-Entwurf (siehe weekly_planner.py) - Aufruf über
# "Workout anpassen" im React-Kalender-Widget verlinkt hierher mit ?draft_id=<id>. React (Port
# 8000) und Streamlit (Port 8501) sind getrennte Prozesse, st.session_state kann nicht zwischen
# ihnen geteilt werden - nur die gemeinsame SQLite-Datei, daher der Umweg über eine id im
# Query-Param statt direkter State-Übergabe.
draft_id = st.query_params.get("draft_id")
interval_prefill = None
steady_prefill = None
draft_row = None
if draft_id:
    conn = get_connection()
    draft_row = conn.execute(
        "SELECT * FROM weekly_plan_workout_draft WHERE id = ?", (draft_id,)
    ).fetchone()
    conn.close()
    if draft_row:
        params = json.loads(draft_row["builder_params_json"])
        if draft_row["builder_name"] == "build_interval_running_workout":
            interval_prefill = params
        else:
            steady_prefill = params
        st.info(f"Bearbeite Entwurf für {draft_row['date']} (Entwurf-id={draft_id}).")
    else:
        st.warning(f"Kein Workout-Entwurf mit id={draft_id} gefunden - Formular wird leer angezeigt.")

st.subheader("📋 Workout-Angaben")

workout_type = st.radio(
    "Workout-Typ", ["Intervall", "Durchgehend"], horizontal=True,
    index=1 if steady_prefill else 0,
)

if workout_type == "Intervall":
    name = st.text_input("Workout-Name", value=interval_prefill["name"] if interval_prefill else "Intervalltraining")

    col1, col2 = st.columns(2)
    with col1:
        warmup_minutes = st.number_input(
            "Einlaufen (Minuten)", min_value=1,
            value=int(interval_prefill["warmup_minutes"]) if interval_prefill else 10, step=1
        )
        warmup_zone_index = zones.index(interval_prefill["warmup_zone"]) \
            if interval_prefill and interval_prefill["warmup_zone"] in zones else 0
        warmup_zone = st.selectbox("Einlaufen-Zone", zones, index=warmup_zone_index, key="warmup_zone")
    with col2:
        cooldown_minutes = st.number_input(
            "Auslaufen (Minuten)", min_value=1,
            value=int(interval_prefill["cooldown_minutes"]) if interval_prefill else 10, step=1
        )
        cooldown_zone_index = zones.index(interval_prefill["cooldown_zone"]) \
            if interval_prefill and interval_prefill["cooldown_zone"] in zones else 0
        cooldown_zone = st.selectbox("Auslaufen-Zone", zones, index=cooldown_zone_index, key="cooldown_zone")

    st.markdown("**Intervalle**")
    interval_count = st.number_input(
        "Anzahl Intervalle", min_value=1,
        value=int(interval_prefill["interval_count"]) if interval_prefill else 6, step=1
    )

    int_col1, int_col2 = st.columns(2)
    with int_col1:
        interval_end_default = 1 if interval_prefill and interval_prefill.get("interval_duration_sec") is not None else 0
        interval_end_mode = st.radio(
            "Intervall-Ende", ["Distanz", "Dauer"], horizontal=True, index=interval_end_default,
            key="interval_end_mode"
        )
        if interval_end_mode == "Distanz":
            interval_distance_m = st.number_input(
                "Distanz pro Intervall (m)", min_value=1.0,
                value=float(interval_prefill["interval_distance_m"]) if interval_prefill and interval_prefill.get("interval_distance_m") else 1000.0,
                step=100.0
            )
            interval_duration_sec = None
        else:
            interval_duration_sec = st.number_input(
                "Dauer pro Intervall (Sek.)", min_value=1.0,
                value=float(interval_prefill["interval_duration_sec"]) if interval_prefill and interval_prefill.get("interval_duration_sec") else 240.0,
                step=10.0
            )
            interval_distance_m = None

    with int_col2:
        interval_target_default = 1 if interval_prefill and interval_prefill.get("interval_target_pace_min_per_km") is not None else 0
        interval_target_mode = st.radio(
            "Intervall-Ziel", ["Zone", "Exakte Pace"], horizontal=True, index=interval_target_default,
            key="interval_target_mode"
        )
        if interval_target_mode == "Zone":
            interval_target_zone_index = 3
            if interval_prefill and interval_prefill.get("interval_target_zone") in zones:
                interval_target_zone_index = zones.index(interval_prefill["interval_target_zone"])
            else:
                interval_target_zone_index = min(3, len(zones) - 1)
            interval_target_zone = st.selectbox(
                "Ziel-Zone", zones, index=interval_target_zone_index, key="interval_target_zone"
            )
            interval_target_pace_min_per_km = None
        else:
            interval_target_pace_min_per_km = st.number_input(
                "Ziel-Pace (min/km)", min_value=2.0,
                value=float(interval_prefill["interval_target_pace_min_per_km"]) if interval_prefill and interval_prefill.get("interval_target_pace_min_per_km") else 4.5,
                step=0.1, help="z.B. 4.5 = 4:30 min/km"
            )
            interval_target_zone = None

    recovery_default = 1 if interval_prefill and interval_prefill.get("recovery_distance_m") is not None else 0
    recovery_mode = st.radio("Erholung", ["Dauer", "Distanz"], horizontal=True, index=recovery_default, key="recovery_mode")
    if recovery_mode == "Dauer":
        recovery_duration_sec = st.number_input(
            "Erholungsdauer (Sek.)", min_value=1.0,
            value=float(interval_prefill["recovery_duration_sec"]) if interval_prefill and interval_prefill.get("recovery_duration_sec") else 90.0,
            step=10.0
        )
        recovery_distance_m = None
    else:
        recovery_distance_m = st.number_input(
            "Erholungsdistanz (m)", min_value=1.0,
            value=float(interval_prefill["recovery_distance_m"]) if interval_prefill and interval_prefill.get("recovery_distance_m") else 200.0,
            step=50.0
        )
        recovery_duration_sec = None

else:  # Durchgehend - lockerer Dauerlauf/langer Lauf ohne Intervall-Struktur
    steady_name = st.text_input(
        "Workout-Name", value=steady_prefill["name"] if steady_prefill else "Lockerer Dauerlauf"
    )

    steady_target_default = 1 if steady_prefill and steady_prefill.get("target_pace_min_per_km") is not None else 0
    steady_target_mode = st.radio(
        "Ziel", ["Zone", "Exakte Pace"], horizontal=True, index=steady_target_default, key="steady_target_mode"
    )
    if steady_target_mode == "Zone":
        steady_zone_index = 1 if len(zones) > 1 else 0
        if steady_prefill and steady_prefill.get("target_zone") in zones:
            steady_zone_index = zones.index(steady_prefill["target_zone"])
        steady_target_zone = st.selectbox("Ziel-Zone", zones, index=steady_zone_index, key="steady_target_zone")
        steady_target_pace_min_per_km = None
    else:
        steady_target_pace_min_per_km = st.number_input(
            "Ziel-Pace (min/km)", min_value=2.0,
            value=float(steady_prefill["target_pace_min_per_km"]) if steady_prefill and steady_prefill.get("target_pace_min_per_km") else 5.5,
            step=0.1, help="z.B. 5.5 = 5:30 min/km"
        )
        steady_target_zone = None

    steady_end_default = 1 if steady_prefill and steady_prefill.get("distance_m") is not None else 0
    steady_end_mode = st.radio("Ende", ["Dauer", "Distanz"], horizontal=True, index=steady_end_default, key="steady_end_mode")
    if steady_end_mode == "Dauer":
        steady_duration_minutes = st.number_input(
            "Dauer (Minuten)", min_value=1.0,
            value=float(steady_prefill["duration_minutes"]) if steady_prefill and steady_prefill.get("duration_minutes") else 45.0,
            step=5.0
        )
        steady_distance_m = None
    else:
        steady_distance_m = st.number_input(
            "Distanz (m)", min_value=100.0,
            value=float(steady_prefill["distance_m"]) if steady_prefill and steady_prefill.get("distance_m") else 10000.0,
            step=500.0
        )
        steady_duration_minutes = None

if st.button("Vorschau erstellen 🔍"):
    try:
        if workout_type == "Intervall":
            workout = build_interval_running_workout(
                name=name,
                warmup_minutes=warmup_minutes, warmup_zone=warmup_zone,
                interval_count=interval_count,
                interval_distance_m=interval_distance_m, interval_duration_sec=interval_duration_sec,
                interval_target_pace_min_per_km=interval_target_pace_min_per_km,
                interval_target_zone=interval_target_zone,
                recovery_duration_sec=recovery_duration_sec, recovery_distance_m=recovery_distance_m,
                cooldown_minutes=cooldown_minutes, cooldown_zone=cooldown_zone,
            )
        else:
            workout = build_steady_running_workout(
                name=steady_name,
                target_zone=steady_target_zone, target_pace_min_per_km=steady_target_pace_min_per_km,
                duration_minutes=steady_duration_minutes, distance_m=steady_distance_m,
            )
        st.session_state["draft_workout"] = workout
        st.success("Workout gebaut - Vorschau unten prüfen, dann ggf. hochladen.")
    except ValueError as e:
        st.error(str(e))
        st.session_state.pop("draft_workout", None)

if "draft_workout" in st.session_state:
    draft = st.session_state["draft_workout"]
    st.divider()
    st.subheader("👀 Vorschau")
    st.write(f"Geschätzte Gesamtdauer: **{draft.estimatedDurationInSecs / 60:.1f} Min.**")
    with st.expander("Vollständige Workout-Struktur (JSON)"):
        st.json(draft.to_dict())

    st.subheader("🚀 Hochladen")
    do_schedule = st.checkbox("Direkt in den Kalender einplanen")
    schedule_date = None
    if do_schedule:
        schedule_date = st.date_input("Datum", value=date.today())

    if st.button("Jetzt zu Garmin hochladen 🚀"):
        with st.spinner("Lade Workout zu Garmin Connect hoch..."):
            try:
                client = get_garmin_client()
                result = upload_workout(
                    st.session_state["draft_workout"], client,
                    schedule_date=schedule_date.isoformat() if schedule_date else None,
                )
                if result["success"]:
                    st.success(f"Workout hochgeladen! workout_id={result['workout_id']}")
                    if result["scheduled"]:
                        st.success(f"Eingeplant für {result['scheduled_date']}.")
                    if result["error"]:
                        st.warning(result["error"])
                    if draft_id and draft_row:
                        conn = get_connection()
                        conn.execute(
                            "UPDATE weekly_plan_workout_draft SET uploaded_at = ? WHERE id = ?",
                            (datetime.now().isoformat(), draft_id)
                        )
                        conn.commit()
                        conn.close()
                    del st.session_state["draft_workout"]
                else:
                    st.error(f"Upload fehlgeschlagen: {result['error']}")
            except Exception as e:
                st.error(f"Fehler beim Hochladen: {e}")
