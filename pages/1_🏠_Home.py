import json
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, timedelta
from db import get_connection, save_journal_entry, init_db
from ai_coach import generate_daily_coaching

# Schlafphasen-Chart (Test): Farben aus der validierten Default-Palette, aber diese konkrete
# 4er-Kombination (blau/aqua/violett/rot) konnte in dieser Umgebung nicht automatisiert gegen
# den Kontrast-/CVD-Validator geprüft werden (kein Node.js verfügbar) - bei Bedarf später nachholen.
SLEEP_STAGE_LABELS = {0: "Tiefschlaf", 1: "Leichtschlaf", 2: "REM", 3: "Wach"}
SLEEP_STAGE_ORDER = ["Tiefschlaf", "Leichtschlaf", "REM", "Wach"]
SLEEP_STAGE_COLORS = {
    "Tiefschlaf": "#2a78d6",
    "Leichtschlaf": "#1baf7a",
    "REM": "#4a3aa7",
    "Wach": "#d03b3b",
}

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

cursor.execute("SELECT * FROM daily_summary WHERE date = ?", (date_str,))
daily_summary_row = cursor.fetchone()

cursor.execute("SELECT * FROM garmin_sleep_phases WHERE date = ?", (date_str,))
sleep_phases = cursor.fetchone()

# ISO-Kalenderwoche des ausgewählten Tages, um die passende weekly_summary-Zeile zu finden
_iso_year, _iso_week, _ = selected_date.isocalendar()
week_id = f"{_iso_year}-W{_iso_week:02d}"
cursor.execute("SELECT * FROM weekly_summary WHERE week_id = ?", (week_id,))
weekly_summary_row = cursor.fetchone()

cursor.execute("SELECT raw_json FROM garmin_daily WHERE date = ?", (date_str,))
garmin_raw_row = cursor.fetchone()
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

st.divider()

# --- BEREICH 5: NEUE AUSWERTUNGEN (Schicht 1 - Test) ---
st.subheader("🆕 Neue Auswertungen")
st.caption(
    "Testbereich für die neu automatisch bei jedem Sync berechneten Kennzahlen - Vorstufe für "
    "einen künftigen KI-Chat, der auf diesen vorverdichteten Werten aufbaut statt bei jeder Frage "
    "die Rohdaten neu auszuwerten. Rein regelbasiert berechnet (Schwellenwerte/Statistik), kein LLM."
)

if daily_summary_row:
    if daily_summary_row["notable_events_text"]:
        if daily_summary_row["overreach_flag"]:
            st.error(f"⚠️ {daily_summary_row['notable_events_text']}")
        else:
            st.info(f"ℹ️ {daily_summary_row['notable_events_text']}")

    ns1, ns2, ns3, ns4 = st.columns(4)
    with ns1:
        val = daily_summary_row["hrv_vs_7d_avg_pct"]
        st.metric("HRV vs. Ø 7 Tage", f"{val:+.0f}%" if val is not None else "--",
                   help="Vergleich der heutigen HRV gegen den Schnitt der vorangehenden 7 Tage.")
    with ns2:
        val = daily_summary_row["sleep_vs_7d_avg_pct"]
        st.metric("Schlaf vs. Ø 7 Tage", f"{val:+.0f}%" if val is not None else "--",
                   help="Vergleich der Schlafdauer gegen den Schnitt der vorangehenden 7 Tage.")
    with ns3:
        val = daily_summary_row["acute_chronic_ratio"]
        st.metric("Belastung (ACWR)", f"{val:.2f}" if val is not None else "--",
                   help="Akute (7 Tage) zu chronischer (28 Tage) Trainingsbelastung. ~1.0 = ausgeglichen, "
                        "deutlich über 1.5 = erhöhtes Verletzungs-/Übertrainingsrisiko.")
    with ns4:
        val = daily_summary_row["sleep_debt_cumulative"]
        st.metric("Schlafschuld (14 T.)", f"{val:+.1f} h" if val is not None else "--",
                   help="Rollierende Abweichung von deinem individuellen Schlafbedarf (Garmins sleepNeed, "
                        "sonst 8h) über die letzten 14 Tage.")
else:
    st.info("Für diesen Tag liegt noch keine daily_summary vor (füllt sich ab dem nächsten Sync).")

st.markdown(f"**📅 Wochenübersicht** ({week_id})")
if weekly_summary_row:
    if weekly_summary_row["notable_events_text"]:
        st.caption(f"ℹ️ {weekly_summary_row['notable_events_text']}")

    ws1, ws2, ws3, ws4 = st.columns(4)
    ws1.metric("🏃 Laufen", f"{weekly_summary_row['volume_running_km']:.1f} km")
    ws2.metric("🚴 Radfahren", f"{weekly_summary_row['volume_cycling_km']:.1f} km")
    ws3.metric("🏊 Schwimmen", f"{weekly_summary_row['volume_swimming_km']:.1f} km")
    phase = weekly_summary_row["training_phase"]
    ws4.metric("📊 Trainingsphase", phase if phase else "--")

    z1z2 = weekly_summary_row["zone_distribution_z1_z2_pct"]
    days_race = weekly_summary_row["days_until_next_race"]
    limiter = weekly_summary_row["discipline_limiter"]
    detail_bits = []
    if z1z2 is not None:
        detail_bits.append(f"Zone 1-2: {z1z2:.0f}%")
    if days_race is not None:
        detail_bits.append(f"Nächstes Rennen in {days_race} Tagen")
    if limiter:
        detail_bits.append(f"Limiter: {limiter}")
    if detail_bits:
        st.caption(" · ".join(detail_bits))
