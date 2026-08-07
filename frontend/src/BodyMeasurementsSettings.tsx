import { useEffect, useState, type FormEvent } from "react";
import { fetchBodySettings, saveBodySettings, resetHeightToGarmin, type BodySettings } from "./api";

// Körpergröße für den FFMI + Körperfett-Zielwert für den Zielwert-Indikator auf der Körper-Seite
// (siehe BodyView.tsx). Körpergröße wird täglich automatisch aus Garmins get_user_profile()
// übernommen (siehe garmin_service.py::_fetch_body_composition), hier manuell überschreibbar (z. B.
// falls Garmins Wert falsch/veraltet ist) - ein überschriebener Wert wird von künftigen
// Garmin-Syncs nicht mehr angetastet, bis er unten zurückgesetzt wird. Der Körperfett-Zielwert hat
// keine Garmin-Quelle, ist rein manuell.
function BodyMeasurementsSettings() {
  const [settings, setSettings] = useState<BodySettings | null>(null);
  const [heightInput, setHeightInput] = useState("");
  const [targetBodyFatInput, setTargetBodyFatInput] = useState("");
  const [savingHeight, setSavingHeight] = useState(false);
  const [savingTargetBodyFat, setSavingTargetBodyFat] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reload() {
    fetchBodySettings()
      .then((s) => {
        setSettings(s);
        setHeightInput(s.height_cm != null ? String(s.height_cm) : "");
        setTargetBodyFatInput(s.target_body_fat_pct != null ? String(s.target_body_fat_pct) : "");
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(reload, []);

  async function handleSubmitHeight(e: FormEvent) {
    e.preventDefault();
    const value = Number(heightInput.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) return;
    setSavingHeight(true);
    setError(null);
    try {
      await saveBodySettings({ height_cm: value });
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingHeight(false);
    }
  }

  async function handleReset() {
    setSavingHeight(true);
    setError(null);
    try {
      await resetHeightToGarmin();
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingHeight(false);
    }
  }

  async function handleSubmitTargetBodyFat(e: FormEvent) {
    e.preventDefault();
    const value = Number(targetBodyFatInput.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) return;
    setSavingTargetBodyFat(true);
    setError(null);
    try {
      await saveBodySettings({ target_body_fat_pct: value });
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingTargetBodyFat(false);
    }
  }

  return (
    <div className="card club-slots-settings">
      <h3>Körpermaße</h3>
      <p className="week-rationale">
        Körpergröße für den FFMI auf der Körper-Seite - wird täglich automatisch aus Garmins Profil
        übernommen, hier bei Bedarf überschreibbar. Ein manueller Wert bleibt bestehen, bis er
        unten zurückgesetzt wird.
      </p>
      {error && <p className="error-banner">Fehler: {error}</p>}

      <form className="body-height-form" onSubmit={handleSubmitHeight}>
        <label>
          Körpergröße
          <input
            type="number"
            step="0.1"
            min="0"
            placeholder="z. B. 180"
            value={heightInput}
            onChange={(e) => setHeightInput(e.target.value)}
          />
          cm
        </label>
        <button type="submit" disabled={savingHeight}>
          {savingHeight ? "Speichert…" : "Speichern"}
        </button>
        {settings?.height_source === "manual" && (
          <button type="button" onClick={handleReset} disabled={savingHeight}>
            Zurücksetzen auf Garmin-Wert
          </button>
        )}
      </form>

      {settings?.height_cm != null && (
        <p className="week-rationale">
          Aktuell: {settings.height_cm} cm ({settings.height_source === "manual" ? "manuell überschrieben" : "automatisch von Garmin"})
        </p>
      )}

      <form className="body-height-form" onSubmit={handleSubmitTargetBodyFat}>
        <label>
          Körperfett-Zielwert
          <input
            type="number"
            step="0.1"
            min="0"
            max="100"
            placeholder="z. B. 20"
            value={targetBodyFatInput}
            onChange={(e) => setTargetBodyFatInput(e.target.value)}
          />
          %
        </label>
        <button type="submit" disabled={savingTargetBodyFat}>
          {savingTargetBodyFat ? "Speichert…" : "Speichern"}
        </button>
      </form>
    </div>
  );
}

export default BodyMeasurementsSettings;
