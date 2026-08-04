"""
Schicht 4 der KI-Chat-Vorbereitung: der eigentliche Chat auf Basis von Schicht 1-3
(daily_summary/weekly_summary/insight_memory) sowie workout_builder.py. Reine Python-Logik,
kein Streamlit-Import (Portabilitäts-Prinzip, analog zu allen anderen Modulen dieses Repos).

Turn-Trennung propose_workout/confirm_and_upload_workout: siehe ChatEngine-Docstring unten -
zwei Ebenen (System-Prompt UND strukturelle Sperre über _turn_counter), nicht nur Prompt-Text.

Ground-Truth-Hinweis (live gegen die echte Gemini-API verifiziert): types.Tool(function_
declarations=[...]) mit reinen Schema-Objekten (kein echter Python-Callable) löst KEINE
automatische SDK-seitige Funktionsausführung/-verkettung aus, auch nicht bei aggressiven Prompts
("mach beides in einem Schritt") - trotzdem keine alleinige Absicherung, siehe ChatEngine.
"""
import json
import re
import sqlite3
import time
import uuid
from datetime import date

from google.genai import types
from db import get_connection, DB_PATH
from gemini_client import get_client, MODEL_NAME
from garmin_auth import get_garmin_client
from workout_builder import build_interval_running_workout, upload_workout

# --- Teil 1: run_readonly_query ---
TABLE_DESCRIPTIONS = {
    "daily_summary": "Regelbasierte Tageskennzahlen (PK date): HRV/Schlaf/Ruhepuls vs. Baseline, "
                      "Trainingslast, CTL/ATL/TSB, Übertrainings-Flag, Journal-Werte.",
    "weekly_summary": "Regelbasierte Wochenkennzahlen (PK week_id, z.B. '2026-W32'): Volumen nach "
                       "Sportart, Zonen-Verteilung, Trainingsphase, Renn-Countdown.",
    "insight_memory_compressed": "Vom Nutzer selbst eingetragene Zusatzinfos, verdichtet "
                                  "(aktuellste Version = MAX(version)).",
    "garmin_activities": "Einzelne Aktivitäten (Läufe/Rad/Schwimmen, PK activity_id) mit "
                          "Distanz/Dauer/HF/Leistung - raw_json wird nie ausgegeben.",
    "training_zones_running": "Friel-Lauf-Trainingszonen (HF+Pace) je Zone, mehrere Zeilen je "
                               "date - aktuell = neuestes date.",
    "training_zones_cycling_hr": "Friel-Rad-HF-Zonen je Zone, mehrere Zeilen je date - aktuell = "
                                  "neuestes date.",
    "training_zones_cycling_power": "Friel-Rad-Leistungszonen (FTP-basiert) je Zone, mehrere "
                                     "Zeilen je date - aktuell = neuestes date.",
}
ALLOWED_TABLES = set(TABLE_DESCRIPTIONS)
RAW_JSON_COLUMNS = {"raw_json"}

MAX_ROWS = 100
QUERY_TIMEOUT_SECONDS = 3.0
MAX_TOOL_ROUNDS = 8  # legitime mehrstufige Datenrecherche (mehrere run_readonly_query-Aufrufe
                      # nacheinander) braucht öfter mehr als 5 Runden, siehe Testlauf
MAX_HISTORY_MESSAGES = 40


def _extract_table_names(sql):
    return set(re.findall(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.IGNORECASE))


def _format_rows(columns, rows):
    lines = [" | ".join(columns)]
    for row in rows:
        values = []
        for col in columns:
            val = row[col]
            if col in RAW_JSON_COLUMNS and val is not None:
                values.append(f"[ausgeblendet, {len(str(val))} Zeichen]")
            else:
                values.append(str(val) if val is not None else "NULL")
        lines.append(" | ".join(values))
    return "\n".join(lines)


