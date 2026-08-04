import calendar as cal
import html
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
from db import get_connection, init_db

st.set_page_config(page_title="Health Trends", page_icon="📊", layout="wide")
init_db()

st.title("📊 Health & Training Trends")

# Daten aus SQLite laden
conn = get_connection()
df_garmin = pd.read_sql_query("SELECT * FROM garmin_daily ORDER BY date ASC", conn)
df_journal = pd.read_sql_query("SELECT * FROM daily_journal ORDER BY date ASC", conn)
df_readiness = pd.read_sql_query("SELECT date, score FROM garmin_training_readiness ORDER BY date ASC", conn)
df_weigh_ins = pd.read_sql_query("SELECT date, weight FROM garmin_weigh_ins ORDER BY date ASC", conn)
df_events = pd.read_sql_query("SELECT event_date, title, is_race, distance_meters, activity_type_id FROM garmin_scheduled_events ORDER BY event_date ASC", conn)
df_endurance = pd.read_sql_query("SELECT * FROM garmin_endurance_score ORDER BY date DESC LIMIT 1", conn)
df_hill = pd.read_sql_query("SELECT * FROM garmin_hill_score ORDER BY date DESC LIMIT 1", conn)
df_ftp = pd.read_sql_query("SELECT date, functional_threshold_power, measured_date, power_to_weight FROM garmin_cycling_ftp ORDER BY date DESC LIMIT 1", conn)
df_lactate = pd.read_sql_query(
    "SELECT date, speed, heart_rate, heart_rate_cycling, power_to_weight "
    "FROM garmin_lactate_threshold ORDER BY date DESC LIMIT 1", conn
)
conn.close()

today = date.today()
today_str = today.isoformat()

WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Garmins eigene Klassifizierungs-Stufen für den Endurance Score (Schwellenwerte kommen
# direkt aus der API-Antwort, nicht geraten - anders als beim Hill Score, siehe unten).
ENDURANCE_TIERS = [
    ("Elite", "classification_elite"),
    ("Superior", "classification_superior"),
    ("Expert", "classification_expert"),
    ("Well Trained", "classification_well_trained"),
    ("Trained", "classification_trained"),
    ("Intermediate", "classification_intermediate"),
]


def format_pace(sec_per_km):
    if pd.isna(sec_per_km):
        return "–"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/km"


def classify_endurance_score(row):
    """Ordnet den Endurance Score anhand der von Garmin mitgelieferten Schwellenwerte ein.
    Gibt (aktuelle Stufe, nächste Stufe, Punkte bis zur nächsten Stufe) zurück."""
    score = row["overall_score"]
    if pd.isna(score):
        return None, None, None
    for i, (label, col) in enumerate(ENDURANCE_TIERS):
        threshold = row.get(col)
        if pd.notna(threshold) and score >= threshold:
            next_label = ENDURANCE_TIERS[i - 1][0] if i > 0 else None
            next_threshold = row.get(ENDURANCE_TIERS[i - 1][1]) if i > 0 else None
            points_to_next = (next_threshold - score) if pd.notna(next_threshold) else None
            return label, next_label, points_to_next
    return "Beginner", "Intermediate", (row.get("classification_intermediate") - score) if pd.notna(row.get("classification_intermediate")) else None


# --- BEREICH 0: BEVORSTEHENDE EVENTS & GEPLANTE EINHEITEN ---
st.subheader("📅 Bevorstehende Events & geplante Einheiten")

upcoming = df_events[
    (df_events["event_date"] >= today_str) & df_events["title"].notna()
].drop_duplicates(subset=["event_date", "title"])
races = upcoming[upcoming["is_race"] == 1]

if not races.empty:
    race_cols = st.columns(len(races))
    for col, (_, race) in zip(race_cols, races.iterrows()):
        days_left = (pd.to_datetime(race["event_date"]) - pd.to_datetime(today_str)).days
        distance_txt = f" · {race['distance_meters'] / 1000:.1f} km" if pd.notna(race["distance_meters"]) else ""
        with col:
            st.metric(f"🏁 {race['title']}", f"in {days_left} Tagen", f"{race['event_date']}{distance_txt}")
else:
    st.info("Keine bevorstehenden Rennen im Garmin-Kalender gefunden.")

# Events nach Datum gruppiert, für die Kalenderansicht
events_by_date = {}
for _, ev in upcoming.iterrows():
    events_by_date.setdefault(ev["event_date"], []).append(ev)

# Sport-Icons anhand von Garmins eigener activityTypeId (verifiziert gegen get_activity_types()
# aus der API-Exploration, nicht geraten). Trainingsplan-Einheiten ohne activityTypeId
# (z.B. "DL FatMax") fallen auf eine Stichwortsuche im Titel zurück.
RUNNING_TYPE_IDS = {1, 6, 7, 8, 18, 153, 154, 156, 181}
CYCLING_TYPE_IDS = {2, 5, 10, 19, 20, 21, 22, 25, 143, 175, 176, 197, 198}
SWIMMING_TYPE_IDS = {26, 27, 28}
WALKING_TYPE_IDS = {9, 15, 16, 201}
STRENGTH_TYPE_IDS = {13}
MULTISPORT_TYPE_IDS = {89, 190, 191, 192}


def event_icon(ev):
    if ev["is_race"]:
        return "🏁"
    type_id = ev.get("activity_type_id")
    if pd.notna(type_id):
        type_id = int(type_id)
        if type_id in RUNNING_TYPE_IDS:
            return "🏃"
        if type_id in CYCLING_TYPE_IDS:
            return "🚴"
        if type_id in SWIMMING_TYPE_IDS:
            return "🏊"
        if type_id in WALKING_TYPE_IDS:
            return "🚶"
        if type_id in STRENGTH_TYPE_IDS:
            return "🏋️"
        if type_id in MULTISPORT_TYPE_IDS:
            return "🔺"
    title_lower = ev["title"].lower()
    if any(k in title_lower for k in ("lauf", "run", "dl ", "vo2max", "tempo", "intervall")):
        return "🏃"
    if any(k in title_lower for k in ("rad", "bike", "cycl")):
        return "🚴"
    if any(k in title_lower for k in ("schwimm", "swim")):
        return "🏊"
    return "🏋️"


st.caption("Geplante Einheiten & Events aus Garmins Kalender/Trainingsplan (im Kalender selbst nach unten scrollen):")

# Fortlaufender Kalender (keine Monats-Kacheln) - startet am Montag der aktuellen Woche und
# läuft nur bis zum letzten Tag, für den tatsächlich ein Event/Workout vorliegt (statt bis zum
# Ende des synchronisierten Zeitfensters, das oft deutlich weiter reicht als die reale Planung).
# Der 1. eines Monats bekommt einen dickeren linken Rand als dezente Orientierungshilfe.
start_of_week = today - timedelta(days=today.weekday())
if not upcoming.empty:
    end_of_range = pd.to_datetime(upcoming["event_date"]).max().date()
else:
    end_of_range = date(today.year, today.month, cal.monthrange(today.year, today.month)[1])

header_cells = "".join(
    f"<div style='text-align:center;font-size:0.75em;opacity:0.6;'>{wd}</div>" for wd in WEEKDAYS_DE
)

week_rows = []
day_cursor = start_of_week
while day_cursor <= end_of_range:
    day_cells = []
    for _ in range(7):
        day_date_str = day_cursor.isoformat()
        day_events = events_by_date.get(day_date_str, [])
        is_today = day_date_str == today_str
        is_race_day = any(ev["is_race"] for ev in day_events)
        is_month_start = day_cursor.day == 1

        cell_style = ("min-height:60px; border-radius:6px; padding:4px; font-size:0.72em; "
                      "border:1px solid rgba(128,128,128,0.25); overflow-wrap:break-word; word-break:break-word;")
        if is_race_day:
            cell_style += "background:rgba(230,60,60,0.18); border-color:rgba(230,60,60,0.5);"
        elif is_today:
            cell_style += "background:rgba(70,130,230,0.15); border-color:rgba(70,130,230,0.5);"
        if is_month_start:
            cell_style += "border-left:3px solid rgba(128,128,128,0.6);"

        day_num_style = "font-weight:700;" if is_today else "opacity:0.85;"
        day_label = f"{day_cursor.day:02d}.{day_cursor.month:02d}."
        badges = "".join(
            f"<div style='overflow-wrap:break-word; word-break:break-word; line-height:1.25; margin-top:2px;' "
            f"title='{html.escape(ev['title'])}'>{event_icon(ev)} {html.escape(ev['title'])}</div>"
            for ev in day_events
        )
        day_cells.append(f"<div style='{cell_style}'><div style='{day_num_style}'>{day_label}</div>{badges}</div>")
        day_cursor += timedelta(days=1)
    week_rows.append(
        "<div style='display:grid; grid-template-columns:repeat(7, minmax(0,1fr)); gap:4px; margin-bottom:4px;'>"
        + "".join(day_cells) + "</div>"
    )

calendar_html = (
    "<div style='display:grid; grid-template-columns:repeat(7, minmax(0,1fr)); gap:4px; margin-bottom:6px;'>"
    + header_cells + "</div>" + "".join(week_rows)
)
st.markdown(
    "<div style='max-height:480px; overflow-y:auto; border:1px solid rgba(128,128,128,0.2); "
    "border-radius:10px; padding:14px;'>" + calendar_html + "</div>",
    unsafe_allow_html=True
)

# --- Aktuelle Leistungswerte, nach Sportart gruppiert (noch wenig Historie, daher als
# Kennzahl statt Trendlinie) ---
st.divider()
lactate_row = df_lactate.iloc[0] if not df_lactate.empty else None
ftp_row = df_ftp.iloc[0] if not df_ftp.empty else None

st.markdown("**🏃 Laufen**")
run_cols = st.columns(5)
with run_cols[0]:
    if not df_endurance.empty and pd.notna(df_endurance.iloc[0]["overall_score"]):
        row = df_endurance.iloc[0]
        tier, next_tier, points_to_next = classify_endurance_score(row)
        delta = f"{tier}" + (f" · noch {int(points_to_next)} bis {next_tier}" if points_to_next is not None and points_to_next > 0 else "")
        st.metric("Endurance Score", int(row["overall_score"]), delta, help=f"Stand: {row['date']} · Skala {row['gauge_lower_limit']}-{row['gauge_upper_limit']} (Garmins eigene Einordnung)")
    else:
        st.metric("Endurance Score", "--")
with run_cols[1]:
    if not df_hill.empty and pd.notna(df_hill.iloc[0]["overall_score"]):
        row = df_hill.iloc[0]
        st.metric("Hill Score", int(row["overall_score"]), help=f"Stand: {row['date']} · Garmin liefert für den Hill Score über die API keine Klassifizierungs-Schwellenwerte, daher hier ohne Einordnung (roher Score + Klassifizierungs-ID {int(row['classification_id']) if pd.notna(row['classification_id']) else '?'})")
    else:
        st.metric("Hill Score", "--")
with run_cols[2]:
    if lactate_row is not None and pd.notna(lactate_row["heart_rate"]):
        st.metric("LTHR", f"{int(lactate_row['heart_rate'])} bpm", help=f"Stand: {lactate_row['date']}")
    else:
        st.metric("LTHR", "--")
with run_cols[3]:
    if lactate_row is not None and pd.notna(lactate_row["speed"]) and lactate_row["speed"]:
        pace = 1000.0 / lactate_row["speed"]
        st.metric("Schwellenpace", format_pace(pace), help=f"Stand: {lactate_row['date']}")
    else:
        st.metric("Schwellenpace", "--")
with run_cols[4]:
    if lactate_row is not None and pd.notna(lactate_row["power_to_weight"]):
        st.metric("Leistung/kg", f"{lactate_row['power_to_weight']:.2f} W/kg", help=f"Stand: {lactate_row['date']} · Lauf-Leistungsschwelle (Garmin taggt sie selbst mit \"sport\":\"RUNNING\"), keine Rad-FTP")
    else:
        st.metric("Leistung/kg", "--")

st.markdown("**🚴 Radfahren**")
bike_cols = st.columns(2)
with bike_cols[0]:
    if lactate_row is not None and pd.notna(lactate_row["heart_rate_cycling"]):
        st.metric("Bike-LTHR", f"{int(lactate_row['heart_rate_cycling'])} bpm", help=f"Stand: {lactate_row['date']}")
    else:
        st.metric("Bike-LTHR", "--")
with bike_cols[1]:
    if ftp_row is not None and pd.notna(ftp_row["functional_threshold_power"]):
        watts = int(ftp_row["functional_threshold_power"])
        if pd.notna(ftp_row["power_to_weight"]):
            st.metric("FTP", f"{ftp_row['power_to_weight']:.2f} W/kg", help=f"{watts} W · Gemessen: {ftp_row['measured_date']} · W/kg selbst aus FTP und aktuellstem Gewicht berechnet (Garmin liefert kein W/kg für Rad-FTP)")
        else:
            st.metric("FTP", f"{watts} W", help=f"Gemessen: {ftp_row['measured_date']} · W/kg konnte nicht berechnet werden (kein Körpergewicht vorhanden)")
    else:
        st.metric("FTP", "--")

st.divider()

if df_garmin.empty:
    st.info("Noch keine Garmin-Daten für historische Trends vorhanden. Synchronisiere zuerst ein paar Tage!")
else:
    # 1. HRV & Ruhepuls Trend
    st.subheader("❤️ HRV & Ruhepuls-Verlauf")
    fig_hr = px.line(
        df_garmin,
        x="date",
        y=["avg_hrv", "resting_hr"],
        labels={"value": "Wert", "date": "Datum", "variable": "Metrik"},
        title="HRV (Ø) vs. Ruhepuls (bpm)"
    )
    st.plotly_chart(fig_hr, use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        # 2. Schlaf-Metriken
        st.subheader("😴 Schlaf-Qualität & Dauer")
        if "sleep_hours" in df_garmin.columns and not df_garmin["sleep_hours"].isna().all():
            fig_sleep = px.bar(
                df_garmin,
                x="date",
                y="sleep_hours",
                color="sleep_score",
                labels={"sleep_hours": "Stunden", "date": "Datum", "sleep_score": "Schlaf-Score"},
                title="Schlafdauer & Score"
            )
            st.plotly_chart(fig_sleep, use_container_width=True)

    with col2:
        # 3. Readiness Score Verlauf: Garmins eigener Trainingsbereitschafts-Score
        st.subheader("🎯 Trainingsbereitschaft (Garmin)")
        if not df_readiness.empty:
            fig_readiness = go.Figure()
            fig_readiness.add_trace(go.Scatter(
                x=df_readiness["date"], y=df_readiness["score"], mode="lines+markers", name="Garmin-Score"
            ))
            fig_readiness.update_layout(
                yaxis_range=[0, 100], yaxis_title="Score (0-100)", xaxis_title="Datum",
                title="Bereitschafts-Score über Zeit"
            )
            st.plotly_chart(fig_readiness, use_container_width=True)
        else:
            st.info("Noch keine Readiness-Daten vorhanden.")

    # 4. Gewichtsverlauf
    if not df_weigh_ins.empty and df_weigh_ins["weight"].notna().any():
        st.divider()
        st.subheader("⚖️ Gewichtsverlauf")
        df_weigh_ins["weight_kg"] = df_weigh_ins["weight"] / 1000.0
        fig_weight = px.line(
            df_weigh_ins, x="date", y="weight_kg", markers=True,
            labels={"weight_kg": "Gewicht (kg)", "date": "Datum"},
            title="Körpergewicht über Zeit"
        )
        st.plotly_chart(fig_weight, use_container_width=True)

    # 5. Subjektives Befinden (aus dem Journal)
    if not df_journal.empty:
        st.divider()
        st.subheader("📝 Subjektives Befinden (RPE & Muskelkater)")
        fig_journal = px.line(
            df_journal,
            x="date",
            y=["rpe_score", "muscle_soreness", "energy_level"],
            labels={"value": "Skala", "date": "Datum", "variable": "Kategorie"},
            title="Belastung (RPE), Muskelkater & Energie"
        )
        st.plotly_chart(fig_journal, use_container_width=True)
