import streamlit as st
from datetime import date
from garmin_service import fetch_and_store_garmin_data
from db import init_db

st.set_page_config(page_title="Einstellungen & Data Engine", page_icon="⚙️")
init_db()

st.title("⚙️ Einstellungen & Daten-Synchronisation")

st.subheader("Garmin Connect Sync")
col1, col2 = st.columns([2, 1])

with col1:
    sync_date = st.date_input("Datum für Synchronisation wählen", value=date.today())

with col2:
    st.write("") # Spacer
    st.write("")
    if st.button("Jetzt Synchronisieren 🔄"):
        with st.spinner("Lade Daten von Garmin Connect..."):
            try:
                data = fetch_and_store_garmin_data(sync_date.isoformat())
                st.success(f"Daten für {sync_date} erfolgreich gespeichert!")
                st.json(data)
            except Exception as e:
                st.error(f"Fehler beim Sync: {e}")