def run_readonly_query(sql):
    """Führt eine SELECT-only-Query gegen eine feste Tabellen-Whitelist aus (separate Read-Only-
    Connection, Row-Limit, Timeout). Gibt bei JEDEM Fehler einen verständlichen String zurück
    statt zu crashen - wird als Gemini-Tool aufgerufen, ein Crash würde den ganzen Chat-Turn reißen."""
    if not isinstance(sql, str) or not sql.strip():
        return "Fehler: Keine SQL-Abfrage übergeben."
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT"):
        return "Fehler: Nur SELECT-Abfragen sind erlaubt."
    if ";" in stripped:
        return "Fehler: Mehrere Anweisungen (Semikolon) sind nicht erlaubt."

    referenced = _extract_table_names(stripped)
    if not referenced:
        return "Fehler: Konnte keine Tabelle in der Abfrage erkennen."
    disallowed = referenced - ALLOWED_TABLES
    if disallowed:
        return (f"Fehler: Zugriff auf nicht erlaubte Tabelle(n) {sorted(disallowed)}. "
                f"Erlaubt sind nur: {sorted(ALLOWED_TABLES)}.")

    wrapped_sql = f"SELECT * FROM ({stripped}) LIMIT {MAX_ROWS}"
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
        cursor = conn.execute(wrapped_sql)
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description] if cursor.description else []
        conn.close()
    except sqlite3.OperationalError as e:
        return f"Fehler bei der Abfrage: {e}"
    except Exception as e:
        return f"Unerwarteter Fehler bei der Abfrage: {e}"

    if not rows:
        return "Keine Ergebnisse."
    return _format_rows(columns, rows)


# --- Gemini-Tool-Deklarationen (reine Schema-Objekte, siehe Ground-Truth-Hinweis oben) ---
RUN_QUERY_DECL = types.FunctionDeclaration(
    name="run_readonly_query",
    description="Führt eine einzelne SELECT-SQL-Abfrage gegen eine feste Tabellen-Whitelist aus. "
                "Nutze das für alles, was über die im Kontext bereits mitgelieferten Basisdaten "
                "hinausgeht (z.B. mehrere Wochen Verlauf, einzelne Aktivitäten, Trainingszonen).",
    parameters={
        "type": "OBJECT",
        "properties": {"sql": {"type": "STRING",
                               "description": "Eine einzelne SELECT-Anweisung, OHNE abschließendes Semikolon."}},
        "required": ["sql"],
    },
)

PROPOSE_WORKOUT_DECL = types.FunctionDeclaration(
    name="propose_workout",
    description="Schlägt ein strukturiertes Intervall-Lauf-Workout vor (NUR Vorschau, lädt NICHT "
                "hoch). Genau eines von interval_distance_m/interval_duration_sec und genau eines "
                "von interval_target_pace_min_per_km/interval_target_zone angeben, ebenso genau "
                "eines von recovery_duration_sec/recovery_distance_m. Zonen sind Strings wie "
                "'1','2','3','4','5a','5b','5c'.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING"},
            "warmup_minutes": {"type": "INTEGER"},
            "warmup_zone": {"type": "STRING"},
            "interval_count": {"type": "INTEGER"},
            "interval_distance_m": {"type": "NUMBER"},
            "interval_duration_sec": {"type": "NUMBER"},
            "interval_target_pace_min_per_km": {"type": "NUMBER"},
            "interval_target_zone": {"type": "STRING"},
            "recovery_duration_sec": {"type": "NUMBER"},
            "recovery_distance_m": {"type": "NUMBER"},
            "cooldown_minutes": {"type": "INTEGER"},
            "cooldown_zone": {"type": "STRING"},
        },
        "required": ["name", "warmup_minutes", "warmup_zone", "interval_count",
                      "cooldown_minutes", "cooldown_zone"],
    },
)

CONFIRM_UPLOAD_DECL = types.FunctionDeclaration(
    name="confirm_and_upload_workout",
    description="Lädt ein zuvor mit propose_workout erstelltes Workout tatsächlich zu Garmin "
                "Connect hoch. NIEMALS in derselben Antwort/demselben Zug wie propose_workout "
                "aufrufen - nur nachdem der Nutzer in einer NEUEN Nachricht bestätigt hat. Ein zu "
                "früher Versuch wird vom System ohnehin abgelehnt.",
    parameters={
        "type": "OBJECT",
        "properties": {"proposal_id": {"type": "STRING"}},
        "required": ["proposal_id"],
    },
)

