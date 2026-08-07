"""
Withings-OAuth2-Token-Caching. Reine Python-Logik, kein Streamlit-Import (Portabilitäts-Prinzip
wie garmin_auth.py).

Ground-Truth-Hinweis: die Bibliothek withings-api verlangt pydantic<2, was mit google-genai
(pydantic>=2.12.5) kollidiert - ein Testinstall hat das live bestätigt (google.genai wurde dadurch
unimportierbar, sofort wieder rückgängig gemacht). Dieses Modul spricht die Withings-REST-API
deshalb direkt per requests an, kein SDK. Die exakten Endpunkte/Parameter/Antwortformate unten
stammen 1:1 aus dem tatsächlich funktionierenden Quellcode von withings-api
(github.com/vangorra/python_withings_api) - nur ohne die Bibliothek selbst zu installieren:
- Autorisierungs-URL: account.withings.com/oauth2_user/authorize2 (GET, Browser-Redirect)
- Token-Tausch/-Refresh: wbsapi.withings.net/v2/oauth2 (POST, action=requesttoken)
- Antwort-Hülle aller Endpunkte: {"status": 0, "body": {...}} - status 0 = Erfolg
"""
import json
import os
import secrets
import time
from urllib.parse import urlencode

import requests

WITHINGS_CLIENT_ID = os.getenv("WITHINGS_CLIENT_ID")
WITHINGS_CLIENT_SECRET = os.getenv("WITHINGS_CLIENT_SECRET")
WITHINGS_REDIRECT_URI = os.getenv("WITHINGS_REDIRECT_URI")

AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"

TOKEN_DIR = os.path.expanduser("~/.withings_api")
TOKEN_PATH = os.path.join(TOKEN_DIR, "credentials.json")

# Access-Token gilt laut Withings typischerweise 3h - Refresh etwas vor dem exakten
# Ablaufzeitpunkt anstoßen, um kein Rennen mit einem gerade noch gültigen, gleich abgelaufenen
# Token einzugehen.
REFRESH_MARGIN_SECONDS = 300


def get_authorize_url():
    """Baut die Autorisierungs-URL für den einmaligen interaktiven Browser-Schritt (siehe
    examples/withings_authorize.py). state wird nur generiert, nicht verifiziert (Single-User-
    CLI-Skript, kein Server, der einen Callback empfängt)."""
    if not WITHINGS_CLIENT_ID or not WITHINGS_REDIRECT_URI:
        raise ValueError("WITHINGS_CLIENT_ID und WITHINGS_REDIRECT_URI müssen in .env gesetzt sein.")
    params = {
        "response_type": "code",
        "client_id": WITHINGS_CLIENT_ID,
        "redirect_uri": WITHINGS_REDIRECT_URI,
        "scope": "user.metrics",
        "state": secrets.token_urlsafe(16),
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _request_token(**body_extra):
    body = {
        "action": "requesttoken",
        "client_id": WITHINGS_CLIENT_ID,
        "client_secret": WITHINGS_CLIENT_SECRET,
        **body_extra,
    }
    response = requests.post(TOKEN_URL, data=body, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != 0:
        raise RuntimeError(f"Withings-Token-Anfrage fehlgeschlagen (status={payload.get('status')}): {payload}")

    token_body = payload["body"]
    return {
        "access_token": token_body["access_token"],
        "refresh_token": token_body["refresh_token"],
        "token_type": token_body["token_type"],
        "expires_in": token_body["expires_in"],
        "userid": token_body["userid"],
        "created_at": int(time.time()),
    }


def exchange_code_for_tokens(code):
    """Erst-Autorisierung: tauscht den Code aus der Redirect-URL gegen Tokens - siehe
    examples/withings_authorize.py. Gibt das Tokens-Dict zurück, speichert es NICHT selbst
    (Aufrufer entscheidet, das CLI-Skript ruft danach save_tokens())."""
    if not WITHINGS_CLIENT_ID or not WITHINGS_CLIENT_SECRET or not WITHINGS_REDIRECT_URI:
        raise ValueError(
            "WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET und WITHINGS_REDIRECT_URI müssen in .env "
            "gesetzt sein."
        )
    return _request_token(grant_type="authorization_code", code=code, redirect_uri=WITHINGS_REDIRECT_URI)


def _refresh_access_token(tokens):
    """Withings gibt bei jedem Refresh einen NEUEN refresh_token mit zurück - der alte wird
    ungültig, daher muss das Ergebnis hier immer vollständig neu gespeichert werden (siehe
    get_withings_tokens())."""
    return _request_token(grant_type="refresh_token", refresh_token=tokens["refresh_token"])


def save_tokens(tokens):
    os.makedirs(TOKEN_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        json.dump(tokens, f)
    print(f"💾 Withings-Tokens gespeichert unter: {TOKEN_PATH}")


def _load_tokens():
    if not os.path.exists(TOKEN_PATH):
        return None
    with open(TOKEN_PATH) as f:
        return json.load(f)


def get_token_status():
    """Liest den gespeicherten Token ohne Refresh-Seiteneffekt (im Gegensatz zu
    get_withings_tokens()) - für reine Status-Anzeigen (Einstellungen-Seite), die keinen
    echten API-Call/Refresh auslösen sollen. Gibt None zurück, falls noch nie autorisiert wurde."""
    tokens = _load_tokens()
    if tokens is None:
        return None
    return {
        "created_at": tokens["created_at"],
        "expires_at": tokens["created_at"] + tokens["expires_in"],
    }


def get_withings_tokens():
    """Lädt gespeicherte Tokens, refresht bei Bedarf automatisch (Ergebnis wird sofort persistiert)
    und gibt gültige Tokens zurück."""
    tokens = _load_tokens()
    if tokens is None:
        raise ValueError(
            "Kein Withings-Token gefunden. Bitte einmalig examples/withings_authorize.py "
            "ausführen, um die Autorisierung durchzuführen."
        )

    expires_at = tokens["created_at"] + tokens["expires_in"]
    if time.time() >= expires_at - REFRESH_MARGIN_SECONDS:
        tokens = _refresh_access_token(tokens)
        save_tokens(tokens)

    return tokens
