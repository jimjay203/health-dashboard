import { useEffect, useState, type FormEvent } from "react";
import { fetchHabitEntry, saveHabitEntry, type HabitEntry, type HabitEntryInput } from "./api";
import Icon from "./Icon";

function emptyForm(): HabitEntryInput {
  return { caffeine_after_noon: false, last_screen_time: "", last_meal_time: "" };
}

function formFromEntry(entry: HabitEntry): HabitEntryInput {
  return {
    caffeine_after_noon: entry.caffeine_after_noon ?? false,
    last_screen_time: entry.last_screen_time ?? "",
    last_meal_time: entry.last_meal_time ?? "",
  };
}

function summaryText(entry: HabitEntry): string {
  const parts: string[] = [];
  parts.push(entry.caffeine_after_noon ? "Koffein n. 14 Uhr" : "Kein Koffein n. 14 Uhr");
  if (entry.last_screen_time) parts.push(`Letzte Bildschirmnutzung ${entry.last_screen_time}`);
  if (entry.last_meal_time) parts.push(`Letzte Mahlzeit ${entry.last_meal_time}`);
  return parts.join(" · ");
}

// Bewusst als eigenständige Karte (nicht Teil von JournalCard) - der Habit-Tracker deckt Faktoren
// ab, die Garmin nicht liefert (Koffein/letzte Bildschirmnutzung/letzte Mahlzeit), gemischte
// Eingabetypen (Checkbox/Uhrzeit), und soll bei Bedarf um weitere Habits wachsen können, ohne das
// Tagesjournal (subjektives RPE/Muskelkater/Energie) mit fachfremden Feldern zu vermischen.
// Bildschirmzeit war ursprünglich ein Minuten-Slider - eine Uhrzeit ("wann zuletzt?") ist leichter
// zu erinnern als eine geschätzte Dauer, die Minuten bis zur Bettzeit lassen sich serverseitig aus
// sleep_start_local ableiten (siehe backend/routers/sleep.py::_screen_time_gap_minutes).
function HabitTrackerCard({ date }: { date: string }) {
  const [entry, setEntry] = useState<HabitEntry | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<HabitEntryInput>(emptyForm());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchHabitEntry(date)
      .then((e) => {
        setEntry(e);
        const filled = e.caffeine_after_noon !== null;
        setForm(filled ? formFromEntry(e) : emptyForm());
        setEditing(!filled);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [date]);

  const filled = entry?.caffeine_after_noon != null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const saved = await saveHabitEntry(date, form);
      setEntry(saved);
      setEditing(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  function handleEditClick() {
    if (entry) setForm(formFromEntry(entry));
    setEditing(true);
  }

  return (
    <div className="card habit-tracker-card">
      <div className="journal-header">
        <div className="journal-header-title-row">
          <h3>Habit-Tracker</h3>
          {filled && !editing && entry && <p className="journal-summary-line">{summaryText(entry)}</p>}
        </div>
        {!loading &&
          (filled ? (
            <button type="button" className="journal-status-pill journal-status-filled" onClick={handleEditClick}>
              <Icon name="edit" /> Erfasst
            </button>
          ) : (
            <span className="journal-status-pill journal-status-open">
              <Icon name="schedule" /> Offen
            </span>
          ))}
      </div>

      {error && <p className="error-banner">Fehler: {error}</p>}

      {editing && (
        <form className="habit-tracker-form" onSubmit={handleSubmit}>
          <div className="habit-tracker-row">
            <label className="habit-tracker-checkbox">
              <input
                type="checkbox"
                checked={form.caffeine_after_noon}
                onChange={(e) => setForm({ ...form, caffeine_after_noon: e.target.checked })}
              />
              Koffein nach 14 Uhr
            </label>
          </div>
          <div className="habit-tracker-row">
            <label className="habit-tracker-time-field">
              Uhrzeit letzte Bildschirmnutzung
              <input
                type="time"
                value={form.last_screen_time ?? ""}
                onChange={(e) => setForm({ ...form, last_screen_time: e.target.value || null })}
              />
            </label>
            <label className="habit-tracker-time-field">
              Uhrzeit letzte Mahlzeit
              <input
                type="time"
                value={form.last_meal_time ?? ""}
                onChange={(e) => setForm({ ...form, last_meal_time: e.target.value || null })}
              />
            </label>
          </div>
          <div className="journal-form-actions">
            <button type="submit" disabled={saving}>
              {saving ? "Speichert…" : "Habits speichern"}
            </button>
            {filled && (
              <button type="button" onClick={() => setEditing(false)} disabled={saving}>
                Abbrechen
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

export default HabitTrackerCard;
