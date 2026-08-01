import streamlit as st

st.set_page_config(
    page_title="Health & Performance Dashboard",
    page_icon="🏃‍♂️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Streamlit Multi-Page Navigation
st.markdown("# 🏃‍♂️ Health & Performance System")
st.sidebar.success("Wähle ein Modul aus der Seitenleiste.")

st.info("Willkommen! Nutze das Menü links, um zwischen den Modulen zu navigieren.")