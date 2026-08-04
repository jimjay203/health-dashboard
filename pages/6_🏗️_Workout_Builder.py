import streamlit as st
from datetime import date
from db import get_connection, init_db
from garmin_auth import get_garmin_client
from workout_builder import build_interval_running_workout, upload_workout

st.set_page_config(page_title="Workout Builder", page_icon="🏗️")
init_db()

st.title("🏗️ Workout Builder")
st.caption(
    "Baut ein strukturiertes Intervall-Lauf-Workout und lädt es zu Garmin Connect hoch. "
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

st.subheader("📋 Workout-Angaben")

name = st.text_input("Workout-Name", value="Intervalltraining")

col1, col2 = st.columns(2)
with col1:
    warmup_minutes = st.number_input("Einlaufen (Minuten)", min_value=1, value=10, step=1)
    warmup_zone = st.selectbox("Einlaufen-Zone", zones, index=0, key="warmup_zone")
with col2:
    cooldown_minutes = st.number_input("Auslaufen (Minuten)", min_value=1, value=10, step=1)
    cooldown_zone = st.selectbox("Auslaufen-Zone", zones, index=0, key="cooldown_zone")

st.markdown("**Intervalle**")
interval_count = st.number_input("Anzahl Intervalle", min_value=1, value=6, step=1)

int_col1, int_col2 = st.columns(2)
with int_col1:
    interval_end_mode = st.radio("Intervall-Ende", ["Distanz", "Dauer"], horizontal=True, key="interval_end_mode")
    if interval_end_mode == "Distanz":
        interval_distance_m = st.number_input("Distanz pro Intervall (m)", min_value=1.0, value=1000.0, step=100.0)
        interval_duration_sec = None
    else:
        interval_duration_sec = st.number_input("Dauer pro Intervall (Sek.)", min_value=1.0, value=240.0, step=10.0)
        interval_distance_m = None

with int_col2:
    interval_target_mode = st.radio("Intervall-Ziel", ["Zone", "Exakte Pace"], horizontal=True, key="interval_target_mode")
    if interval_target_mode == "Zone":
        interval_target_zone = st.selectbox("Ziel-Zone", zones, index=min(3, len(zones) - 1), key="interval_target_zone")
        interval_target_pace_min_per_km = None
    else:
        interval_target_pace_min_per_km = st.number_input(
            "Ziel-Pace (min/km)", min_value=2.0, value=4.5, step=0.1,
            help="z.B. 4.5 = 4:30 min/km"
        )
        interval_target_zone = None

recovery_mode = st.radio("Erholung", ["Dauer", "Distanz"], horizontal=True, key="recovery_mode")
if recovery_mode == "Dauer":
    recovery_duration_sec = st.number_input("Erholungsdauer (Sek.)", min_value=1.0, value=90.0, step=10.0)
    recovery_distance_m = None
else:
    recovery_distance_m = st.number_input("Erholungsdistanz (m)", min_value=1.0, value=200.0, step=50.0)
    recovery_duration_sec = None

if st.button("Vorschau erstellen 🔍"):
    try:
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
                    del st.session_state["draft_workout"]
                else:
                    st.error(f"Upload fehlgeschlagen: {result['error']}")
            except Exception as e:
                st.error(f"Fehler beim Hochladen: {e}")