else:
    st.info("Für diese Woche liegt noch keine weekly_summary vor (füllt sich ab dem nächsten Sync).")


def _fmt_hm(seconds):
    if seconds is None:
        return "–"
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}h {m:02d}m"


st.markdown("**😴 Schlafphasen**")
if sleep_phases:
    sp1, sp2, sp3, sp4 = st.columns(4)
    sp1.metric("Tiefschlaf", _fmt_hm(sleep_phases["deep_sleep_seconds"]),
               f"{sleep_phases['deep_pct']}% · {translate_feedback(sleep_phases['deep_qualifier'])}"
               if sleep_phases["deep_pct"] is not None else None)
    sp2.metric("Leichtschlaf", _fmt_hm(sleep_phases["light_sleep_seconds"]),
               f"{sleep_phases['light_pct']}% · {translate_feedback(sleep_phases['light_qualifier'])}"
               if sleep_phases["light_pct"] is not None else None)
    sp3.metric("REM", _fmt_hm(sleep_phases["rem_sleep_seconds"]),
               f"{sleep_phases['rem_pct']}% · {translate_feedback(sleep_phases['rem_qualifier'])}"
               if sleep_phases["rem_pct"] is not None else None)
    sp4.metric("Wachphasen", f"{sleep_phases['awake_count']}x" if sleep_phases["awake_count"] is not None else "--",
               _fmt_hm(sleep_phases["awake_sleep_seconds"]))

    # Testweise: Minuten-genauer Phasenverlauf aus Garmins Rohdaten (sleepLevels), die schon im
    # bestehenden Sync in garmin_daily.raw_json mitgespeichert werden - noch keine eigene Tabelle,
    # nur zur Ansicht. Vgl. Garmin Connect App ("Sleep Score"-Kachel).
    sleep_levels, gmt_to_local_offset = None, timedelta(0)
    if garmin_raw_row and garmin_raw_row["raw_json"]:
        try:
            blob = json.loads(garmin_raw_row["raw_json"])
            sleep_blob = blob.get("sleep") or {}
            sleep_levels = sleep_blob.get("sleepLevels")
            dto = sleep_blob.get("dailySleepDTO") or {}
            # sleepStartTimestampGMT/...Local sind Epoch-Millisekunden (Integer), keine ISO-Strings -
            # direkt als Millisekunden-Differenz rechnen, nicht über pd.to_datetime() (das einen
            # rohen Integer sonst fälschlich als Nanosekunden interpretiert).
            gmt_start = dto.get("sleepStartTimestampGMT")
            local_start = dto.get("sleepStartTimestampLocal")
            if gmt_start and local_start:
                gmt_to_local_offset = timedelta(milliseconds=local_start - gmt_start)
        except (json.JSONDecodeError, AttributeError, TypeError):
            sleep_levels = None

    if sleep_levels:
        rows = [
            {"Start": lvl["startGMT"], "Ende": lvl["endGMT"], "Phase": SLEEP_STAGE_LABELS[lvl["activityLevel"]]}
            for lvl in sleep_levels if lvl.get("activityLevel") in SLEEP_STAGE_LABELS
        ]
        df_sleep = pd.DataFrame(rows)
        df_sleep["Start"] = pd.to_datetime(df_sleep["Start"]) + gmt_to_local_offset
        df_sleep["Ende"] = pd.to_datetime(df_sleep["Ende"]) + gmt_to_local_offset
        df_sleep["Nacht"] = "Schlaf"

        fig_sleep = px.timeline(
            df_sleep, x_start="Start", x_end="Ende", y="Nacht", color="Phase",
            color_discrete_map=SLEEP_STAGE_COLORS,
            category_orders={"Phase": SLEEP_STAGE_ORDER},
        )
        fig_sleep.update_yaxes(visible=False)
        fig_sleep.update_layout(
            xaxis_title="Uhrzeit (lokal)", legend_title="Phase", height=200,
            margin=dict(l=10, r=10, t=10, b=10)
        )
        st.plotly_chart(fig_sleep, use_container_width=True)
        st.caption(
            "Test-Chart aus Garmins Minuten-Zeitreihe (sleepLevels), die bereits im Sync mitkommt - "
            "noch keine eigene Tabelle, nur zur Ansicht. Farben konnten in dieser Umgebung nicht "
            "automatisiert validiert werden (kein Node.js verfügbar)."
        )
    else:
        st.caption("Keine Minuten-genaue Schlafphasen-Zeitreihe im Rohdaten-Archiv für diesen Tag gefunden.")
else:
    st.info("Keine Schlafphasen-Daten für diesen Tag vorhanden.")
