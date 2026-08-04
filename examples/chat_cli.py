"""
Einfaches Terminal-Testskript für chat_engine.py (kein UI, keine Streamlit-Integration). Eine
input()-Schleife über eine einzelne ChatEngine-Instanz (= eine Konversation).

Ausführen vom Repo-Root aus:
    python3 -m examples.chat_cli

Zum Beenden: "exit" oder Strg+C.
"""
from chat_engine import ChatEngine


def main():
    engine = ChatEngine()
    print("Chat bereit. 'exit' zum Beenden.\n")
    while True:
        try:
            user_text = input("Du: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text.lower() in ("exit", "quit"):
            break

        reply = engine.send_message(user_text)
        print(f"\nAssistent: {reply}\n")


if __name__ == "__main__":
    main()
