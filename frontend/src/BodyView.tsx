import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Line, Bar } from "react-chartjs-2";
import { Chart as ChartJS, LineElement, BarElement, PointElement, LinearScale, CategoryScale, Tooltip, Legend } from "chart.js";
import {
  todayIso,
  formatShortDate,
  fetchBodyOverview,
  fetchBodyTrend,
  fetchBodyTrendInsight,
  regenerateBodyTrendInsight,
  fetchBodyWhatIf,
  fetchBodySettings,
  saveBodySettings,
  fetchInjuries,
  createInjury,
  updateInjury,
  type BodyOverview,
  type BodyTrend,
  type BodyTrendInsight,
  type WhatIfResult,
  type Injury,
  type InjuryInput,
} from "./api";
import Icon from "./Icon";
import BodyDiagram from "./BodyDiagram";
import { fixedYAxisWidth, X_AXIS_OFFSET } from "./HrvTrendPanel";
import { useCssVar } from "./useCssVar";

ChartJS.register(LineElement, BarElement, PointElement, LinearScale, CategoryScale, Tooltip, Legend);

// --- Formatierung ---

function formatKg(value: number | null, digits = 1): string {
  if (value == null) return "–";
  return `${value.toFixed(digits)} kg`;
}

// Reiner Zahlenwert ohne Einheit - für BodyDiagnosticItem, das Wert/Einheit getrennt darstellt
// (gleiches Formatierungsmuster wie DiagnosticItem auf der Leistung-Seite, PerformanceView.tsx).
function formatNum(value: number | null, digits = 1): string {
  return value == null ? "–" : value.toFixed(digits);
}

// Sekunden -> "1:35:00 h" (>=1h) bzw. "20:15 min" - gleiche Formatierung wie PerformanceView.tsx.
function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.round(totalSeconds % 60);
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")} h`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")} min`;
}

function formatWPerKg(value: number | null): string {
  if (value == null) return "–";
  return `${value.toFixed(2)} W/kg`;
}

function formatVo2max(value: number | null): string {
  if (value == null) return "–";
  return `${value.toFixed(1)} ml/min/kg`;
}

function formatSignedKg(value: number | null): string {
  if (value == null) return "–";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)} kg`;
}

function formatWatts(value: number | null): string {
  if (value == null) return "–";
  return `${Math.round(value)} W`;
}

function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="info-tooltip" title={text} tabIndex={0}>
      <Icon name="info" />
    </span>
  );
}

// Erzwingt eine Neu-Generierung einer Gemini-Einschätzung unabhängig vom Tages-Cache - gleiches
// Muster/gleiche Styles (.tier-regenerate-button, "spinning") wie RegenerateButton in
// WeeklyCalendarWidget.tsx, hier aber generisch über den jeweiligen Insight-Typ.
function InsightRegenerateButton<T>({
  regenerateFn,
  onRegenerated,
}: {
  regenerateFn: () => Promise<T>;
  onRegenerated: (result: T) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setError(null);
    try {
      onRegenerated(await regenerateFn());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className={`tier-regenerate-button${loading ? " spinning" : ""}`}
        onClick={handleClick}
        disabled={loading}
        title="Neu generieren"
      >
        <Icon name="refresh" />
      </button>
      {error && <p className="tier-regenerate-warning">{error}</p>}
    </>
  );
}

// Gleiches Karten-Gliederungsmuster wie die Sportart-Karten auf der Leistung-Seite
// (PerformanceView.tsx::Subsection/DiagnosticItem) - dort lokal definiert statt exportiert, daher
// hier dieselbe kleine Komponente noch einmal (gleiche Konvention wie InfoTooltip oben).
function Subsection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="performance-subsection">
      <p className="performance-subsection-label">{title}</p>
      {children}
    </div>
  );
}

function BodyDiagnosticItem({
  label,
  value,
  unit,
  sub,
  tooltip,
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: ReactNode;
  tooltip?: string;
}) {
  return (
    <div className="performance-diagnostic-item">
      <div className="performance-diagnostic-value">
        {value}
        {unit && <span className="performance-diagnostic-unit"> {unit}</span>}
      </div>
      <div className="performance-diagnostic-label">
        {label}
        {tooltip && <InfoTooltip text={tooltip} />}
      </div>
      {sub && <div className="body-diagnostic-sub">{sub}</div>}
    </div>
  );
}

