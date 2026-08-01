import streamlit as st
import pandas as pd
import plotly.express as px
from db import get_connection, init_db

st.set_page_config(page_title="Health Trends", page_icon="📊", layout="wide")
init_db()

st.title("📊 Health & Training Trends")

# Daten aus SQLite laden
conn = get_connection()
df_garmin = pd.read_sql_query("SELECT * FROM garmin_daily ORDER BY date ASC", conn)
df_journal = pd.read_sql_query("SELECT * FROM daily_journal ORDER BY date ASC", conn)
df_ai = pd.read_sql_query("SELECT * FROM ai_coach_insights ORDER BY date ASC", conn)
conn.close()

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
        # 3. Readiness Score Verlauf
        st.subheader("🤖 KI Readiness Score Trend")
        if not df_ai.empty:
            fig_ai = px.line(
                df_ai, 
                x="date", 
                y="readiness_score", 
                range_y=[0, 100],
                markers=True,
                labels={"readiness_score": "Score (0-100)", "date": "Datum"},
                title="Bereitschafts-Score über Zeit"
            )
            st.plotly_chart(fig_ai, use_container_width=True)

    # 4. Subjektives Befinden (aus dem Journal)
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