import streamlit as st
import pandas as pd
import plotly.express as px
import pydeck as pdk
from db import get_connection, init_db

st.set_page_config(page_title="Aktivitäten", page_icon="🏃", layout="wide")
init_db()

st.title("🏃 Aktivitäten-Auswertung")

SPORT_ICONS = {
    "running": "🏃", "trail_running": "🏃", "treadmill_running": "🏃",
    "track_running": "🏃", "street_running": "🏃", "indoor_running": "🏃", "ultra_run": "🏃",
    "cycling": "🚴", "road_biking": "🚴", "mountain_biking": "🚴",
    "indoor_cycling": "🚴", "gravel_cycling": "🚴", "cyclocross": "🚴",
    "lap_swimming": "🏊", "open_water_swimming": "🏊",
    "walking": "🚶", "casual_walking": "🚶", "speed_walking": "🚶",
    "strength_training": "🏋️",
    "multi_sport": "🔺",
}


def sport_icon(activity_type):
    return SPORT_ICONS.get(activity_type, "🏅")


def format_duration(seconds):
    if seconds is None or pd.isna(seconds):
        return "–"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"


conn = get_connection()
df = pd.read_sql_query("SELECT * FROM garmin_activities ORDER BY start_time_local DESC", conn)
conn.close()

if df.empty:
    st.info("Noch keine Aktivitäten synchronisiert. Gehe zu ⚙️ Settings, um welche zu laden.")
    st.stop()

df["start_dt"] = pd.to_datetime(df["start_time_local"])
df["start_date"] = df["start_dt"].dt.date
df["distance_km"] = (df["distance_meters"].fillna(0) / 1000.0).round(2)
df["duration_min"] = (df["duration_seconds"].fillna(0) / 60.0).round(1)

# --- FILTER ---
st.subheader("Filter")
f1, f2, f3, f4 = st.columns(4)

with f1:
    types = sorted(df["activity_type"].dropna().unique().tolist())
    selected_types = st.multiselect("Sportart", types, default=types,
                                     format_func=lambda t: f"{sport_icon(t)} {t}")

with f2:
    min_date, max_date = df["start_date"].min(), df["start_date"].max()
    date_range = st.date_input("Zeitraum", value=(min_date, max_date),
                                min_value=min_date, max_value=max_date)

with f3:
    max_km = max(float(df["distance_km"].max()), 1.0)
    km_range = st.slider("Distanz (km)", 0.0, max_km, (0.0, max_km))

with f4:
    max_dur = max(float(df["duration_min"].max()), 1.0)
    dur_range = st.slider("Dauer (Min)", 0.0, max_dur, (0.0, max_dur))

filtered = df[df["activity_type"].isin(selected_types)]
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_d, end_d = date_range
    filtered = filtered[(filtered["start_date"] >= start_d) & (filtered["start_date"] <= end_d)]
filtered = filtered[
    filtered["distance_km"].between(km_range[0], km_range[1])
    & filtered["duration_min"].between(dur_range[0], dur_range[1])
].reset_index(drop=True)

st.caption(f"{len(filtered)} von {len(df)} Aktivitäten")

if filtered.empty:
    st.info("Keine Aktivitäten für die aktuelle Filterauswahl.")
    st.stop()

# --- ÜBERSICHTSTABELLE (klickbar) ---
display_df = pd.DataFrame({
    "Datum": filtered["start_dt"].dt.strftime("%d.%m.%Y %H:%M"),
    "Sport": filtered["activity_type"].apply(lambda t: f"{sport_icon(t)} {t}"),
    "Name": filtered["activity_name"],
    "km": filtered["distance_km"],
    "Dauer": filtered["duration_seconds"].apply(format_duration),
    "Ø HF": filtered["average_hr"],
    "Kalorien": filtered["calories"],
    "PR": filtered["is_pr"].apply(lambda x: "🏆" if x else ""),
    "Details": filtered["has_details_synced"].apply(lambda x: "✅" if x else "—"),
})

event = st.dataframe(
    display_df, hide_index=True, use_container_width=True,
    on_select="rerun", selection_mode="single-row", key="activities_table"
)

selected_rows = event.selection["rows"] if event and event.selection else []

st.divider()

if not selected_rows:
    st.info("👆 Klicke auf eine Zeile in der Tabelle, um die Details einer Aktivität zu sehen.")
    st.stop()

row = filtered.iloc[selected_rows[0]]
activity_id = int(row["activity_id"])

