import streamlit as st
from datetime import date, timedelta
from garmin_auth import get_garmin_client
from garmin_service import fetch_and_store_garmin_data
from garmin_backfill import run_backfill
from db import init_db

st.set_page_config(page_title="Einstellungen & Data Engine", page_icon="⚙️")
init_db()

st.title("⚙️ Einstellungen & Daten-Synchronisation")

st.subheader("Garmin Connect Sync")
col1, col2 = st.columns([2, 1])

with col1:
    sync_date = st.date_input("Datum für Synchronisation wählen", value=date.today())

with col2:
    st.write("")  # Spacer
    st.write("")
    if st.button("Jetzt Synchronisieren 🔄"):
        with st.spinner("Lade Daten von Garmin Connect..."):
            try:
                # Gecachten/persistierten Client nutzen statt bei jedem Klick
                # neu per Passwort einzuloggen.
                client = get_garmin_client()
                data = fetch_and_store_garmin_data(sync_date.isoformat(), client=client)
                st.success(f"Daten für {sync_date} erfolgreich gespeichert!")
                st.json(data)
            except Exception as e:
                st.error(f"Fehler beim Sync: {e}")

st.divider()

st.subheader("📦 Backfill über Zeitraum")
st.caption("Lädt Daten für jeden Tag zwischen Start- und Enddatum nach.")

bf_col1, bf_col2 = st.columns(2)
with bf_col1:
    backfill_start = st.date_input(
        "Startdatum", value=date.today() - timedelta(days=7), key="backfill_start"
    )
with bf_col2:
    backfill_end = st.date_input("Enddatum", value=date.today(), key="backfill_end")

if backfill_start > backfill_end:
    st.warning("Das Startdatum muss vor oder gleich dem Enddatum liegen.")
elif st.button("Backfill starten 🚀"):
    total_days = (backfill_end - backfill_start).days + 1
    st.write(f"Starte Import für {total_days} Tage ({backfill_start} bis {backfill_end})...")

    progress_bar = st.progress(0)
    status_placeholder = st.empty()

    try:
        client = get_garmin_client()
    except Exception as e:
        st.error(f"Konnte keine Garmin-Session herstellen: {e}")
        client = None

    if client:
        def on_progress(current_date, status, success_count, error_count, total):
            done = success_count + error_count
            progress_bar.progress(min(done / total, 1.0))
            if status == "ok":
                status_placeholder.write(f"✅ {current_date.isoformat()} gespeichert")
            elif status == "rate_limited":
                status_placeholder.error(
                    f"🛑 Rate-Limit erreicht bei {current_date.isoformat()} — Backfill abgebrochen, "
                    "um die Sperre nicht zu verlängern."
                )
            else:
                status_placeholder.warning(f"❌ Fehler bei {current_date.isoformat()}")

        success_count, error_count, stopped_early = run_backfill(
            backfill_start, backfill_end, client, on_progress=on_progress
        )

        progress_bar.progress(1.0)

        if stopped_early:
            st.error(
                f"Backfill wegen Rate-Limit abgebrochen. "
                f"Erfolgreich: {success_count}, Fehler: {error_count}. "
                "Bitte später erneut versuchen."
            )
        else:
            st.success(
                f"🎉 Backfill abgeschlossen! Erfolgreich: {success_count}, Fehler: {error_count}"
            )