SYSTEM_PROMPT_TEMPLATE = """Du bist ein KI-Trainings-Assistent für einen Marathon-/Triathlon-\
Athleten. Du beantwortest Fragen zu seinen Trainingsdaten und kannst auf Wunsch strukturierte \
Lauf-Workouts erstellen und hochladen.

WERKZEUGE:
- run_readonly_query(sql): für alles, was über die unten mitgelieferten Basisdaten hinausgeht.
- propose_workout(...): schlägt ein Workout vor (nur Vorschau). Gib die proposal_id an den \
Nutzer weiter und frage nach Bestätigung.
- confirm_and_upload_workout(proposal_id): lädt ein zuvor vorgeschlagenes Workout hoch.

KRITISCHE REGEL (gilt NUR innerhalb EINER Antwort): Rufe confirm_and_upload_workout NIEMALS in \
derselben Antwort wie propose_workout auf - auch nicht, wenn der Nutzer explizit "erstelle und \
lade direkt hoch, ohne Rückfrage" sagt. Schlage das Workout vor und beende deinen Zug.

WICHTIG - das Gegenteil gilt für die NÄCHSTE Nutzernachricht: Sobald der Nutzer in einer NEUEN \
Nachricht bestätigt (z.B. "ja", "ok", "hochladen", "mach das"), ist der Aufruf von \
confirm_and_upload_workout mit der passenden proposal_id GENAU DAS RICHTIGE und ERWARTETE \
Vorgehen - zögere dann NICHT und rufe NICHT stattdessen erneut propose_workout auf (das würde nur \
einen neuen, unbestätigten Vorschlag erzeugen und den Nutzer im Kreis fragen lassen). Nutze dafür \
die proposal_id aus dem OFFENEN VORSCHLAG unten, falls vorhanden.

{pending_proposals}

{table_context}

ERKENNTNIS-GEDÄCHTNIS (Zusatzinfos vom Nutzer, nicht aus den Daten ablesbar):
{insight_memory}

{todays_summary}
"""