const RACE_LABELS: Record<string, string> = {
  time_5k: "5 km",
  time_10k: "10 km",
  time_half_marathon: "Halbmarathon",
  time_marathon: "Marathon",
};
const RACE_ORDER = ["time_5k", "time_10k", "time_half_marathon", "time_marathon"];

// --- Übersicht ---

const BODY_OVERVIEW_TOOLTIP =
  "Körperzusammensetzung aus der Withings-Waage. FFMI (Fat-Free Mass Index) und BMR (Katch-" +
  "McArdle-Formel) basieren auf der fettfreien Masse (Gewicht - Fettmasse). FFMI braucht deine " +
  "Körpergröße - wird automatisch aus Garmin übernommen, unter Einstellungen überschreibbar.";

const FFMI_TOOLTIP =
  "FFMI-Klassifizierung nach ffmicalculator.io - eine von mehreren gängigen Einteilungen für " +
  "natürliche (nicht leistungsoptimierte) Athleten, keine medizinische Norm. Andere Quellen " +
  "setzen die Grenzen leicht anders.";

const HYDRATION_TOOLTIP =
  "Grobe Referenzspanne für erwachsene Männer (Quelle: InBody - aktiv ca. 55-65%, athletisch ca. " +
  "60-70% Körperwasseranteil), keine personalisierte oder medizinische Bewertung.";

const HYDRATION_STATUS_LABEL_DE: Record<string, string> = {
  normal: "Normal",
  "erhöht": "Erhöht",
};

