import streamlit as st
from db import init_db
from insight_memory import (
    list_raw_entries,
    list_compressed_versions,
    add_raw_entry,
    delete_raw_entry,
)

st.set_page_config(page_title="Erkenntnis-Gedächtnis", page_icon="🧠")
init_db()

st.title("🧠 Erkenntnis-Gedächtnis")
st.caption(
    "Schicht 3 der KI-Chat-Vorbereitung: Zusatzinfos, die sich nicht aus den Trainingsdaten "
    "ablesen lassen (z.B. feste Wochenroutinen wie Vereinstraining), in deinen eigenen Worten. "
    "Gemini dampft deine Einträge unten auf das Wesentliche ein, damit der komplette Text später "
    "günstig als Kontext für einen KI-Chat mitgegeben werden kann."
)

st.divider()

# --- Aktueller verdichteter Stand ---
st.subheader("📄 Aktueller Stand")
versions = list_compressed_versions()
if versions:
    latest = versions[0]
    st.caption(f"Version {latest['version']} · zuletzt aktualisiert {latest['updated_at']}")
    st.text_area("compressed_text", value=latest["compressed_text"] or "", height=200,
                 disabled=True, label_visibility="collapsed")
else:
    st.info("Noch kein verdichteter Text vorhanden - lege unten den ersten Eintrag an.")

if len(versions) > 1:
    with st.expander(f"Verlauf ({len(versions)} Versionen)"):
        for v in versions[1:]:
            st.markdown(f"**Version {v['version']}** · {v['updated_at']}")
            st.caption(v["compressed_text"] or "")

st.divider()

# --- Neuer manueller Eintrag ---
st.subheader("✏️ Neuen Eintrag hinzufügen")
st.caption(
    "Wird sofort verdichtet (nicht gesammelt): präzisiert/korrigiert der Eintrag Bestehendes, "
    "wird die alte Stelle ersetzt statt dupliziert; ist er redundant, wird er ignoriert."
)
with st.form("insight_memory_form", clear_on_submit=True):
    raw_text = st.text_area("Neuer Rohtext", placeholder=(
        "z.B. \"Ich vertrage Hitze über 25°C schlecht, sollte im Sommer früh morgens laufen.\""
    ))
    submitted = st.form_submit_button("Merken 🧠")

if submitted:
    if not raw_text or not raw_text.strip():
        st.warning("Bitte einen Text eingeben.")
    else:
        with st.spinner("Gemini verdichtet den neuen Eintrag ins Gedächtnis..."):
            try:
                add_raw_entry(raw_text.strip(), source="user")
                st.success("Gemerkt und verdichtet!")
                st.rerun()
            except Exception as e:
                st.error(f"Fehler beim Verdichten: {e}")

st.divider()

# --- Bisherige Rohtext-Einträge ---
st.subheader("🗂️ Bisherige Rohtext-Einträge")
st.caption("Archiv, wird nie von der KI verändert. Löschen entfernt nur den Rohtext, keine erneute Verdichtung.")

raw_entries = list_raw_entries()
if not raw_entries:
    st.info("Noch keine Einträge.")
else:
    for entry in raw_entries:
        col_text, col_delete = st.columns([5, 1])
        with col_text:
            source_label = "🤖 Claude-Import" if entry["source"] == "claude_import" else "👤 Du"
            st.markdown(f"**{entry['created_at']}** · {source_label}")
            st.caption(entry["raw_text"])
        with col_delete:
            if st.button("🗑️", key=f"delete_{entry['id']}"):
                delete_raw_entry(entry["id"])
                st.rerun()
