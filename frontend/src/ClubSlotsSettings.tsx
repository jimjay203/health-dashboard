import { useEffect, useState, type FormEvent } from "react";
import {
  todayIso,
  fetchClubSlots,
  createClubSlot,
  deleteClubSlot,
  SPORT_TYPES,
  SPORT_TYPE_EMOJI,
  type ClubSlot,
  type ClubSlotInput,
} from "./api";

const WEEKDAY_LABELS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

function emptyForm(): ClubSlotInput {
  return { weekday: 0, sport_type: SPORT_TYPES[0], label: "", valid_from: todayIso(), valid_to: null };
}

function ClubSlotsSettings() {
  const [slots, setSlots] = useState<ClubSlot[]>([]);
  const [form, setForm] = useState<ClubSlotInput>(emptyForm());
  const [error, setError] = useState<string | null>(null);

  function reload() {
    fetchClubSlots()
      .then(setSlots)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(reload, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    try {
      await createClubSlot(form);
      setForm(emptyForm());
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteClubSlot(id);
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="card club-slots-settings">
      <h2>Vereins-Trainingstermine</h2>
      {error && <p className="error-banner">Fehler: {error}</p>}

      <table className="club-slots-table">
        <thead>
          <tr>
            <th>Wochentag</th>
            <th>Sportart</th>
            <th>Label</th>
            <th>Gültig ab</th>
            <th>Gültig bis</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {slots.map((slot) => (
            <tr key={slot.id}>
              <td>{WEEKDAY_LABELS[slot.weekday]}</td>
              <td>
                {SPORT_TYPE_EMOJI[slot.sport_type]} {slot.sport_type}
              </td>
              <td>{slot.label}</td>
              <td>{slot.valid_from}</td>
              <td>{slot.valid_to ?? "unbegrenzt"}</td>
              <td>
                <button onClick={() => handleDelete(slot.id)}>Löschen</button>
              </td>
            </tr>
          ))}
          {slots.length === 0 && (
            <tr>
              <td colSpan={6}>Noch keine Vereins-Slots angelegt.</td>
            </tr>
          )}
        </tbody>
      </table>

      <form onSubmit={handleSubmit} className="club-slot-form">
        <select
          value={form.weekday}
          onChange={(e) => setForm({ ...form, weekday: Number(e.target.value) })}
        >
          {WEEKDAY_LABELS.map((label, i) => (
            <option key={i} value={i}>
              {label}
            </option>
          ))}
        </select>
        <select
          value={form.sport_type}
          onChange={(e) => setForm({ ...form, sport_type: e.target.value as ClubSlotInput["sport_type"] })}
        >
          {SPORT_TYPES.map((sportType) => (
            <option key={sportType} value={sportType}>
              {SPORT_TYPE_EMOJI[sportType]} {sportType}
            </option>
          ))}
        </select>
        <input
          placeholder="Label (z. B. Bahntraining)"
          value={form.label}
          onChange={(e) => setForm({ ...form, label: e.target.value })}
          required
        />
        <input
          type="date"
          value={form.valid_from}
          onChange={(e) => setForm({ ...form, valid_from: e.target.value })}
          required
        />
        <input
          type="date"
          value={form.valid_to ?? ""}
          onChange={(e) => setForm({ ...form, valid_to: e.target.value || null })}
        />
        <button type="submit">Slot anlegen</button>
      </form>
    </div>
  );
}

export default ClubSlotsSettings;
