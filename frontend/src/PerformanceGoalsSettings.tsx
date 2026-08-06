import { useEffect, useState, type FormEvent } from "react";
import {
  fetchPerformanceGoals,
  savePerformanceGoal,
  deletePerformanceGoal,
  isPaceUnit,
  paceUnitLabel,
  unitDisplayLabel,
  parsePaceToSeconds,
  formatSecondsToPace,
  parseGermanDecimal,
  formatGermanDecimal,
  formatGoalValue,
  type PerformanceGoal,
  type PerformanceGoalInput,
} from "./api";

// Feste Liste statt Freitext (siehe PerformanceView.tsx) - der Key ist der Join-Schlüssel zu den
// Schwellenwert-Karten auf der Leistungsseite, ein Tippfehler dort machte das Ziel bisher
// unbemerkt wirkungslos. Nur ftp_w_per_kg/run_threshold_pace/marathon_pace/halbmarathon_pace haben
// eine echte Garmin-Ist-Wert-Quelle für die Fortschrittsanzeige dort (siehe GOAL_METRIC_SOURCES in
// backend/routers/performance.py) - swim_pace_100m wird hier trotzdem schon als generischer
// Benchmark unterstützt, bekommt auf der Leistungsseite aber vorerst keine Fortschrittsanzeige.
const KNOWN_GOAL_KEYS: { key: string; label: string; unit: string }[] = [
  { key: "ftp_w_per_kg", label: "FTP-Ziel (W/kg)", unit: "W/kg" },
  { key: "run_threshold_pace", label: "Lauf-Schwellenpace", unit: "sec/km" },
  { key: "marathon_pace", label: "Marathon-Zielpace", unit: "sec/km" },
  { key: "halbmarathon_pace", label: "Halbmarathon-Zielpace", unit: "sec/km" },
  // 100m ist die triathlon-/schwimmsport-übliche Bezugsstrecke für Zielpace (analog zu sec/km
  // beim Laufen) - andere Einheiten (z.B. sec/50m) wären unüblich für Freiwasser-/Bahn-Vergleiche.
  { key: "swim_pace_100m", label: "Schwimm-Zielpace (100m)", unit: "sec/100m" },
];

function emptyForm(): PerformanceGoalInput {
  const first = KNOWN_GOAL_KEYS[0];
  return {
    key: first.key, label: first.label, target_value: 0, unit: first.unit,
    derived_from_race_goal_id: null, notes: null, target_date: null, start_date: null,
  };
}

// Auch die Tabellen-Anzeige zeigt Pace-Ziele als mm:ss min/km statt der intern gespeicherten
// rohen Sekundenzahl - sec/km bleibt reines Speicherformat, taucht an der Oberfläche nirgends auf
// (auch nicht im Einheit-Feld des Formulars selbst, siehe unitDisplayLabel-Verwendung unten).
function displayValue(goal: PerformanceGoal): string {
  return formatGoalValue(goal.target_value, goal.unit);
}