function BodyOverviewCard({ overview }: { overview: BodyOverview | null }) {
  if (!overview || overview.weight_kg == null) {
    return (
      <div className="card">
        <h3>
          Körperzusammensetzung
          <InfoTooltip text={BODY_OVERVIEW_TOOLTIP} />
        </h3>
        <p className="week-rationale">Noch keine Withings-Messung synchronisiert.</p>
      </div>
    );
  }

  const bodyFatDiff =
    overview.target_body_fat_pct != null && overview.body_fat_pct != null
      ? overview.body_fat_pct - overview.target_body_fat_pct
      : null;

  const hydrationLabel =
    overview.hydration_status != null
      ? HYDRATION_STATUS_LABEL_DE[overview.hydration_status] ?? overview.hydration_status
      : null;

  return (
    <div className="card performance-card performance-sport-card">
      <h3>
        Körperzusammensetzung
        <InfoTooltip text={BODY_OVERVIEW_TOOLTIP} />
      </h3>
      <p className="week-rationale">Letzte Messung: {formatShortDate(overview.measured_date ?? todayIso())}</p>

      {/* 1. Übersicht (Hero) */}
      <Subsection title="Übersicht">
        <div className="body-hero-row">
          <div className="body-hero-item">
            <div className="performance-metric-value">
              {formatNum(overview.weight_kg)}
              <span className="performance-metric-caption"> kg Gewicht</span>
            </div>
            <div className="body-hero-sub">
              {overview.weight_trend_7d_kg != null
                ? `${formatSignedKg(overview.weight_trend_7d_kg)} ggü. 7-Tage-Schnitt`
                : "Noch kein 7-Tage-Vergleich"}
            </div>
          </div>
          <div className="body-hero-item">
            <div className="performance-metric-value">
              {formatNum(overview.body_fat_pct)}
              <span className="performance-metric-caption"> % Körperfett</span>
            </div>
            <div className="body-hero-sub">
              {overview.target_body_fat_pct == null
                ? "Kein Zielwert gesetzt"
                : bodyFatDiff != null && bodyFatDiff > 0
                  ? `Ziel ${overview.target_body_fat_pct}% (noch -${bodyFatDiff.toFixed(1)}pp)`
                  : `Ziel ${overview.target_body_fat_pct}% erreicht`}
            </div>
          </div>
          <div className="body-hero-item">
            <div className="performance-metric-value">
              {overview.body_water_pct != null ? overview.body_water_pct.toFixed(1) : "–"}
              <span className="performance-metric-caption"> % Wasser</span>
              <InfoTooltip text={HYDRATION_TOOLTIP} />
            </div>
            <div className="body-hero-sub">{hydrationLabel ?? "–"}</div>
          </div>
        </div>
      </Subsection>

      {/* 2. Substanz-Verteilung */}
      <Subsection title="Substanz-Verteilung">
        <div className="performance-diagnostics-row">
          <BodyDiagnosticItem label="Muskelmasse" value={formatNum(overview.muscle_mass_kg)} unit="kg" />
          <BodyDiagnosticItem label="Fettmasse" value={formatNum(overview.fat_mass_kg)} unit="kg" />
          <BodyDiagnosticItem label="Knochenmasse" value={formatNum(overview.bone_mass_kg)} unit="kg" />
        </div>
      </Subsection>

      {/* 3. Physiologische Indikatoren */}
      <Subsection title="Physiologische Indikatoren">
        <div className="performance-diagnostics-row">
          <BodyDiagnosticItem
            label="FFMI"
            value={overview.ffmi != null ? overview.ffmi.toFixed(1) : "–"}
            tooltip={FFMI_TOOLTIP}
            sub={
              overview.ffmi_classification ? (
                <span className="status-pill body-ffmi-badge">
                  {overview.ffmi_classification} ({overview.ffmi!.toFixed(1)})
                </span>
              ) : undefined
            }
          />
          <BodyDiagnosticItem
            label="Muskel-Fett-Ratio"
            value={overview.muscle_fat_ratio != null ? overview.muscle_fat_ratio.toFixed(2) : "–"}
          />
          <BodyDiagnosticItem label="Grundumsatz (BMR)" value={overview.bmr_kcal != null ? String(Math.round(overview.bmr_kcal)) : "–"} unit="kcal" />
        </div>
      </Subsection>

      {/* 4. Performance-Bezug (zentriert) */}
      <Subsection title="Performance-Bezug">
        <div className="performance-diagnostics-row body-performance-row">
          <BodyDiagnosticItem
            label="Rad-W/kg"
            value={overview.cycling_power_to_weight != null ? overview.cycling_power_to_weight.toFixed(2) : "–"}
            unit="W/kg"
            sub={`FTP: ${formatWatts(overview.cycling_ftp_watts)}`}
          />
          <BodyDiagnosticItem
            label="Lauf-W/kg"
            value={overview.running_power_to_weight != null ? overview.running_power_to_weight.toFixed(2) : "–"}
            unit="W/kg"
            sub={`Schwelle: ${formatWatts(overview.running_ftp_watts)}`}
          />
          <BodyDiagnosticItem
            label="VO2max (Lauf)"
            value={overview.vo2max_running != null ? overview.vo2max_running.toFixed(1) : "–"}
            unit="ml/kg/min"
          />
          <BodyDiagnosticItem
            label="VO2max (Rad)"
            value={overview.vo2max_cycling != null ? overview.vo2max_cycling.toFixed(1) : "–"}
            unit="ml/kg/min"
          />
        </div>
      </Subsection>
    </div>
  );
}

// --- Trend: Körperzusammensetzung ---

