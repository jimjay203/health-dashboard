import json
import streamlit as st
from datetime import date
from db import get_connection, save_journal_entry, init_db
from ai_coach import generate_daily_coaching

# Garmin liefert die Faktor-Bewertungen als Enum-Codes (z.B. "POOR", "GOOD") statt als
# fertigen Text - hier übersetzt, statt den kryptischen "feedbackLong"-Kombicode
# (z.B. "LOW_RT_HIGH_SS_GOOD_OR_MOD") zu zeigen oder zu raten, was der bedeutet.
FEEDBACK_LABELS = {
    "EXCELLENT": "Exzellent",
    "GOOD": "Gut",
    "FAIR": "Befriedigend",
    "MODERATE": "Mäßig",
    "POOR": "Schlecht",
    "NONE": "Keine Daten",
    "LOW": "Niedrig",
    "HIGH": "Hoch",
}
FEEDBACK_SEVERITY = {"POOR": 0, "FAIR": 1, "MODERATE": 2, "GOOD": 3, "EXCELLENT": 4}


def translate_feedback(code):
    if not code:
        return None
    return FEEDBACK_LABELS.get(code, code.replace("_", " ").title())

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

cursor.execute("SELECT * FROM garmin_training_readiness WHERE date = ?", (date_str,))
readiness = cursor.fetchone()
conn.close()

st.divider()

# --- BEREICH 1: SUBJEKTIVES TAGESJOURNAL & BEFINDEN ---
# Ganz oben: morgens als erstes das Befinden erfassen, danach direkt die KI-Auswertung
# anstoßen (die das Journal als Kontext mit einbezieht).
journal_header_col, journal_status_col = st.columns([3, 1])
with journal_header_col:
    st.subheader("📝 Subjektives Tagesjournal & Befinden")
with journal_status_col:
    if journal:
        st.success("✅ Erfasst")
    else:
        st.info("⏳ Offen")

journal_dict = dict(journal) if journal else {}

if journal:
    # Ergebnis-Ansicht statt des Formulars, damit es nicht dauerhaft Platz einnimmt
    jr1, jr2, jr3 = st.columns(3)
    jr1.metric("Belastung (RPE)", f"{journal_dict['rpe_score']}/10")
    jr2.metric("Muskelkater / Frische", f"{journal_dict['muscle_soreness']}/5")
    jr3.metric("Energielevel", f"{journal_dict['energy_level']}/5")
    if journal_dict.get("notes"):
        st.caption(f"📝 {journal_dict['notes']}")

with st.expander("Journal bearbeiten" if journal else "📝 Journal jetzt ausfüllen", expanded=not journal):
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

st.divider()

# --- BEREICH 2: KI COACH INSIGHTS ---
coach_header_col, coach_status_col = st.columns([3, 1])
with coach_header_col:
    st.subheader("🤖 KI-Coach Auswertung")
with coach_status_col:
    if ai_insight:
        st.success("✅ Abgefragt")
    else:
        st.info("⏳ Offen")

if ai_insight:
    # Empfehlungen zuerst und auf einen Blick lesbar - der ausführliche Begründungstext
    # (coaching_advice) steht bewusst erst im Expander darunter, nicht direkt im Fließtext.
    if ai_insight["training_focus"]:
        st.markdown(f"#### 🎯 {ai_insight['training_focus']}")

    recommendations = json.loads(ai_insight["key_recommendations"]) if ai_insight["key_recommendations"] else []
    if recommendations:
        for rec in recommendations:
            st.markdown(f"- **{rec}**")
    else:
        st.markdown(f"**{ai_insight['status_summary']}**")

    with st.expander("Ausführliche Begründung"):
        st.caption(ai_insight["status_summary"])
        st.write(ai_insight["coaching_advice"])
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

# --- BEREICH 3: METRIKEN & BEREITSCHAFTS-SCORE ---
col_score, col_m1, col_m2, col_m3, col_m4 = st.columns([1.5, 1, 1, 1, 1])

with col_score:
    if ai_insight:
        score = ai_insight["readiness_score"]
        st.metric("🤖 KI-Score", f"{score} / 100")
    else:
        st.metric("🤖 KI-Score", "-- / 100")

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

# --- BEREICH 4: TRAININGSBEREITSCHAFT (Garmin) ---
st.subheader("🎯 Trainingsbereitschaft (Garmin)")

if readiness:
    level = readiness["level"] or ""
    level_icon = {"LOW": "🔴", "MODERATE": "🟡", "HIGH": "🟢"}.get(level, "⚪")

    # Faktoren, aus denen sich der Score zusammensetzt - jeweils (Label, Prozent, Feedback-Code)
    factors = [
        ("😴 Schlaf (letzte Nacht)", readiness["sleep_score_factor_percent"], readiness["sleep_score_factor_feedback"]),
        ("📅 Schlaf-Historie", readiness["sleep_history_factor_percent"], readiness["sleep_history_factor_feedback"]),
        ("📈 HRV", readiness["hrv_factor_percent"], readiness["hrv_factor_feedback"]),
        ("⏱️ Erholungszeit", readiness["recovery_time_factor_percent"], readiness["recovery_time_factor_feedback"]),
        ("⚖️ Belastungsverhältnis (ACWR)", readiness["acwr_factor_percent"], readiness["acwr_factor_feedback"]),
        ("😣 Stress-Historie", readiness["stress_history_factor_percent"], readiness["stress_history_factor_feedback"]),
    ]
    # Schlechtesten bewerteten Faktor als "Hauptgrund" hervorheben (NONE = keine Daten, zählt nicht als schlecht)
    rated_factors = [f for f in factors if f[2] in FEEDBACK_SEVERITY]
    worst_factor = min(rated_factors, key=lambda f: FEEDBACK_SEVERITY[f[2]]) if rated_factors else None

    # Nur Score + empfohlene Erholung als eigene Metrik - die 6 Einzelfaktoren stehen
    # bereits vollständig im Detail-Expander darunter, nicht hier nochmal wiederholen.
    r1, r2 = st.columns(2)
    with r1:
        score_txt = f"{readiness['score']} / 100" if readiness["score"] is not None else "--"
        st.metric(f"{level_icon} Garmin-Score", score_txt, level.title() if level else None)
    with r2:
        recovery_hours = round(readiness["recovery_time"] / 60, 1) if readiness["recovery_time"] else None
        st.metric("⏱️ Empf. Erholung", f"{recovery_hours} h" if recovery_hours is not None else "--")

    if worst_factor:
        label, percent, feedback_code = worst_factor
        st.caption(f"Hauptgrund für den Score: **{label}** ist aktuell **{translate_feedback(feedback_code)}**"
                   f"{f' ({percent}%)' if percent is not None else ''}.")

    with st.expander("Alle Faktoren im Detail"):
        for label, percent, feedback_code in factors:
            pct_txt = f"{percent}%" if percent is not None else "–"
            fb_txt = translate_feedback(feedback_code) or "–"
            st.write(f"- **{label}:** {pct_txt} · {fb_txt}")
else:
    st.info("Keine Garmin-Trainingsbereitschaftsdaten für diesen Tag vorhanden. Synchronisiere zuerst über die Settings-Seite.")