// Eigenes Text-Zwischenspeicher-State statt eines direkt an target_value gebundenen <input
// type="number">, da während des Tippens Zwischenzustände wie "4:" oder "3," entstehen, die noch
// keine gültige Zahl ergeben - erst ein vollständiger Treffer wird an das Formular committet. Über
// den formRevision-Key (siehe PerformanceGoalsSettings) wird bei jedem *externen* Laden eines Werts
// (Preset-Wahl, "Bearbeiten", Formular-Reset nach dem Speichern) neu gemountet und damit der
// Text neu aus dem geladenen Wert formatiert - reines Tippen löst kein Remounting aus.
function GoalValueInput({
  unit,
  value,
  onChange,
}: {
  unit: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const pace = isPaceUnit(unit);
  const decimalComma = unit === "W/kg";
  const format = pace ? formatSecondsToPace : decimalComma ? formatGermanDecimal : (v: number) => String(v);
  const parse = pace ? parsePaceToSeconds : decimalComma ? parseGermanDecimal : (t: string) => {
    const n = Number(t.trim());
    return Number.isFinite(n) && t.trim() !== "" ? n : null;
  };
  const placeholder = pace ? `mm:ss ${paceUnitLabel(unit)}` : decimalComma ? "z. B. 3,5" : "Zielwert";

  const [text, setText] = useState(() => format(value));

  function handleChange(newText: string) {
    setText(newText);
    const parsed = parse(newText);
    if (parsed !== null) onChange(parsed);
  }

  return <input value={text} placeholder={placeholder} onChange={(e) => handleChange(e.target.value)} required />;
}

// key ist der Primärschlüssel (siehe performance_goals-Schema) - PUT ist idempotent, ein erneutes
// Anlegen mit demselben key überschreibt die bestehende Zeile (bewusst kein separater Edit-Modus,
// Klick auf "Bearbeiten" befüllt einfach das Formular erneut).
function PerformanceGoalsSettings() {
  const [goals, setGoals] = useState<PerformanceGoal[]>([]);
  const [form, setForm] = useState<PerformanceGoalInput>(emptyForm());
  // Erzwingt einen Remount von GoalValueInput bei jedem externen Laden eines Zielwerts (siehe
  // GoalValueInput-Kommentar) - unabhängig davon, ob sich form.key dabei zufällig ändert oder
  // nicht (z.B. "Bearbeiten" auf dem bereits ausgewählten Preset).
  const [formRevision, setFormRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);

  function reload() {
    fetchPerformanceGoals()
      .then(setGoals)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(reload, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    try {
      await savePerformanceGoal(form);
      setForm(emptyForm());
      setFormRevision((r) => r + 1);
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDelete(key: string) {
    try {
      await deletePerformanceGoal(key);
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function handleEdit(goal: PerformanceGoal) {
    setForm(goal);
    setFormRevision((r) => r + 1);
  }

  return (
    <div className="card club-slots-settings">
      <h3>Leistungsziele</h3>
      <p className="week-rationale">
        Generische Leistungs-Benchmarks für die Vergleiche auf der Leistungsseite (z. B.
        Marathon-Zielpace, FTP-Ziel in W/kg) - unabhängig von einer konkreten Wettkampfanmeldung.
        Startdatum bestimmt den Ausgangswert für die Fortschrittsanzeige auf der Leistungsseite.
      </p>
      {error && <p className="error-banner">Fehler: {error}</p>}

      <form onSubmit={handleSubmit}>
        <table className="club-slots-table">
          <thead>
            <tr>
              <th>Key</th>
              <th>Label</th>
              <th>Zielwert</th>
              <th>Einheit</th>
              <th>Startdatum</th>
              <th>Zieldatum</th>
              <th>Notiz</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {goals.map((goal) => (
              <tr key={goal.key}>
                <td>{goal.key}</td>
                <td>{goal.label}</td>
                <td>{displayValue(goal)}</td>
                <td>{unitDisplayLabel(goal.unit)}</td>
                <td>{goal.start_date ?? "–"}</td>
                <td>{goal.target_date ?? "–"}</td>
                <td>{goal.notes ?? "–"}</td>
                <td>
                  <button type="button" onClick={() => handleEdit(goal)}>
                    Bearbeiten
                  </button>
                  <button type="button" onClick={() => handleDelete(goal.key)}>
                    Löschen
                  </button>
                </td>
              </tr>
            ))}
            {goals.length === 0 && (
              <tr>
                <td colSpan={8}>Noch keine Leistungsziele angelegt.</td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr className="club-slot-form-row">
              <td>
                <select
                  value={form.key}
                  onChange={(e) => {
                    const preset = KNOWN_GOAL_KEYS.find((k) => k.key === e.target.value);
                    setForm({ ...form, key: e.target.value, label: preset?.label ?? form.label, unit: preset?.unit ?? form.unit });
                    setFormRevision((r) => r + 1);
                  }}
                >
                  {KNOWN_GOAL_KEYS.map((preset) => (
                    <option key={preset.key} value={preset.key}>
                      {preset.label}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input
                  placeholder="Label (z. B. Marathon-Zielpace)"
                  value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                  required
                />
              </td>
              <td>
                <GoalValueInput
                  key={formRevision}
                  unit={form.unit}
                  value={form.target_value}
                  onChange={(target_value) => setForm({ ...form, target_value })}
                />
              </td>
              <td>
                {/* Nicht mehr frei editierbar - die Einheit ergibt sich aus dem gewählten Key
                    (siehe KNOWN_GOAL_KEYS), und intern gespeicherte Einheiten wie sec/km sollen
                    an der Oberfläche nie sichtbar sein (siehe unitDisplayLabel). */}
                <input value={unitDisplayLabel(form.unit)} disabled />
              </td>
              <td>
                <input
                  type="date"
                  value={form.start_date ?? ""}
                  onChange={(e) => setForm({ ...form, start_date: e.target.value || null })}
                />
              </td>
              <td>
                <input
                  type="date"
                  value={form.target_date ?? ""}
                  onChange={(e) => setForm({ ...form, target_date: e.target.value || null })}
                />
              </td>
              <td>
                <input
                  placeholder="Notiz (optional)"
                  value={form.notes ?? ""}
                  onChange={(e) => setForm({ ...form, notes: e.target.value || null })}
                />
              </td>
              <td>
                <button type="submit">Ziel speichern</button>
              </td>
            </tr>
          </tfoot>
        </table>
      </form>
    </div>
  );
}

export default PerformanceGoalsSettings;