function CompositionTrendCharts({ trend }: { trend: BodyTrend }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  const accentColor = useCssVar("--accent");
  const points = trend.points;

  const commonOptions = (unitSuffix: string) => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: false as const,
    scales: {
      x: { offset: X_AXIS_OFFSET, grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 7, autoSkip: true } },
      y: {
        afterFit: fixedYAxisWidth,
        grid: { color: gridColor },
        ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 4, callback: (v: number | string) => `${v}${unitSuffix}` },
      },
    },
    plugins: {
      legend: { display: true, position: "bottom" as const, labels: { color: textColor, font: { size: 10 }, boxWidth: 10, padding: 12 } },
      tooltip: { enabled: true, padding: 6, titleFont: { size: 11 }, bodyFont: { size: 11 } },
    },
  });

  if (points.length < 2) {
    return <p className="week-rationale">Noch nicht genug Withings-Messungen für einen Trend.</p>;
  }

  const labels = points.map((p) => formatShortDate(p.date));

  return (
    <div className="body-trend-grid">
      <div className="hrv-trend-chart-block">
        <div className="hrv-trend-chart-title">Gewicht</div>
        <div className="hrv-trend-chart-canvas">
          <Line
            data={{
              labels,
              datasets: [
                {
                  label: "Gewicht",
                  data: points.map((p) => p.weight_kg),
                  borderColor: gridColor,
                  backgroundColor: gridColor,
                  pointRadius: 2,
                  borderWidth: 1,
                  spanGaps: true,
                },
                {
                  label: "7-Tage-Schnitt",
                  data: points.map((p) => p.weight_rolling_avg_kg),
                  borderColor: accentColor,
                  backgroundColor: accentColor,
                  pointRadius: 0,
                  borderWidth: 2,
                  tension: 0.3,
                  spanGaps: true,
                },
              ],
            }}
            options={commonOptions(" kg")}
          />
        </div>
      </div>

      <div className="hrv-trend-chart-block">
        <div className="hrv-trend-chart-title">Muskelmasse vs. Fettmasse</div>
        <div className="hrv-trend-chart-canvas">
          <Line
            data={{
              labels,
              datasets: [
                {
                  label: "Muskelmasse",
                  data: points.map((p) => p.muscle_mass_kg),
                  borderColor: accentColor,
                  backgroundColor: accentColor,
                  pointRadius: 2,
                  borderWidth: 2,
                  spanGaps: true,
                },
                {
                  label: "Fettmasse",
                  data: points.map((p) => p.fat_mass_kg),
                  borderColor: "#f5a623",
                  backgroundColor: "#f5a623",
                  pointRadius: 2,
                  borderWidth: 2,
                  spanGaps: true,
                },
              ],
            }}
            options={commonOptions(" kg")}
          />
        </div>
      </div>

      <div className="hrv-trend-chart-block">
        <div className="hrv-trend-chart-title">Körperfett %</div>
        <div className="hrv-trend-chart-canvas">
          <Line
            data={{
              labels,
              datasets: [
                {
                  label: "Körperfett",
                  data: points.map((p) => p.body_fat_pct),
                  borderColor: "#f5a623",
                  backgroundColor: "#f5a623",
                  pointRadius: 2,
                  borderWidth: 2,
                  spanGaps: true,
                },
              ],
            }}
            options={{
              ...commonOptions(" %"),
              plugins: { ...commonOptions(" %").plugins, legend: { display: false } },
            }}
          />
        </div>
      </div>

      <div className="hrv-trend-chart-block">
        <div className="hrv-trend-chart-title">Wasser &amp; Knochenmasse</div>
        <div className="hrv-trend-chart-canvas">
          <Line
            data={{
              labels,
              datasets: [
                {
                  label: "Wasser",
                  data: points.map((p) => p.body_water_kg),
                  borderColor: "#38bdf8",
                  backgroundColor: "#38bdf8",
                  pointRadius: 2,
                  borderWidth: 2,
                  spanGaps: true,
                },
                {
                  label: "Knochenmasse",
                  data: points.map((p) => p.bone_mass_kg),
                  borderColor: "#a78bfa",
                  backgroundColor: "#a78bfa",
                  pointRadius: 2,
                  borderWidth: 2,
                  spanGaps: true,
                },
              ],
            }}
            options={commonOptions(" kg")}
          />
        </div>
      </div>
    </div>
  );
}

// --- What-if-Simulator ---

const RUN_PACE_HEURISTIC_TOOLTIP =
  "Angenommen wird eine konstante absolute VO2max-Kapazität (dieselbe Annahme wie beim relativen " +
  "VO2max oben): die Zeit skaliert direkt proportional zum Verhältnis aus Zielgewicht und " +
  "aktuellem Gewicht (neue Zeit = aktuelle Zeit × Zielgewicht/aktuelles Gewicht), angewendet auf " +
  "deine aktuellen Garmin-Renn-Prognosen. Funktioniert für Gewichtsverlust und -zunahme.";

