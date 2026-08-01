import streamlit as st
from datetime import date
from db import get_connection, save_journal_entry, init_db
from ai_coach import generate_daily_coaching

st.set_page_config(page_title="Tagesübersicht", page_icon="🏠", layout="wide")
init_db()

st.title("🏠 Tagesübersicht & KI-Coach")

# Datums-Auswahl oben rechts
selected_date = st.date_input("Datum auswählen", value=date.today())
date_str = selected_date.isoformat()

# Daten aus SQLite laden
conn = get_connection()
cursor = conn.cursor()
cursor.execute("SELECT * FROM garmin_daily WHERE date = ?", (date_str,))
garmin = cursor.fetchone()

cursor.execute("SELECT * FROM ai_coach_insights WHERE date = ?", (date_str,))
ai_insight = cursor.fetchone()

cursor.execute("SELECT * FROM daily_journal WHERE date = ?", (date_str,))
journal = cursor.fetchone()
conn.close()

st.divider()

# --- BEREICH 1: METRIKEN & BEREITSCHAFTS-SCORE ---
col_score, col_m1, col_m2, col_m3, col_m4 = st.columns([1.5, 1, 1, 1, 1])

with col_score:
    if ai_insight:
        score = ai_insight["readiness_score"]
        st.metric("🤖 KI Readiness Score", f"{score} / 100")
    else:
        st.metric("🤖 KI Readiness Score", "-- / 100")

with col_m1:
    st.metric("😴 Schlaf", f"{garmin['sleep_hours']} h" if garmin and garmin['sleep_hours'] else "--", 
              f"Score: {garmin['sleep_score']}" if garmin and garmin['sleep_score'] else None)

with col_m2:
    st.metric("❤️ Ruhepuls", f"{garmin['resting_hr']} bpm" if garmin and garmin['resting_hr'] else "--")

with col_m3:
    st.metric("📈 HRV (Ø)", f"{garmin['avg_hrv']} ms" if garmin and garmin['avg_hrv'] else "--")

with col_m4:
    st.metric("🏃 Schritte", f"{garmin['steps']:,}" if garmin and garmin['steps'] else "--")

st.divider()

# --- BEREICH 2: KI COACH INSIGHTS ---
st.subheader("🤖 KI-Coach Auswertung")

if ai_insight:
    st.success(f"**Status:** {ai_insight['status_summary']}")
    st.write(ai_insight['coaching_advice'])
else:
    st.info("Noch keine KI-Analyse für diesen Tag vorhanden.")

if st.button("🤖 Analyse jetzt von Gemini generieren / aktualisieren"):
    with st.spinner("Gemini analysiert deine Daten und berechnet den Score..."):
        try:
            res = generate_daily_coaching(date_str)
            if "error" in res:
                st.warning(res["error"])
            else:
                st.rerun()
        except Exception as e:
            st.error(f"Fehler bei der KI-Analyse: {e}")

st.divider()

# --- BEREICH 3: FORMULAR SUBJEKTIVES TAGESJOURNAL ---
st.subheader("📝 Subjektives Tagesjournal & Befinden")

journal_dict = dict(journal) if journal else {}

with st.form("journal_form"):
    f_col1, f_col2, f_col3 = st.columns(3)
    
    with f_col1:
        rpe = st.slider("Belastungsempfinden (RPE)", 1, 10, value=journal_dict.get("rpe_score", 5),
                        help="1 = Völlig entspannt, 10 = Maximale Erschöpfung")
    with f_col2:
        soreness = st.slider("Muskelkater / Frische", 1, 5, value=journal_dict.get("muscle_soreness", 3),
                             help="1 = Keinerlei Muskelkater, 5 = Extremer Muskelkater")
    with f_col3:
        energy = st.slider("Energielevel", 1, 5, value=journal_dict.get("energy_level", 3),
                           help="1 = Sehr müde/schlapp, 5 = Voller Energie")

    notes = st.text_area("Tagesnotizen & Besonderheiten", value=journal_dict.get("notes", ""),
                         placeholder="z.B. Spätes Essen, Stress bei der Arbeit, gute Beine beim Laufen...")

    submitted = st.form_submit_button("Journal-Eintrag speichern 💾")
    if submitted:
        save_journal_entry(date_str, rpe, soreness, energy, notes)
        st.success("Tagesjournal gespeichert!")
        st.rerun()