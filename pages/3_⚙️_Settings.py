import streamlit as st
from datetime import date, timedelta
from garmin_auth import get_garmin_client
from garmin_service import fetch_and_store_garmin_data
from garmin_backfill import run_backfill
from garmin_explore import run_exploration
from garmin_activities import sync_activity_list, sync_activity_details
from db import init_db, get_connection

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
        def on_progress(current_date, status, success_count, error_count, total, error_detail=None):
            done = success_count + error_count
            progress_bar.progress(min(done / total, 1.0))
            if status == "ok":
                status_placeholder.write(f"✅ {current_date.isoformat()} gespeichert")
            elif status == "rate_limited":
                detail = f" ({error_detail})" if error_detail else ""
                status_placeholder.error(
                    f"🛑 Rate-Limit erreicht bei {current_date.isoformat()}{detail} — Backfill abgebrochen, "
                    "um die Sperre nicht zu verlängern."
                )
            else:
                detail = f": {error_detail}" if error_detail else ""
                status_placeholder.warning(f"❌ Fehler bei {current_date.isoformat()}{detail}")

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

st.divider()

st.subheader("🔬 API-Exploration (Tier 1 & 2 Testabruf)")
st.caption(
    "Ruft alle vorgesehenen Endpunkte einmal ab und zeigt die rohen JSON-Antworten an. "
    "Läuft im selben Prozess wie der Einzel-Sync oben, um Token-Probleme separater Prozesse zu vermeiden. "
    "Ergebnisse werden zusätzlich unter garmin_api_exploration/ gespeichert."
)

if st.button("Exploration starten 🧪"):
    explore_progress = st.progress(0)
    explore_status = st.empty()

    try:
        client = get_garmin_client()
    except Exception as e:
        st.error(f"Konnte keine Garmin-Session herstellen: {e}")
        client = None

    if client:
        def on_explore_progress(name, index, total, status, data_or_error):
            explore_progress.progress(min(index / total, 1.0))
            if status == "ok":
                explore_status.write(f"✅ [{index}/{total}] {name}")
            elif status == "rate_limited":
                explore_status.error(
                    f"🛑 Rate-Limit erreicht bei {name} ({index}/{total}) — Test abgebrochen."
                )
            else:
                explore_status.warning(f"❌ [{index}/{total}] {name}: {data_or_error}")

        results = run_exploration(client, on_progress=on_explore_progress)
        explore_progress.progress(1.0)

        success_count = sum(1 for r in results.values() if r["success"])
        error_count = len(results) - success_count
        st.success(f"Fertig! Erfolgreich: {success_count}, Fehler: {error_count}")

        for name, result in results.items():
            with st.expander(f"{'✅' if result['success'] else '❌'} {name}"):
                if result["success"]:
                    st.json(result["data"])
                else:
                    st.error(result["error"])

st.divider()

st.subheader("🏃 Aktivitäten (Läufe, Rad, Schwimmen)")
st.caption(
    "Bewusst getrennt vom automatischen Tages-/Backfill-Sync und nur manuell hier anstoßbar - "
    "eine volle Historie kann mehrere hundert Aktivitäten und pro Aktivität mehrere hundert "
    "Detail-Zeilen (GPS/HF/Leistung pro Sekunde) umfassen."
)

conn = get_connection()
total_activities = conn.execute("SELECT COUNT(*) AS n FROM garmin_activities").fetchone()["n"]
pending_details = conn.execute(
    "SELECT COUNT(*) AS n FROM garmin_activities WHERE has_details_synced = 0"
).fetchone()["n"]
conn.close()

st.write(f"📋 {total_activities} Aktivitäten gespeichert · {pending_details} davon noch ohne Detail-Zeitreihe")

act_col1, act_col2 = st.columns(2)

with act_col1:
    st.markdown("**1. Aktivitätsliste aktualisieren**")
    activity_limit = st.number_input(
        "Wie viele der letzten Aktivitäten laden?", min_value=1, max_value=200, value=20, step=10
    )
    if st.button("Aktivitätsliste laden 📋"):
        with st.spinner(f"Lade die letzten {activity_limit} Aktivitäten..."):
            try:
                client = get_garmin_client()
                count = sync_activity_list(client, limit=activity_limit)
                st.success(f"{count} Aktivitäten gespeichert/aktualisiert.")
                st.rerun()
            except Exception as e:
                st.error(f"Fehler beim Laden der Aktivitätsliste: {e}")

with act_col2:
    st.markdown("**2. Detail-Zeitreihen nachladen**")
    detail_limit = st.number_input(
        "Für wie viele Aktivitäten (ohne Details, neueste zuerst)?",
        min_value=1, max_value=50, value=5, step=1
    )
    if st.button("Detaildaten laden 🔬"):
        detail_progress = st.progress(0)
        detail_status = st.empty()
        try:
            client = get_garmin_client()

            def on_detail_progress(index, total, activity_name, status):
                detail_progress.progress(min(index / total, 1.0))
                if status == "ok":
                    detail_status.write(f"✅ [{index}/{total}] {activity_name}")
                else:
                    detail_status.warning(f"❌ [{index}/{total}] {activity_name} übersprungen")

            synced, errors = sync_activity_details(client, max_count=detail_limit, on_progress=on_detail_progress)
            detail_progress.progress(1.0)
            st.success(f"Fertig! {synced} Aktivitäten mit Details, {errors} Fehler.")
            st.rerun()
        except Exception as e:
            st.error(f"Fehler beim Laden der Detaildaten: {e}")

if total_activities > 0:
    with st.expander("Gespeicherte Aktivitäten anzeigen"):
        conn = get_connection()
        rows = conn.execute(
            "SELECT start_time_local, activity_type, activity_name, "
            "ROUND(distance_meters / 1000.0, 2) AS km, has_details_synced "
            "FROM garmin_activities ORDER BY start_time_local DESC LIMIT 50"
        ).fetchall()
        conn.close()
        st.dataframe(
            [dict(r) for r in rows],
            hide_index=True, use_container_width=True
        )