function WhatIfSimulator({
  overview,
  targetWeight,
  setTargetWeight,
  whatIf,
  onSaveTarget,
}: {
  overview: BodyOverview | null;
  targetWeight: string;
  setTargetWeight: (value: string) => void;
  whatIf: WhatIfResult | null;
  onSaveTarget: () => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await onSaveTarget();
    } finally {
      setSaving(false);
    }
  }

  if (!overview || overview.weight_kg == null) {
    return null;
  }

  return (
    <div className="card">
      <h3>
        What-if-Simulator
        <InfoTooltip text="Rechnet dein aktuelles Rad-W/kg, deinen relativen Lauf-VO2max und deine Garmin-Renn-Prognosen auf ein Zielgewicht um. W/kg und VO2max sind reine Neuberechnung bestehender Formeln, die Renn-Zeit-Prognose nutzt eine explizit gekennzeichnete Faustregel (siehe Tooltip unten)." />
      </h3>
      <div className="body-what-if-input-row">
        <label>
          Zielgewicht
          <input
            type="number"
            step="0.1"
            min="0"
            value={targetWeight}
            onChange={(e) => setTargetWeight(e.target.value)}
          />
          kg
        </label>
        <span className="week-rationale">Aktuell: {formatKg(overview.weight_kg)}</span>
        <button type="button" onClick={handleSave} disabled={saving}>
          {saving ? "Speichert…" : "Als Ziel speichern"}
        </button>
      </div>

      {whatIf && (
        <>
          <div className="performance-diagnostics-row body-diagnostics-row">
            <div className="performance-diagnostic-item">
              <div className="performance-diagnostic-value">{formatWPerKg(whatIf.cycling_power_to_weight_current)}</div>
              <div className="performance-diagnostic-label">Rad-W/kg (aktuell)</div>
            </div>
            <div className="performance-diagnostic-item">
              <div className="performance-diagnostic-value">{formatWPerKg(whatIf.cycling_power_to_weight_target)}</div>
              <div className="performance-diagnostic-label">Rad-W/kg (Zielgewicht)</div>
            </div>
            <div className="performance-diagnostic-item">
              <div className="performance-diagnostic-value">{formatVo2max(whatIf.vo2max_running_current)}</div>
              <div className="performance-diagnostic-label">Lauf-VO2max (aktuell)</div>
            </div>
            <div className="performance-diagnostic-item">
              <div className="performance-diagnostic-value">{formatVo2max(whatIf.vo2max_running_target)}</div>
              <div className="performance-diagnostic-label">Lauf-VO2max (Zielgewicht)</div>
            </div>
          </div>

          {whatIf.race_time_projection ? (
            <div className="body-race-projection">
              <div className="hrv-trend-chart-title">
                Renn-Zeit-Prognose
                <InfoTooltip text={RUN_PACE_HEURISTIC_TOOLTIP} />
              </div>
              <table className="club-slots-table">
                <thead>
                  <tr>
                    <th>Distanz</th>
                    <th>Aktuell</th>
                    <th>Bei Zielgewicht</th>
                  </tr>
                </thead>
                <tbody>
                  {RACE_ORDER.filter((key) => whatIf.race_time_projection?.[key]).map((key) => {
                    const entry = whatIf.race_time_projection![key];
                    return (
                      <tr key={key}>
                        <td>{RACE_LABELS[key]}</td>
                        <td>{formatDuration(entry.current_seconds)}</td>
                        <td>{formatDuration(entry.target_seconds)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="week-rationale">Noch keine Garmin-Renn-Prognosen für eine Zeit-Prognose vorhanden.</p>
          )}
        </>
      )}
    </div>
  );
}

// --- Verletzungs-/Schmerzprotokoll ---

const BODY_PART_SUGGESTIONS = [
  "Knie links", "Knie rechts", "Achillessehne links", "Achillessehne rechts",
  "Wade links", "Wade rechts", "Oberschenkel links", "Oberschenkel rechts",
  "Hüfte links", "Hüfte rechts", "Schienbein links", "Schienbein rechts",
  "Ferse/Plantarfaszie links", "Ferse/Plantarfaszie rechts", "Rücken/LWS", "Schulter",
];
const PAIN_TYPES = ["Stechend", "Dumpf", "Morgensteifigkeit", "Druckschmerz", "Ziehen"];
const PAIN_CONTEXTS = ["Beim Laufen", "Beim Radfahren", "Beim Gehen", "Ruheschmerz", "Nach dem Training"];

function severityColor(severity: number): string {
  if (severity >= 7) return "#f87171";
  if (severity >= 4) return "#f5a623";
  return "#3dd68c";
}

function emptyInjuryForm(): InjuryInput {
  return { date: todayIso(), body_part: "", severity: 3, pain_type: null, context: null, notes: null };
}

function InjuryForm({ onSaved }: { onSaved: () => void }) {
  const [form, setForm] = useState<InjuryInput>(emptyInjuryForm());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.body_part.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createInjury(form);
      setForm(emptyInjuryForm());
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="body-injury-form" onSubmit={handleSubmit}>
      {error && <p className="error-banner">Fehler: {error}</p>}
      <div className="body-injury-form-row">
        <div className="habit-tracker-form body-injury-form-fields">
          <div className="habit-tracker-row">
            <label className="habit-tracker-time-field">
              Datum
              <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} required />
            </label>
          </div>
          <div className="habit-tracker-row">
            <label className="habit-tracker-time-field">
              Körperstelle
              <input
                list="body-part-suggestions"
                value={form.body_part}
                onChange={(e) => setForm({ ...form, body_part: e.target.value })}
                placeholder="z. B. Knie rechts, oder rechts im Diagramm anklicken"
                required
              />
              <datalist id="body-part-suggestions">
                {BODY_PART_SUGGESTIONS.map((b) => (
                  <option key={b} value={b} />
                ))}
              </datalist>
            </label>
          </div>
          <div className="habit-tracker-row">
            <label className="habit-tracker-time-field">
              Schmerz-Skala (1-10)
              <input
                type="number"
                min="1"
                max="10"
                value={form.severity}
                onChange={(e) => setForm({ ...form, severity: Number(e.target.value) })}
                required
              />
            </label>
          </div>
          <div className="habit-tracker-row">
            <label className="habit-tracker-time-field">
              Schmerz-Typ
              <select value={form.pain_type ?? ""} onChange={(e) => setForm({ ...form, pain_type: e.target.value || null })}>
                <option value="">–</option>
                {PAIN_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="habit-tracker-row">
            <label className="habit-tracker-time-field">
              Kontext
              <select value={form.context ?? ""} onChange={(e) => setForm({ ...form, context: e.target.value || null })}>
                <option value="">–</option>
                {PAIN_CONTEXTS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="habit-tracker-row">
            <label className="habit-tracker-time-field">
              Notiz
              <input value={form.notes ?? ""} onChange={(e) => setForm({ ...form, notes: e.target.value || null })} />
            </label>
          </div>
          <div className="journal-form-actions">
            <button type="submit" disabled={saving}>
              {saving ? "Speichert…" : "Eintrag speichern"}
            </button>
          </div>
        </div>
        <div className="body-injury-form-diagram">
          <BodyDiagram
            selectedLabel={form.body_part || null}
            onSelect={(label) => setForm({ ...form, body_part: label })}
          />
        </div>
      </div>
    </form>
  );
}

function ActiveInjuryBadges({ injuries, onResolve }: { injuries: Injury[]; onResolve: (id: number) => void }) {
  const active = injuries.filter((i) => i.resolved_at == null);
  if (active.length === 0) return null;
  return (
    <div className="body-active-injuries-row">
      {active.map((i) => (
        <span key={i.id} className="status-pill body-injury-badge" style={{ color: severityColor(i.severity), borderColor: severityColor(i.severity), backgroundColor: `${severityColor(i.severity)}1a` }}>
          <Icon name="warning" /> {i.body_part}: {i.severity}/10
          <button type="button" className="body-injury-resolve-btn" onClick={() => onResolve(i.id)} title="Als abgeklungen markieren">
            <Icon name="check" />
          </button>
        </span>
      ))}
    </div>
  );
}

function PainChart({ injuries }: { injuries: Injury[] }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");

  if (injuries.length === 0) return null;

  return (
    <div className="hrv-trend-panel">
      <div className="hrv-trend-chart-block">
        <div className="hrv-trend-chart-title">Schmerz-Verlauf</div>
        <div className="hrv-trend-chart-canvas">
          <Bar
            data={{
              labels: injuries.map((i) => formatShortDate(i.date)),
              datasets: [
                {
                  label: "Schmerz-Skala",
                  data: injuries.map((i) => i.severity),
                  backgroundColor: injuries.map((i) => severityColor(i.severity)),
                  borderRadius: 2,
                },
              ],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              animation: false,
              scales: {
                x: { offset: X_AXIS_OFFSET, grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 7, autoSkip: true } },
                y: { min: 0, max: 10, afterFit: fixedYAxisWidth, grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 5 } },
              },
              plugins: {
                legend: { display: false },
                tooltip: {
                  enabled: true,
                  padding: 6,
                  titleFont: { size: 11 },
                  bodyFont: { size: 11 },
                  callbacks: {
                    label: (item) => {
                      const i = injuries[item.dataIndex];
                      return `${i.body_part}: ${i.severity}/10${i.pain_type ? ` · ${i.pain_type}` : ""}${i.context ? ` · ${i.context}` : ""}`;
                    },
                  },
                },
              },
            }}
          />
        </div>
      </div>
    </div>
  );
}

function InjuryLogCard({ injuries, onReload }: { injuries: Injury[]; onReload: () => void }) {
  async function handleResolve(id: number) {
    await updateInjury(id, { resolved: true });
    onReload();
  }

  return (
    <div className="card">
      <h3>Verletzungs-/Schmerzprotokoll</h3>
      <ActiveInjuryBadges injuries={injuries} onResolve={handleResolve} />
      <PainChart injuries={injuries} />
      <InjuryForm onSaved={onReload} />
    </div>
  );
}

// --- Hauptseite ---

function BodyView() {
  const [overview, setOverview] = useState<BodyOverview | null>(null);
  const [trend, setTrend] = useState<BodyTrend | null>(null);
  const [trendInsight, setTrendInsight] = useState<BodyTrendInsight | null>(null);
  const [trendInsightLoading, setTrendInsightLoading] = useState(false);
  const [targetWeight, setTargetWeight] = useState("");
  const [whatIf, setWhatIf] = useState<WhatIfResult | null>(null);
  const [injuries, setInjuries] = useState<Injury[]>([]);
  const [error, setError] = useState<string | null>(null);

  function reloadOverview() {
    fetchBodyOverview()
      .then(setOverview)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }

  function reloadInjuries() {
    fetchInjuries()
      .then(setInjuries)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(() => {
    reloadOverview();
    fetchBodyTrend(90)
      .then(setTrend)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchBodySettings()
      .then((s) => {
        if (s.target_weight_kg != null) setTargetWeight(String(s.target_weight_kg));
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    reloadInjuries();
  }, []);

  // Erst anfragen, sobald genug Trend-Daten für die Charts da sind (gleiche Bedingung wie unten
  // beim Rendern) - vermeidet einen Gemini-Aufruf ohne sinnvolle Datenbasis.
  useEffect(() => {
    if (!trend || trend.points.length <= 1) return;
    setTrendInsightLoading(true);
    fetchBodyTrendInsight()
      .then(setTrendInsight)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setTrendInsightLoading(false));
  }, [trend]);

  useEffect(() => {
    const value = Number(targetWeight.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) {
      setWhatIf(null);
      return;
    }
    const timeout = setTimeout(() => {
      fetchBodyWhatIf(value)
        .then(setWhatIf)
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }, 400);
    return () => clearTimeout(timeout);
  }, [targetWeight]);

  async function handleSaveTarget() {
    const value = Number(targetWeight.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) return;
    await saveBodySettings({ target_weight_kg: value });
  }

  return (
    <div className="today-view">
      {error && <p className="error-banner">Fehler: {error}</p>}

      <div className="performance-row body-overview-trend-row">
        <div className="body-half-col">
          <BodyOverviewCard overview={overview} />
        </div>
        <div className="body-half-col">
          <InjuryLogCard injuries={injuries} onReload={reloadInjuries} />
        </div>
      </div>

      {trend && (
        <div className="card">
          <h3>
            Trend (90 Tage)
            {trendInsight && (
              <InsightRegenerateButton regenerateFn={regenerateBodyTrendInsight} onRegenerated={setTrendInsight} />
            )}
          </h3>
          <div className="sleep-trend-row">
            <div className="sleep-insight-col">
              {trendInsightLoading && !trendInsight ? (
                <p className="week-rationale">Lade Einordnung…</p>
              ) : trendInsight ? (
                <p className="sleep-insight-text">{trendInsight.insight_text}</p>
              ) : (
                <p className="week-rationale">Keine Einordnung verfügbar.</p>
              )}
            </div>
            <CompositionTrendCharts trend={trend} />
          </div>
        </div>
      )}

      <WhatIfSimulator
        overview={overview}
        targetWeight={targetWeight}
        setTargetWeight={setTargetWeight}
        whatIf={whatIf}
        onSaveTarget={handleSaveTarget}
      />
    </div>
  );
}

export default BodyView;
