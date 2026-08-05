"""
Einmaliger interaktiver Autorisierungs-Flow für die Withings-Integration (siehe withings_auth.py/
withings_service.py). Muss genau einmal ausgeführt werden, bevor fetch_and_store_withings_data()
funktioniert - danach übernimmt withings_auth.py das automatische Token-Refresh.

Ausführen vom Repo-Root aus:
    python3 -m examples.withings_authorize

Ablauf:
1. Skript druckt eine Autorisierungs-URL.
2. Im Browser öffnen, bei Withings einloggen, Zugriff genehmigen.
3. Der Browser landet danach auf der in .env hinterlegten WITHINGS_REDIRECT_URI - die Adresse
   muss dort nicht wirklich etwas Sinnvolles anzeigen, wichtig ist nur die URL in der Adresszeile.
4. Diese komplette URL (oder nur den "code"-Parameter daraus) hier ins Terminal einfügen.
"""
from urllib.parse import urlparse, parse_qs

from withings_auth import get_authorize_url, exchange_code_for_tokens, save_tokens


def _extract_code(user_input):
    user_input = user_input.strip()
    if user_input.startswith("http://") or user_input.startswith("https://"):
        query = parse_qs(urlparse(user_input).query)
        codes = query.get("code")
        if not codes:
            raise ValueError("Konnte keinen 'code'-Parameter in der eingefügten URL finden.")
        return codes[0]
    return user_input


def main():
    print("=== Withings-Autorisierung ===\n")
    print("1. Diese URL im Browser öffnen und Zugriff genehmigen:\n")
    print(get_authorize_url())
    print("\n2. Danach die komplette Redirect-URL (oder nur den 'code'-Wert) hier einfügen.\n")

    user_input = input("Redirect-URL oder Code: ")
    code = _extract_code(user_input)

    tokens = exchange_code_for_tokens(code)
    save_tokens(tokens)
    print("\n✅ Autorisierung erfolgreich. fetch_and_store_withings_data() ist jetzt nutzbar.")


if __name__ == "__main__":
    main()
