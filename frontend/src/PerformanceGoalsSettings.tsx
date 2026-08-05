import { useEffect, useState, type FormEvent } from "react";
import {
  fetchPerformanceGoals,
  savePerformanceGoal,
  deletePerformanceGoal,
  type PerformanceGoal,
  type PerformanceGoalInput,
} from "./api";

function emptyForm(): PerformanceGoalInput {
  return { key: "", label: "", target_value: 0, unit: "", derived_from_race_goal_id: null, notes: null };
}

// key ist der Primärschlüssel (siehe performance_goals-Schema) - PUT ist idempotent, ein erneutes
// Anlegen mit demselben key überschreibt die bestehende Zeile (bewusst kein separater Edit-Modus,
// Klick auf "Bearbeiten" befüllt einfach das Formular erneut).
function PerformanceGoalsSettings() {
  const [goals, setGoals] = useState<PerformanceGoal[]>([]);
  const [form, setForm] = useState<PerformanceGoalInput>(emptyForm());
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

  return (
    <div className="card club-slots-settings">
      <h3>Leistungsziele</h3>
      <p className="week-rationale">
        Generische Leistungs-Benchmarks für die Vergleiche auf der Leistungsseite (z. B.
        Marathon-Zielpace, FTP-Ziel in W/kg) - unabhängig von einer konkreten Wettkampfanmeldung.
      </p>
      {error && <p className="error-banner">Fehler: {error}</p>}

      <table className="club-slots-table">
        <thead>
          <tr>
            <th>Key</th>
            <th>Label</th>
            <th>Zielwert</th>
            <th>Einheit</th>
            <th>Notiz</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {goals.map((goal) => (
            <tr key={goal.key}>
              <td>{goal.key}</td>
              <td>{goal.label}</td>
              <td>{goal.target_value}</td>
              <td>{goal.unit}</td>
              <td>{goal.notes ?? "–"}</td>
              <td>
                <button onClick={() => setForm(goal)}>Bearbeiten</button>
                <button onClick={() => handleDelete(goal.key)}>Löschen</button>
              </td>
            </tr>
          ))}
          {goals.length === 0 && (
            <tr>
              <td colSpan={6}>Noch keine Leistungsziele angelegt.</td>
            </tr>
          )}
        </tbody>
      </table>

      <form onSubmit={handleSubmit} className="club-slot-form">
        <input
          placeholder="Key (z. B. marathon_pace)"
          value={form.key}
          onChange={(e) => setForm({ ...form, key: e.target.value })}
          required
        />
        <input
          placeholder="Label (z. B. Marathon-Zielpace)"
          value={form.label}
          onChange={(e) => setForm({ ...form, label: e.target.value })}
          required
        />
        <input
          type="number"
          step="any"
          placeholder="Zielwert"
          value={form.target_value}
          onChange={(e) => setForm({ ...form, target_value: Number(e.target.value) })}
          required
        />
        <input
          placeholder="Einheit (z. B. sec/km, W/kg)"
          value={form.unit}
          onChange={(e) => setForm({ ...form, unit: e.target.value })}
          required
        />
        <input
          placeholder="Notiz (optional)"
          value={form.notes ?? ""}
          onChange={(e) => setForm({ ...form, notes: e.target.value || null })}
        />
        <button type="submit">Ziel speichern</button>
      </form>
    </div>
  );
}

export default PerformanceGoalsSettings;
