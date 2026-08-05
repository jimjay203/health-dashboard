import { useEffect, useState } from "react";
import {
  todayIso,
  formatShortDate,
  formatPace,
  formatEnumLabel,
  fetchLoadStatus,
  fetchThresholds,
  fetchPerformanceGoals,
  type LoadStatus,
  type Thresholds,
  type PerformanceGoal,
} from "./api";
import Icon from "./Icon";

// Polarisiertes-Training-Richtgröße, dieselbe wie weekly_summary.py::POLARIZATION_MIN_Z1_Z2_PCT -
// hier gespiegelt statt über einen eigenen Endpoint geholt (gleiches Duplizierungs-Muster wie
// SPORT_TYPES zwischen Frontend/Backend). Keine erfundene phasenabhängige Zielmatrix, da dafür
// keine verifizierte Quelle im Code existiert - siehe PerformanceView-Kommentar unten.
const POLARIZATION_MIN_Z1_Z2_PCT = 70;

// Natives title-Attribut statt eigenem Popover-State - reicht für einen simplen Hover-Hinweis,
// \n wird von Browsern in title-Tooltips als Zeilenumbruch dargestellt.
function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="info-tooltip" title={text} tabIndex={0}>
      <Icon name="info" />
    </span>
  );
}

function RangeBar({
  value,
  low,
  high,
  formatValue,
}: {
  value: number | null;
  low: number | null;
  high: number | null;
  formatValue: (v: number) => string;
}) {
  if (value === null || low === null || high === null || low >= high) return null;
  const padding = (high - low) * 0.3 || 1;
  const scaleMin = low - padding;
  const scaleMax = high + padding;
  const pct = (v: number) => `${Math.max(0, Math.min(100, ((v - scaleMin) / (scaleMax - scaleMin)) * 100))}%`;

  return (
    <div className="range-bar">
      <div className="range-bar-track">
        <div className="range-bar-zone" style={{ left: pct(low), width: `calc(${pct(high)} - ${pct(low)})` }} />
        <div className="range-bar-marker" style={{ left: pct(value) }} title={formatValue(value)} />
      </div>
      <div className="range-bar-labels">
        <span>{formatValue(low)}</span>
        <span>{formatValue(high)}</span>
      </div>
    </div>
  );
}

function LoadStatusCard({ loadStatus }: { loadStatus: LoadStatus | null }) {
  const label = formatEnumLabel(loadStatus?.training_status_label ?? null);
  return (
    <div className="card performance-card">
      <h3>
        Trainingszustand
        {loadStatus?.data_date && loadStatus.data_date !== todayIso() && (
          <span className="tier-kw"> · Stand {formatShortDate(loadStatus.data_date)}</span>
        )}
      </h3>
      <div className="performance-metric-value">{label ?? "Keine Daten"}</div>
      {loadStatus?.acute_training_load != null && (
        <>
          <p className="week-rationale">
            Akute Belastung: {loadStatus.acute_training_load.toFixed(0)}
            {loadStatus.acwr_status && loadStatus.acwr_status !== "NONE" && ` · ACWR: ${formatEnumLabel(loadStatus.acwr_status)}`}
          </p>
          <RangeBar
            value={loadStatus.acute_training_load}
            low={loadStatus.chronic_load_min}
            high={loadStatus.chronic_load_max}
            formatValue={(v) => v.toFixed(0)}
          />
        </>
      )}
    </div>
  );
}

function LoadFocusBars({ loadStatus }: { loadStatus: LoadStatus | null }) {
  const bars: { label: string; pct: number | null }[] = [
    { label: "Anaerob", pct: loadStatus?.load_focus_anaerobic_pct ?? null },
    { label: "Hoch-Aerob", pct: loadStatus?.load_focus_high_aerobic_pct ?? null },
    { label: "Niedrig-Aerob", pct: loadStatus?.load_focus_low_aerobic_pct ?? null },
  ];
  const hasData = bars.some((b) => b.pct !== null);

  return (
    <div className="card performance-card">
      <h3>Belastungsfokus-Verteilung</h3>
      {hasData ? (
        <>
          {bars.map((bar) => (
            <div key={bar.label} className="load-focus-row">
              <span className="load-focus-label">{bar.label}</span>
              <div className="load-focus-track">
                <div className="load-focus-fill" style={{ width: `${bar.pct ?? 0}%` }} />
              </div>
              <span className="load-focus-pct">{bar.pct ?? 0}%</span>
            </div>
          ))}
          <p className="week-rationale">Ziel (polarisiert): ≥{POLARIZATION_MIN_Z1_Z2_PCT}% Niedrig-Aerob/lockere Belastung.</p>
        </>
      ) : (
        <p className="week-rationale">
          Noch keine Belastungsfokus-Daten von Garmin verfügbar für dieses Konto.
        </p>
      )}
    </div>
  );
}

// Höher-ist-besser (Watt/kg) vs. niedriger-ist-besser (Pace in sec/km) - anhand der Einheit
// unterschieden, da performance_goals keine explizite Richtung speichert.
function goalIsMet(actual: number, goal: PerformanceGoal): boolean {
  return goal.unit.includes("sec") ? actual <= goal.target_value : actual >= goal.target_value;
}

