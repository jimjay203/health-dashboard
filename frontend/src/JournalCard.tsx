import { useEffect, useState, type FormEvent } from "react";
import { fetchDailyJournal, saveDailyJournal, type DailyJournal, type DailyJournalInput } from "./api";
import Icon from "./Icon";

const RPE_HELP = "1 = Völlig entspannt, 10 = Maximale Erschöpfung";
const SORENESS_HELP = "1 = Keinerlei Muskelkater, 5 = Extremer Muskelkater";
const ENERGY_HELP = "1 = Sehr müde/schlapp, 5 = Voller Energie";

function emptyForm(): DailyJournalInput {
  return { rpe_score: 5, muscle_soreness: 3, energy_level: 3, notes: "" };
}

function formFromJournal(journal: DailyJournal): DailyJournalInput {
  return {
    rpe_score: journal.rpe_score ?? 5,
    muscle_soreness: journal.muscle_soreness ?? 3,
    energy_level: journal.energy_level ?? 3,
    notes: journal.notes ?? "",
  };
}

function SliderField({
  label,
  help,
  min,
  max,
  value,
  onChange,
}: {
  label: string;
  help: string;
  min: number;
  max: number;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="journal-slider-field" title={help}>
      <span className="journal-slider-label">
        {label} <span className="journal-slider-value">{value}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

// Ganz oben auf der Heute-Seite (siehe TodayView.tsx) - morgens als erstes das Befinden erfassen,
// bevor die KI-Empfehlung angeschaut wird (dasselbe Prinzip wie in der früheren
// pages/1_🏠_Home.py-Reihenfolge). Zeigt bei bereits erfasstem Journal eine kompakte
// Ergebnis-Ansicht statt dauerhaft das Formular offen zu halten (spart Platz), "Bearbeiten"
// öffnet es wieder mit den gespeicherten Werten vorbefüllt.
function JournalCard({ date }: { date: string }) {
  const [journal, setJournal] = useState<DailyJournal | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<DailyJournalInput>(emptyForm());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchDailyJournal(date)
      .then((j) => {
        setJournal(j);
        const filled = j.rpe_score !== null;
        setForm(filled ? formFromJournal(j) : emptyForm());
        setEditing(!filled);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [date]);

  const filled = journal?.rpe_score != null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setWarning(null);
    try {
      const result = await saveDailyJournal(date, form);
      setJournal(result.journal);
      setWarning(result.insight_memory_warning);
      setEditing(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  function handleEditClick() {
    if (journal) setForm(formFromJournal(journal));
    setEditing(true);
  }

  return (
    <div className="card journal-card">
      <div className="journal-header">
        <h3>Subjektives Tagesjournal &amp; Befinden</h3>
        {!loading && (
          <span className={`journal-status-pill${filled ? " journal-status-filled" : " journal-status-open"}`}>
            <Icon name={filled ? "check_circle" : "schedule"} /> {filled ? "Erfasst" : "Offen"}
          </span>
        )}
      </div>

      {error && <p className="error-banner">Fehler: {error}</p>}
      {warning && <p className="journal-warning">{warning}</p>}

      {filled && !editing && journal && (
        <>
          <div className="journal-summary-row">
            <div className="journal-summary-metric">
              <div className="journal-summary-metric-value">{journal.rpe_score}/10</div>
              <div className="journal-summary-metric-label">Belastung (RPE)</div>
            </div>
            <div className="journal-summary-metric">
              <div className="journal-summary-metric-value">{journal.muscle_soreness}/5</div>
              <div className="journal-summary-metric-label">Muskelkater / Frische</div>
            </div>
            <div className="journal-summary-metric">
              <div className="journal-summary-metric-value">{journal.energy_level}/5</div>
              <div className="journal-summary-metric-label">Energielevel</div>
            </div>
          </div>
          {journal.notes && <p className="journal-notes">{journal.notes}</p>}
          <button type="button" className="journal-edit-toggle" onClick={handleEditClick}>
            <Icon name="edit" /> Bearbeiten
          </button>
        </>
      )}

      {editing && (
        <form className="journal-form" onSubmit={handleSubmit}>
          <div className="journal-slider-row">
            <SliderField
              label="Belastungsempfinden (RPE)"
              help={RPE_HELP}
              min={1}
              max={10}
              value={form.rpe_score}
              onChange={(v) => setForm({ ...form, rpe_score: v })}
            />
            <SliderField
              label="Muskelkater / Frische"
              help={SORENESS_HELP}
              min={1}
              max={5}
              value={form.muscle_soreness}
              onChange={(v) => setForm({ ...form, muscle_soreness: v })}
            />
            <SliderField
              label="Energielevel"
              help={ENERGY_HELP}
              min={1}
              max={5}
              value={form.energy_level}
              onChange={(v) => setForm({ ...form, energy_level: v })}
            />
          </div>
          <textarea
            className="journal-textarea"
            placeholder="Tagesnotizen & Besonderheiten, z. B. Spätes Essen, Stress bei der Arbeit, gute Beine beim Laufen..."
            value={form.notes ?? ""}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
          <div className="journal-form-actions">
            <button type="submit" disabled={saving}>
              {saving ? "Speichert…" : "Journal-Eintrag speichern"}
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

export default JournalCard;