# --- DETAILBEREICH ---
st.subheader(f"{sport_icon(row['activity_type'])} {row['activity_name']} — {row['start_dt'].strftime('%d.%m.%Y %H:%M')}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Distanz", f"{row['distance_km']:.2f} km")
m2.metric("Dauer", format_duration(row["duration_seconds"]))
m3.metric("Ø Puls", f"{row['average_hr']:.0f} bpm" if pd.notna(row["average_hr"]) else "–")
m4.metric("Kalorien", f"{row['calories']:.0f}" if pd.notna(row["calories"]) else "–")
m5.metric("Höhenmeter", f"{row['elevation_gain']:.0f} m" if pd.notna(row["elevation_gain"]) else "–")

extra_bits = []
if pd.notna(row["cadence"]):
    extra_bits.append(f"Ø Kadenz: {row['cadence']:.0f} {row['cadence_unit'] or ''}")
if pd.notna(row["avg_power"]):
    extra_bits.append(f"Ø Leistung: {row['avg_power']:.0f} W")
if pd.notna(row["aerobic_training_effect"]):
    extra_bits.append(f"Trainingseffekt: {row['aerobic_training_effect']:.1f} ({row['training_effect_label'] or '–'})")
if extra_bits:
    st.caption(" · ".join(extra_bits))

if not row["has_details_synced"]:
    st.info(
        "Detaillierte Zeitreihe (HF-/Leistungs-/Höhenverlauf, Strecke) für diese Aktivität "
        "noch nicht geladen. Kannst du in ⚙️ Settings unter 'Aktivitäten' nachholen."
    )
    st.stop()

conn = get_connection()
details = pd.read_sql_query(
    "SELECT * FROM garmin_activity_details WHERE activity_id = ? ORDER BY seq",
    conn, params=(activity_id,)
)
conn.close()

if details.empty:
    st.info("Keine Detail-Datenpunkte für diese Aktivität vorhanden.")
    st.stop()

if details["timestamp"].notna().any():
    t0 = details["timestamp"].min()
    details["elapsed_min"] = (details["timestamp"] - t0) / 1000.0 / 60.0
else:
    details["elapsed_min"] = details["seq"] / 60.0

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    if details["heart_rate"].notna().any():
        fig = px.line(
            details, x="elapsed_min", y="heart_rate",
            labels={"elapsed_min": "Minuten", "heart_rate": "Herzfrequenz (bpm)"},
            title="❤️ Herzfrequenz-Verlauf"
        )
        st.plotly_chart(fig, use_container_width=True)

with chart_col2:
    if details["power"].notna().any() and details["power"].max() > 0:
        fig = px.line(
            details, x="elapsed_min", y="power",
            labels={"elapsed_min": "Minuten", "power": "Leistung (W)"},
            title="⚡ Leistungs-Verlauf"
        )
        st.plotly_chart(fig, use_container_width=True)
    elif details["speed"].notna().any():
        details["speed_kmh"] = details["speed"] * 3.6
        fig = px.line(
            details, x="elapsed_min", y="speed_kmh",
            labels={"elapsed_min": "Minuten", "speed_kmh": "Geschwindigkeit (km/h)"},
            title="🏃 Geschwindigkeits-Verlauf"
        )
        st.plotly_chart(fig, use_container_width=True)

chart_col3, chart_col4 = st.columns(2)

with chart_col3:
    if details["elevation"].notna().any():
        fig = px.area(
            details, x="elapsed_min", y="elevation",
            labels={"elapsed_min": "Minuten", "elevation": "Höhe (m)"},
            title="⛰️ Höhenprofil"
        )
        st.plotly_chart(fig, use_container_width=True)

with chart_col4:
    if details["cadence"].notna().any():
        fig = px.line(
            details, x="elapsed_min", y="cadence",
            labels={"elapsed_min": "Minuten", "cadence": f"Kadenz ({row['cadence_unit'] or ''})"},
            title="🦵 Kadenz-Verlauf"
        )
        st.plotly_chart(fig, use_container_width=True)

geo = details.dropna(subset=["latitude", "longitude"])
if not geo.empty:
    st.subheader("📍 Strecke")
    # PathLayer statt st.map()-Scatterplot: bei hunderten dicht liegenden GPS-Punkten
    # überlappen sich die Punkt-Marker sonst zu einem dicken Blob statt einer dünnen Linie.
    path = geo[["longitude", "latitude"]].values.tolist()
    path_df = pd.DataFrame({"path": [path]})

    layer = pdk.Layer(
        "PathLayer",
        data=path_df,
        get_path="path",
        get_color=[200, 30, 30],
        get_width=3,
        width_min_pixels=2,
        width_max_pixels=4,
        pickable=False,
    )
    view_state = pdk.ViewState(
        latitude=geo["latitude"].mean(),
        longitude=geo["longitude"].mean(),
        zoom=12,
    )
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, map_style=None))
