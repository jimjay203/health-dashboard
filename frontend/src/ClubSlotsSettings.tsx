import { useEffect, useState, type FormEvent } from "react";
import {
  todayIso,
  fetchClubSlots,
  createClubSlot,
  deleteClubSlot,
  SPORT_TYPES,
  SPORT_TYPE_ICON,
  type ClubSlot,
  type ClubSlotInput,
} from "./api";
import Icon from "./Icon";

const WEEKDAY_LABELS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

function emptyForm(): ClubSlotInput {
  return {
    weekday: 0, sport_type: SPORT_TYPES[0], label: "", valid_from: todayIso(), valid_to: null,
    typical_character: null,
  };
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
      <h3>Vereins-Trainingstermine</h3>
      {error && <p className="error-banner">Fehler: {error}</p>}

      <table className="club-slots-table">
        <thead>
          <tr>
            <th>Wochentag</th>
            <th>Sportart</th>
            <th>Label</th>
            <th>Gültig ab</th>
            <th>Gültig bis</th>
            <th>Charakter</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {slots.map((slot) => (
            <tr key={slot.id}>
              <td>{WEEKDAY_LABELS[slot.weekday]}</td>
              <td>
                <Icon name={SPORT_TYPE_ICON[slot.sport_type]} /> {slot.sport_type}
              </td>
              <td>{slot.label}</td>
              <td>{slot.valid_from}</td>
              <td>{slot.valid_to ?? "unbegrenzt"}</td>
              <td>{slot.typical_character ?? "–"}</td>
              <td>
                <button onClick={() => handleDelete(slot.id)}>Löschen</button>
              </td>
            </tr>
          ))}
          {slots.length === 0 && (
            <tr>
              <td colSpan={7}>Noch keine Vereins-Slots angelegt.</td>
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
          {/* <option> kann nur Text enthalten, kein Icon-Element - hier bewusst nur der Name. */}
          {SPORT_TYPES.map((sportType) => (
            <option key={sportType} value={sportType}>
              {sportType}
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
        <input
          placeholder="Charakter (optional, z. B. 'Bahntraining: meist Intervalle, 400-1000m')"
          value={form.typical_character ?? ""}
          onChange={(e) => setForm({ ...form, typical_character: e.target.value || null })}
        />
        <button type="submit">Slot anlegen</button>
      </form>
    </div>
  );
}

export default ClubSlotsSettings;
