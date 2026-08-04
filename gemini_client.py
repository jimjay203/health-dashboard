"""
Gemeinsame Gemini-Konfiguration - eine Quelle für API-Key/Modell/Client-Erzeugung statt
mehrerer paralleler Konfigurationen. Aktuell genutzt von insight_memory.py.
"""
import os
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "models/gemini-3.5-flash"


def get_client():
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY fehlt in der .env Datei!")
    return genai.Client(api_key=GEMINI_API_KEY)