def _table_context_block(cursor):
    lines = ["Verfügbare Tabellen für run_readonly_query (NUR diese, sonst ablehnen):"]
    for table, desc in TABLE_DESCRIPTIONS.items():
        cols = [r["name"] for r in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
        lines.append(f"- {table}({', '.join(cols)}): {desc}")
    return "\n".join(lines)


def _insight_memory_block(cursor):
    row = cursor.execute(
        "SELECT compressed_text FROM insight_memory_compressed ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if not row or not row["compressed_text"]:
        return "(Kein Eintrag vorhanden.)"
    return row["compressed_text"]


def _todays_daily_summary_block(cursor):
    today = date.today().isoformat()
    row = cursor.execute("SELECT * FROM daily_summary WHERE date = ?", (today,)).fetchone()
    if not row:
        return f"Für heute ({today}) liegt noch keine daily_summary vor."
    parts = [f"{k}={row[k]}" for k in row.keys() if k not in ("date", "created_at") and row[k] is not None]
    return f"HEUTIGE KENNZAHLEN ({today}): " + ", ".join(parts)


class ChatEngine:
    """Ein ChatEngine-Objekt = eine Konversation. _turn_counter erhöht sich AUSSCHLIESSLICH in
    send_message() (also nur bei einer echten neuen eingehenden Nutzernachricht, nie innerhalb der
    internen Function-Calling-Schleife eines einzelnen send_message()-Aufrufs). Jeder Vorschlag aus
    propose_workout trägt den turn_id-Stempel seiner Entstehung; confirm_and_upload_workout prüft
    vor jeder Ausführung, ob der aktuelle turn_id vom Stempel abweicht - sonst Ablehnung. Das ist
    die eigentliche Absicherung gegen Verkettung im selben Zug, nicht der System-Prompt-Text."""

    def __init__(self):
        self._turn_counter = 0
        self._pending_proposals = {}  # proposal_id -> {"workout": RunningWorkout, "turn_id": int, "summary": str}

    def _pending_proposals_block(self, current_turn_id):
        """Wird bei JEDEM send_message() frisch aus dem tatsächlichen Objektzustand gebaut (nicht
        aus der Konversationshistorie abgeleitet) - damit das Modell die korrekte proposal_id auch
        dann sicher kennt, wenn es sie aus dem bisherigen Gesprächstext nicht zuverlässig
        herausliest. Alle zu diesem Zeitpunkt offenen Vorschläge stammen zwangsläufig aus früheren
        Zügen, da der aktuelle Zug gerade erst beginnt."""
        if not self._pending_proposals:
            return "OFFENE VORSCHLÄGE: keine."
        lines = ["OFFENE VORSCHLÄGE (noch nicht hochgeladen):"]
        for proposal_id, proposal in self._pending_proposals.items():
            first_line = proposal["summary"].splitlines()[0]
            lines.append(f"- proposal_id={proposal_id}: {first_line}")
        return "\n".join(lines)

    def send_message(self, user_text):
        self._turn_counter += 1
        turn_id = self._turn_counter

        conn = get_connection()
        cursor = conn.cursor()
        system_instruction = SYSTEM_PROMPT_TEMPLATE.format(
            pending_proposals=self._pending_proposals_block(turn_id),
            table_context=_table_context_block(cursor),
            insight_memory=_insight_memory_block(cursor),
            todays_summary=_todays_daily_summary_block(cursor),
        )
        contents = self._load_history_contents(cursor)
        conn.close()
        contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

        self._save_message("user", user_text)

        tools = [types.Tool(function_declarations=[RUN_QUERY_DECL, PROPOSE_WORKOUT_DECL, CONFIRM_UPLOAD_DECL])]
        config = types.GenerateContentConfig(system_instruction=system_instruction, tools=tools)
        client = get_client()

        tool_call_log = []
        final_text = "Entschuldigung, deine Anfrage war zu komplex - bitte einfacher formulieren."

        for _ in range(MAX_TOOL_ROUNDS):
            response = client.models.generate_content(model=MODEL_NAME, contents=contents, config=config)
            if not response.candidates:
                final_text = "Keine Antwort erhalten (evtl. durch Sicherheitsfilter blockiert)."
                break

            candidate_content = response.candidates[0].content
            function_calls = [p.function_call for p in candidate_content.parts if p.function_call]

            if not function_calls:
                final_text = response.text or final_text
                break

            contents.append(candidate_content)
            response_parts = []
            for fc in function_calls:
                result_str = self._dispatch_tool(fc.name, dict(fc.args), turn_id)
                tool_call_log.append({"name": fc.name, "args": dict(fc.args), "result": result_str})
                response_parts.append(types.Part.from_function_response(name=fc.name, response={"result": result_str}))
            contents.append(types.Content(role="user", parts=response_parts))

        self._save_message("assistant", final_text, tool_call_log)
        return final_text

    def _dispatch_tool(self, name, args, turn_id):
        try:
            if name == "run_readonly_query":
                return run_readonly_query(args.get("sql", ""))
            if name == "propose_workout":
                return self._tool_propose_workout(args, turn_id)
            if name == "confirm_and_upload_workout":
                return self._tool_confirm_and_upload_workout(args, turn_id)
            return f"Unbekanntes Werkzeug: {name}"
        except Exception as e:
            return f"Fehler bei der Ausführung von {name}: {e}"

    def _tool_propose_workout(self, args, turn_id):
        try:
            workout = build_interval_running_workout(
                name=args["name"],
                warmup_minutes=args["warmup_minutes"], warmup_zone=args["warmup_zone"],
                interval_count=args["interval_count"],
                interval_distance_m=args.get("interval_distance_m"),
                interval_duration_sec=args.get("interval_duration_sec"),
                interval_target_pace_min_per_km=args.get("interval_target_pace_min_per_km"),
                interval_target_zone=args.get("interval_target_zone"),
                recovery_duration_sec=args.get("recovery_duration_sec"),
                recovery_distance_m=args.get("recovery_distance_m"),
                cooldown_minutes=args["cooldown_minutes"], cooldown_zone=args["cooldown_zone"],
            )
        except ValueError as e:
            return f"Konnte das Workout nicht erstellen: {e}"
        except KeyError as e:
            return f"Fehlender Parameter: {e}"

        proposal_id = uuid.uuid4().hex[:8]
        summary = self._describe_workout(workout)
        self._pending_proposals[proposal_id] = {"workout": workout, "turn_id": turn_id, "summary": summary}
        return f"Vorschlag erstellt (proposal_id={proposal_id}):\n{summary}"

    def _tool_confirm_and_upload_workout(self, args, turn_id):
        proposal_id = args.get("proposal_id")
        proposal = self._pending_proposals.get(proposal_id)

        note = ""
        if not proposal:
            # Modell hat eine falsche/veraltete ID genannt (oder keine) - Fallback: gibt es genau
            # EINEN Vorschlag aus einem früheren Zug, nehmen wir den statt hart abzulehnen (das
            # führt sonst genau zu dem beobachteten "fragt mehrfach nach"-Verhalten).
            candidates = [(pid, p) for pid, p in self._pending_proposals.items() if p["turn_id"] != turn_id]
            if len(candidates) == 1:
                proposal_id, proposal = candidates[0]
                note = f"(Hinweis: ID '{args.get('proposal_id')}' unbekannt, stattdessen den einzigen offenen Vorschlag '{proposal_id}' verwendet.)\n"
            else:
                pending_ids = [pid for pid, p in self._pending_proposals.items() if p["turn_id"] != turn_id]
                return (f"Kein Vorschlag mit ID '{args.get('proposal_id')}' gefunden. "
                        f"Offene Vorschläge: {pending_ids or 'keine'}.")

        if proposal["turn_id"] == turn_id:
            return ("Abgelehnt: confirm_and_upload_workout darf nicht im selben Zug wie "
                    "propose_workout aufgerufen werden. Bitte erst eine neue Nachricht mit der "
                    "Bestätigung des Nutzers abwarten.")

        del self._pending_proposals[proposal_id]
        try:
            client = get_garmin_client()
            result = upload_workout(proposal["workout"], client)
        except Exception as e:
            return f"{note}Fehler beim Hochladen: {e}"

        if result["success"]:
            return f"{note}Erfolgreich zu Garmin Connect hochgeladen (workout_id={result['workout_id']})."
        return f"{note}Upload fehlgeschlagen: {result['error']}"

    @staticmethod
    def _describe_workout(workout):
        lines = [
            f"Name: {workout.workoutName}",
            f"Geschätzte Dauer: {workout.estimatedDurationInSecs / 60:.1f} Min.",
        ]
        for step in workout.workoutSegments[0].workoutSteps:
            if step.type == "RepeatGroupDTO":
                lines.append(f"{step.numberOfIterations}x Wiederholung:")
                for child in step.workoutSteps:
                    lines.append(f"  - {ChatEngine._describe_step(child)}")
            else:
                lines.append(ChatEngine._describe_step(step))
        return "\n".join(lines)

    @staticmethod
    def _describe_step(step):
        cond = step.endCondition["conditionTypeKey"]
        val = step.endConditionValue
        cond_txt = f"{val:.0f}m" if cond == "distance" else f"{val:.0f}s"
        target_txt = ""
        if step.targetType and step.targetType.get("workoutTargetTypeKey") == "pace.zone":
            faster_m_s, slower_m_s = step.targetValueOne, step.targetValueTwo
            target_txt = f" @ {1000 / faster_m_s / 60:.2f}-{1000 / slower_m_s / 60:.2f} min/km"
        desc = getattr(step, "description", None) or step.stepType["stepTypeKey"]
        return f"{desc}: {cond_txt}{target_txt}"

    def _load_history_contents(self, cursor):
        rows = cursor.execute(
            "SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (MAX_HISTORY_MESSAGES,)
        ).fetchall()
        contents = []
        for row in reversed(rows):
            role = "model" if row["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=row["content"])]))
        return contents

    @staticmethod
    def _save_message(role, content, tool_calls=None):
        conn = get_connection()
        conn.execute(
            "INSERT INTO chat_history (role, content, tool_calls_json) VALUES (?, ?, ?)",
            (role, content, json.dumps(tool_calls) if tool_calls else None)
        )
        conn.commit()
        conn.close()
