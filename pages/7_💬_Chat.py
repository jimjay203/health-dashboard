import json
import streamlit as st
from db import init_db, get_connection
from chat_engine import ChatEngine

st.set_page_config(page_title="Chat", page_icon="💬")
init_db()

st.title("💬 Chat")
st.caption(
    "Schicht 4 (chat_engine.py): Fragen zu deinen Trainingsdaten, Workout-Vorschläge und "
    "-Uploads. Ein Workout-Vorschlag und der tatsächliche Upload sind bewusst auf zwei "
    "getrennte Nachrichten aufgeteilt - erst nach einer neuen Bestätigung wird hochgeladen."
)

if "chat_engine" not in st.session_state:
    st.session_state.chat_engine = ChatEngine()

if st.button("🗑️ Verlauf löschen"):
    conn = get_connection()
    conn.execute("DELETE FROM chat_history")
    conn.commit()
    conn.close()
    st.session_state.chat_engine = ChatEngine()
    st.rerun()

st.divider()

conn = get_connection()
rows = conn.execute("SELECT role, content, tool_calls_json FROM chat_history ORDER BY id").fetchall()
conn.close()

if not rows:
    st.info("Noch keine Nachrichten. Stell unten eine Frage oder bitte um ein Workout.")

for row in rows:
    with st.chat_message("user" if row["role"] == "user" else "assistant"):
        st.markdown(row["content"])
        if row["tool_calls_json"]:
            with st.expander("🔧 Tool-Aufrufe (Debug)"):
                st.json(json.loads(row["tool_calls_json"]))

user_text = st.chat_input("Frag mich etwas zu deinem Training...")
if user_text:
    with st.spinner("Denke nach..."):
        try:
            st.session_state.chat_engine.send_message(user_text)
        except Exception as e:
            st.error(f"Fehler: {e}")
    st.rerun()