function GoalComparison({ goal, actual }: { goal: PerformanceGoal | undefined; actual: number | null }) {
  if (!goal || actual === null) return null;
  const met = goalIsMet(actual, goal);
  const formattedTarget = goal.unit.includes("sec") ? formatPace(goal.target_value) : `${goal.target_value} ${goal.unit}`;
  return (
    <p className={`goal-comparison${met ? " goal-met" : ""}`}>
      Ziel {goal.label}: {formattedTarget}{" "}
      {met && (
        <>
          <Icon name="check" /> erreicht
        </>
      )}
    </p>
  );
}

function RunThresholdCard({ thresholds, goals }: { thresholds: Thresholds | null; goals: PerformanceGoal[] }) {
  const marathonGoal = goals.find((g) => g.key === "marathon_pace");
  const thresholdGoal = goals.find((g) => g.key === "run_threshold_pace");
  return (
    <div className="card performance-card">
      <h3>
        Laufen
        {thresholds?.run_threshold_date && <span className="tier-kw"> · Stand {formatShortDate(thresholds.run_threshold_date)}</span>}
      </h3>
      <div className="performance-metric-value">{formatPace(thresholds?.run_threshold_pace_sec_per_km ?? null)}</div>
      <p className="week-rationale">Schwellen-HF: {thresholds?.run_threshold_hr ?? "–"} bpm</p>
      <GoalComparison goal={thresholdGoal} actual={thresholds?.run_threshold_pace_sec_per_km ?? null} />
      <GoalComparison goal={marathonGoal} actual={thresholds?.run_threshold_pace_sec_per_km ?? null} />
      <p className="week-rationale">
        VO2max: {thresholds?.vo2max_running ?? "–"}
        {thresholds?.vo2max_running_date && ` (Stand ${formatShortDate(thresholds.vo2max_running_date)})`}
      </p>
    </div>
  );
}

function BikeThresholdCard({ thresholds, goals }: { thresholds: Thresholds | null; goals: PerformanceGoal[] }) {
  const ftpGoal = goals.find((g) => g.key === "ftp_w_per_kg");
  // power_to_weight kommt direkt von Garmin (garmin_cycling_ftp.power_to_weight) - Gewicht für den
  // Tooltip aus Watt/W-pro-kg zurückgerechnet statt eines zusätzlichen Felds/API-Calls.
  const weightKg =
    thresholds?.ftp_watts != null && thresholds?.ftp_power_to_weight
      ? thresholds.ftp_watts / thresholds.ftp_power_to_weight
      : null;
  const ftpTooltip =
    thresholds?.ftp_watts != null
      ? `${thresholds.ftp_watts} W${weightKg != null ? `\n${weightKg.toFixed(1)} kg Körpergewicht` : ""}`
      : null;

  return (
    <div className="card performance-card">
      <h3>
        Rad
        {thresholds?.ftp_date && <span className="tier-kw"> · Stand {formatShortDate(thresholds.ftp_date)}</span>}
      </h3>
      <div className="performance-metric-value">
        {thresholds?.ftp_power_to_weight != null ? `${thresholds.ftp_power_to_weight.toFixed(2)} W/kg` : "–"}
        {ftpTooltip && <InfoTooltip text={ftpTooltip} />}
      </div>
      {thresholds?.cycling_threshold_hr != null && (
        <p className="week-rationale">Schwellen-HF: {thresholds.cycling_threshold_hr} bpm</p>
      )}
      <GoalComparison goal={ftpGoal} actual={thresholds?.ftp_power_to_weight ?? null} />
      <p className="week-rationale">
        VO2max: {thresholds?.vo2max_cycling ?? "–"}
        {thresholds?.vo2max_cycling_date && ` (Stand ${formatShortDate(thresholds.vo2max_cycling_date)})`}
      </p>
    </div>
  );
}

function PerformanceView() {
  const today = todayIso();
  const [loadStatus, setLoadStatus] = useState<LoadStatus | null>(null);
  const [thresholds, setThresholds] = useState<Thresholds | null>(null);
  const [goals, setGoals] = useState<PerformanceGoal[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchLoadStatus(today)
      .then(setLoadStatus)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchThresholds()
      .then(setThresholds)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchPerformanceGoals()
      .then(setGoals)
      .catch(() => setGoals([]));
  }, [today]);

  return (
    <div className="today-view performance-view">
      {error && <p className="error-banner">Fehler: {error}</p>}

      <section>
        <h2 className="performance-section-heading">Wochen-Steuerung &amp; Belastung</h2>
        <div className="performance-row">
          <LoadStatusCard loadStatus={loadStatus} />
          <LoadFocusBars loadStatus={loadStatus} />
        </div>
      </section>

      <section>
        <h2 className="performance-section-heading">Leistungsdiagnostik &amp; Schwellenwerte</h2>
        <div className="performance-row">
          <RunThresholdCard thresholds={thresholds} goals={goals} />
          <BikeThresholdCard thresholds={thresholds} goals={goals} />
        </div>
      </section>
    </div>
  );
}

export default PerformanceView;
