import { useEffect, useState, type ReactNode } from "react";
import { Line } from "react-chartjs-2";
import { Chart as ChartJS, LineElement, PointElement, LinearScale, CategoryScale, Tooltip, Filler, Legend } from "chart.js";
import {
  todayIso,
  formatShortDate,
  formatPace,
  formatSecondsToPace,
  formatGoalValue,
  unitDisplayLabel,
  goalProgressPct,
  fetchLoadStatus,
  fetchCtlTrend,
  fetchThresholds,
  fetchPerformanceGoals,
  fetchPerformanceGoalsInsight,
  fetchRacePredictions,
  fetchCyclingPrediction,
  fetchSwimDiagnostics,
  type LoadStatus,
  type CtlTrendPoint,
  type Thresholds,
  type PerformanceGoal,
  type PerformanceGoalsInsight,
  type RacePredictions,
  type CyclingPrediction,
  type SwimDiagnostics,
} from "./api";
import Icon from "./Icon";
import { useCssVar } from "./useCssVar";

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Tooltip, Filler, Legend);

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

// Sekunden -> "1:35:00 h" (>=1h) bzw. "20:15 min" - für Renn-/Prognose-Zeiten, deren
// Größenordnung je nach Distanz stark variiert (5km vs. Marathon).
function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.round(totalSeconds % 60);
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")} h`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")} min`;
}

// CTL/ATL/TSB als schlichte Werte-Zeile im Strava-Stil ("Fitness & Freshness": große Zahl + farbiger
// Punkt + Beschriftung, nebeneinander) statt Kacheln - eigene Berechnung statt Garmins
// unzuverlässiger Trainingszustand-Klassifizierung, siehe Ground-Truth-Fund in
// backend/routers/performance.py. Rundet bewusst auf ganze Zahlen (wie Strava/TrainingPeaks selbst).
function TrainingStateRow({ ctl, atl, tsb }: { ctl: number | null; atl: number | null; tsb: number | null }) {
  if (ctl == null || atl == null || tsb == null) return null;
  const metrics: { value: number; label: string; dotClass: string }[] = [
    { value: ctl, label: "Fitness (CTL)", dotClass: "training-state-dot-fitness" },
    { value: atl, label: "Ermüdung (ATL)", dotClass: "training-state-dot-fatigue" },
    { value: tsb, label: "Form (TSB)", dotClass: "training-state-dot-form" },
  ];
  return (
    <div className="training-state-row">
      {metrics.map((m) => (
        <div key={m.label} className="training-state-metric">
          <span className="training-state-metric-value">{Math.round(m.value)}</span>
          <span className="training-state-metric-label">
            <span className={`training-state-dot ${m.dotClass}`} />
            {m.label}
          </span>
        </div>
      ))}
    </div>
  );
}

// Fitness-Verlauf (CTL über Zeit) als Flächen-Linienchart, angelehnt an Strava "Fitness &
// Freshness" - bewusst nur CTL (nicht ATL/TSB), wie gewünscht ein einzelner Verlauf statt der
// zusätzlichen Slider/Vergleichscharts, die Strava dort noch zeigt.
function CtlTrendChart({ trend }: { trend: CtlTrendPoint[] }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  const accentColor = useCssVar("--accent");
  if (trend.length < 2) return null;

  return (
    <div className="ctl-trend-chart-canvas">
      <Line
        data={{
          labels: trend.map((p) => formatShortDate(p.date)),
          datasets: [
            {
              label: "Fitness (CTL)",
              data: trend.map((p) => p.ctl),
              borderColor: "#f5a623",
              backgroundColor: "rgba(245, 166, 35, 0.12)",
              borderWidth: 2,
              pointRadius: 0,
              fill: true,
              tension: 0.25,
              spanGaps: true,
            },
            // ATL/TSB per Klick auf die Legende manuell einblendbar (Chart.js-Standardverhalten
            // bei aktivierter Legende) - "hidden" startet sie ausgeblendet, wie gewünscht.
            {
              label: "Ermüdung (ATL)",
              data: trend.map((p) => p.atl),
              borderColor: "#e5484d",
              backgroundColor: "rgba(229, 72, 77, 0.12)",
              borderWidth: 2,
              pointRadius: 0,
              fill: true,
              tension: 0.25,
              spanGaps: true,
              hidden: true,
            },
            {
              label: "Form (TSB)",
              data: trend.map((p) => p.tsb),
              borderColor: accentColor,
              backgroundColor: `${accentColor}1f`,
              borderWidth: 2,
              pointRadius: 0,
              fill: true,
              tension: 0.25,
              spanGaps: true,
              hidden: true,
            },
          ],
        }}
        options={{
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 6, autoSkip: true },
            },
            y: {
              grid: { color: gridColor },
              ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 4 },
            },
          },
          plugins: {
            legend: {
              display: true,
              position: "bottom",
              labels: { color: textColor, font: { size: 10 }, boxWidth: 10, padding: 12 },
            },
            tooltip: { enabled: true, padding: 6, titleFont: { size: 11 }, bodyFont: { size: 11 } },
          },
        }}
      />
    </div>
  );
}

const TRAINING_STATE_TOOLTIP =
  "CTL (Fitness): langfristige, chronische Trainingsbelastung (42-Tage-Schnitt).\n" +
  "ATL (Ermüdung): kurzfristige, akute Belastung (7-Tage-Schnitt).\n" +
  "TSB (Form): CTL minus ATL - positiv = frisch/erholt, negativ = ermüdet/im Aufbau.\n" +
  "Eigene Berechnung (PMC-Modell), nicht von Garmin übernommen.";

function LoadStatusCard({ loadStatus, ctlTrend }: { loadStatus: LoadStatus | null; ctlTrend: CtlTrendPoint[] }) {
  return (
    <div className="card performance-card">
      <h3>
        Trainingszustand
        <InfoTooltip text={TRAINING_STATE_TOOLTIP} />
        {loadStatus?.data_date && loadStatus.data_date !== todayIso() && (
          <span className="tier-kw"> · Stand {formatShortDate(loadStatus.data_date)}</span>
        )}
      </h3>
      {loadStatus?.tsb != null ? (
        <>
          <TrainingStateRow ctl={loadStatus.ctl} atl={loadStatus.atl} tsb={loadStatus.tsb} />
          <p className="performance-metric-caption">{loadStatus.training_state_label ?? "–"}</p>
          <CtlTrendChart trend={ctlTrend} />
        </>
      ) : (
        <div className="performance-metric-value">Keine Daten</div>
      )}
    </div>
  );
}

const LOAD_FOCUS_TOOLTIP =
  "Eigene Berechnung aus den HF-Zonen-Zeiten der letzten 28 Tage (Z1+Z2 = Niedrig-Aerob, Z3 = " +
  "Hoch-Aerob, Z4+Z5 = Anaerob) - Garmins eigene Verteilung liefert für dieses Konto durchgängig " +
  "keine Daten, siehe Ground-Truth-Fund in backend/routers/performance.py.";

// Dieselbe Ampel-Logik wie überall sonst in der App (grün/orange/rot, siehe --accent/HRV-Bereich) -
// Niedrig-Aerob grün, da das hier die Zielzone ist (Polarisierungs-Ziel ≥70%). Nur Niedrig-Aerob
// bekommt einen Ziel-Strich auf dem Balken - für Hoch-Aerob/Anaerob gibt es keinen verifizierten
// Schwellenwert im Code (siehe POLARIZATION_MIN_Z1_Z2_PCT-Kommentar oben), deshalb wird dort bewusst
// keiner erfunden statt eine plausibel wirkende, aber nicht belegte Zahl zu zeigen.
function LoadFocusBars({ loadStatus }: { loadStatus: LoadStatus | null }) {
  const bars: { label: string; pct: number | null; colorClass: string; target?: number }[] = [
    { label: "Anaerob", pct: loadStatus?.load_focus_anaerobic_pct ?? null, colorClass: "load-focus-fill-anaerobic" },
    { label: "Hoch-Aerob", pct: loadStatus?.load_focus_high_aerobic_pct ?? null, colorClass: "load-focus-fill-high-aerobic" },
    {
      label: "Niedrig-Aerob",
      pct: loadStatus?.load_focus_low_aerobic_pct ?? null,
      colorClass: "load-focus-fill-low-aerobic",
      target: POLARIZATION_MIN_Z1_Z2_PCT,
    },
  ];
  const hasData = bars.some((b) => b.pct !== null);

  return (
    <div className="card performance-card">
      <h3>
        Belastungsfokus-Verteilung
        <InfoTooltip text={LOAD_FOCUS_TOOLTIP} />
      </h3>
      {hasData ? (
        <>
          <p className="load-focus-target">
            <span className="load-focus-target-value">{(loadStatus?.load_focus_low_aerobic_pct ?? 0).toFixed(0)}%</span>
            <span className="load-focus-target-goal"> Niedrig-Aerob · Ziel: ≥{POLARIZATION_MIN_Z1_Z2_PCT}%</span>
          </p>
          {bars.map((bar) => (
            <div key={bar.label} className="load-focus-row">
              <span className="load-focus-label">{bar.label}</span>
              <div className="load-focus-track">
                <div className={`load-focus-fill ${bar.colorClass}`} style={{ width: `${bar.pct ?? 0}%` }} />
                {bar.target != null && (
                  <div
                    className="load-focus-target-marker"
                    style={{ left: `${bar.target}%` }}
                    title={`Ziel: ≥${bar.target}%`}
                  />
                )}
              </div>
              <span className="load-focus-pct">{(bar.pct ?? 0).toFixed(0)}%</span>
            </div>
          ))}
        </>
      ) : (
        <p className="week-rationale">
          Noch keine Aktivität mit HF-Zonen-Daten in den letzten 28 Tagen.
        </p>
      )}
    </div>
  );
}

// Eigener Kasten (Hintergrund-Ton statt nur einer Beschriftung) pro Unterabschnitt einer
// Sportart-Karte - Diagnostik/Ziel-Tracking/Wettkampf-Prognose sollen sich klar voneinander
// abheben, nicht nur durch eine kleine Caption getrennt sein.
function Subsection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="performance-subsection">
      <p className="performance-subsection-label">{title}</p>
      {children}
    </div>
  );
}

// Kleiner Diagnostik-Wert innerhalb der Sportart-Karte (kein eigenes .card - Diagnostik-Werte
// haben keine Zielverfolgung, sind reine Ist-Werte, siehe DiagnosticsRow). unit separat vom
// Zahlenwert übergeben statt Teil des value-Strings, damit sie kleiner/nicht-fett dargestellt
// werden kann (siehe .performance-diagnostic-unit) - als verschachtelter <span> im selben
// Inline-Textfluss sitzt sie automatisch auf derselben Grundlinie wie die Zahl, ohne dass es
// dafür ein eigenes Flex-Alignment bräuchte. SWOLF hat bewusst keine Einheit (dimensionslose
// Kennzahl, keine erfundene Einheit).
function DiagnosticItem({
  label,
  value,
  unit,
  date,
}: {
  label: string;
  value: string;
  unit?: string;
  date?: string | null;
}) {
  return (
    <div className="performance-diagnostic-item">
      <div className="performance-diagnostic-value">
        {value}
        {unit && <span className="performance-diagnostic-unit"> {unit}</span>}
      </div>
      <div className="performance-diagnostic-label">
        {label}
        {date && <span className="performance-diagnostic-date"> · {formatShortDate(date)}</span>}
      </div>
    </div>
  );
}

// Höher-ist-besser (Watt/kg) vs. niedriger-ist-besser (Pace in sec/km) - anhand der Einheit
// unterschieden, da performance_goals keine explizite Richtung speichert.
function goalIsMet(actual: number, goal: PerformanceGoal): boolean {
  return goal.unit.includes("sec") ? actual <= goal.target_value : actual >= goal.target_value;
}

// current_value/start_value kommen serverseitig aus echten Garmin-Zeitreihen (siehe
// GOAL_METRIC_SOURCES/_swim_pace_value in backend/routers/performance.py) - current_value bleibt
// null, falls für einen Ziel-Typ (noch) kein Ist-Wert vorliegt, dafür wird gar nichts gerendert
// statt eines erfundenen Vergleichs. start_value ist NICHT an ein manuell gesetztes Startdatum
// gebunden - ohne eigenes start_date liefert das Backend automatisch die früheste verfügbare
// Messung als impliziten Start (siehe start_value_date), damit ein Fortschrittsbalken so früh wie
// möglich entsteht statt auf eine manuelle Eingabe zu warten. Nur wenn wirklich gar keine Historie
// existiert (start_value null) gibt's die einfache Aktuell/Ziel-Zeile ohne Balken. "Aktuell:"
// ausdrücklich beschriftet, weil eine Karte mehrere Ziele mit unterschiedlichen Ist-Werten zeigen
// kann (z.B. Laufen: Schwellenpace UND Marathon-Vorhersage-Pace).
function GoalProgressBar({ goal, tooltip }: { goal: PerformanceGoal | undefined; tooltip?: string | null }) {
  if (!goal || goal.current_value == null) return null;
  const met = goalIsMet(goal.current_value, goal);
  const unitLabel = unitDisplayLabel(goal.unit);
  const currentLabel = (
    <span className={`goal-progress-current${met ? " goal-met" : ""}`}>
      <span className="goal-progress-current-caption">Aktuell:</span>{" "}
      <span className="goal-progress-current-value">
        {formatGoalValue(goal.current_value, goal.unit)}
        <span className="goal-progress-unit"> {unitLabel}</span>
      </span>
      {met && <Icon name="check" />}
      {tooltip && <InfoTooltip text={tooltip} />}
    </span>
  );

  if (goal.start_value == null || goal.start_value_date == null) {
    return (
      <div className="goal-progress">
        <div className="goal-progress-header">
          <span>{goal.label}</span>
          {currentLabel}
        </div>
        <p className="goal-progress-labels goal-progress-labels-single">
          Ziel: {formatGoalValue(goal.target_value, goal.unit)} {unitLabel}
          {goal.target_date && ` · ${formatShortDate(goal.target_date)}`}
        </p>
      </div>
    );
  }

  const pct = goalProgressPct(goal.start_value, goal.current_value, goal.target_value, goal.unit);
  return (
    <div className="goal-progress">
      <div className="goal-progress-header">
        <span>{goal.label}</span>
        {currentLabel}
      </div>
      <div className="goal-progress-track">
        <div className="goal-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="goal-progress-labels">
        <span>
          {formatGoalValue(goal.start_value, goal.unit)} {unitLabel} · {formatShortDate(goal.start_value_date)}
        </span>
        <span>
          Ziel: <span className="goal-progress-target-value">{formatGoalValue(goal.target_value, goal.unit)}</span>{" "}
          {unitLabel} · {goal.target_date ? formatShortDate(goal.target_date) : "kein Datum"}
        </span>
      </div>
    </div>
  );
}

// Echter Garmin Race-Predictor (garmin_race_predictions) - die einzige Wettkampf-Prognose in
// dieser App, die direkt von Garmin kommt statt selbst geschätzt zu sein (siehe CyclingPredictions
// unten für den Kontrast). Zielzeit-Vergleich nutzt das bestehende marathon_pace-Ziel (Pace * 42,195
// km), keine zusätzliche Zielzeit-Erfassung nötig.
function RunRacePredictions({
  predictions,
  marathonGoal,
}: {
  predictions: RacePredictions | null;
  marathonGoal: PerformanceGoal | undefined;
}) {
  const rows: { label: string; time: number | null; distanceKm: number }[] = [
    { label: "5 km", time: predictions?.time_5k ?? null, distanceKm: 5 },
    { label: "10 km", time: predictions?.time_10k ?? null, distanceKm: 10 },
    { label: "Halbmarathon", time: predictions?.time_half_marathon ?? null, distanceKm: 21.0975 },
    { label: "Marathon", time: predictions?.time_marathon ?? null, distanceKm: 42.195 },
  ];
  const hasData = rows.some((r) => r.time != null);
  if (!hasData) {
    return <p className="week-rationale">Noch keine Renn-Vorhersage von Garmin verfügbar.</p>;
  }

  const marathonTargetSeconds = marathonGoal ? marathonGoal.target_value * 42.195 : null;
  const marathonDeltaSeconds =
    marathonTargetSeconds != null && predictions?.time_marathon != null
      ? predictions.time_marathon - marathonTargetSeconds
      : null;

  return (
    <div className="race-prediction-list">
      {rows.map(
        (row) =>
          row.time != null && (
            <div key={row.label} className="race-prediction-row">
              <span className="race-prediction-label">{row.label}</span>
              <span className="race-prediction-time">{formatDuration(row.time)}</span>
              <span className="race-prediction-pace">{formatPace(row.time / row.distanceKm)}</span>
            </div>
          )
      )}
      {marathonDeltaSeconds != null && marathonTargetSeconds != null && (
        <p className={`week-rationale race-prediction-note${marathonDeltaSeconds <= 0 ? " goal-met" : ""}`}>
          {marathonDeltaSeconds > 0 ? (
            <>
              <Icon name="warning" /> Noch +{formatDuration(marathonDeltaSeconds)} über Zielzeit (
              {formatDuration(marathonTargetSeconds)})
            </>
          ) : (
            <>
              <Icon name="check" /> Aktuell unter Zielzeit ({formatDuration(marathonTargetSeconds)})
            </>
          )}
        </p>
      )}
    </div>
  );
}

// Kein Garmin-Pendant zum Lauf-Race-Predictor fürs Rad - Schätzung aus dem eigenen Wirkungsgrad,
// siehe backend/routers/performance.py::get_cycling_prediction. sample_size macht transparent,
// wie belastbar die Schätzung gerade ist (wird mit mehr Fahrten automatisch genauer).
function CyclingRacePredictions({ prediction }: { prediction: CyclingPrediction | null }) {
  if (!prediction || prediction.sample_size === 0) {
    return <p className="week-rationale">Noch nicht genug Rad-Aktivitäten mit Leistungsdaten für eine Schätzung.</p>;
  }
  return (
    <div className="race-prediction-list">
      {prediction.scenarios.map(
        (s) =>
          s.estimated_duration_seconds != null && (
            <div key={s.key} className="race-prediction-row">
              <span className="race-prediction-label">
                {s.label} ({s.distance_km.toFixed(0)} km)
              </span>
              <span className="race-prediction-time">{formatDuration(s.estimated_duration_seconds)}</span>
              <span className="race-prediction-pace">
                {s.estimated_speed_kmh != null ? `${s.estimated_speed_kmh.toFixed(1)} km/h` : "–"}
              </span>
            </div>
          )
      )}
      <p className="week-rationale">
        Grobe Schätzung aus {prediction.sample_size} eigenen Fahrten
        {prediction.efficiency_kmh_per_watt != null && ` (Ø ${prediction.efficiency_kmh_per_watt.toFixed(3)} km/h pro Watt)`} -
        wird mit mehr Fahrten belastbarer, Wind/Steigung nicht berücksichtigt.
      </p>
    </div>
  );
}

function RunPerformanceCard({
  thresholds,
  goals,
  racePredictions,
}: {
  thresholds: Thresholds | null;
  goals: PerformanceGoal[];
  racePredictions: RacePredictions | null;
}) {
  const thresholdGoal = goals.find((g) => g.key === "run_threshold_pace");
  const marathonGoal = goals.find((g) => g.key === "marathon_pace");
  const halbmarathonGoal = goals.find((g) => g.key === "halbmarathon_pace");
  return (
    <div className="card performance-card performance-sport-card">
      <h3>Laufen</h3>

      <Subsection title="Diagnostik">
        <div className="performance-diagnostics-row">
          <DiagnosticItem
            label="VO2max"
            value={thresholds?.vo2max_running != null ? `${thresholds.vo2max_running}` : "–"}
            unit={thresholds?.vo2max_running != null ? "ml/kg/min" : undefined}
            date={thresholds?.vo2max_running_date}
          />
          <DiagnosticItem
            label="Schwellen-HF"
            value={thresholds?.run_threshold_hr != null ? `${thresholds.run_threshold_hr}` : "–"}
            unit={thresholds?.run_threshold_hr != null ? "bpm" : undefined}
            date={thresholds?.run_threshold_date}
          />
          <DiagnosticItem
            label="Schwellenpace"
            value={
              thresholds?.run_threshold_pace_sec_per_km != null
                ? formatSecondsToPace(thresholds.run_threshold_pace_sec_per_km)
                : "–"
            }
            unit={thresholds?.run_threshold_pace_sec_per_km != null ? "min/km" : undefined}
            date={thresholds?.run_threshold_date}
          />
        </div>
      </Subsection>

      <Subsection title="Ziel-Tracking & Fortschritt">
        <GoalProgressBar goal={thresholdGoal} />
        <GoalProgressBar goal={marathonGoal} />
        <GoalProgressBar goal={halbmarathonGoal} />
      </Subsection>

      <Subsection title="Wettkampf-Prognose">
        <RunRacePredictions predictions={racePredictions} marathonGoal={marathonGoal} />
      </Subsection>
    </div>
  );
}

function BikePerformanceCard({
  thresholds,
  goals,
  cyclingPrediction,
}: {
  thresholds: Thresholds | null;
  goals: PerformanceGoal[];
  cyclingPrediction: CyclingPrediction | null;
}) {
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
    <div className="card performance-card performance-sport-card">
      <h3>Rad</h3>

      <Subsection title="Diagnostik">
        <div className="performance-diagnostics-row">
          <DiagnosticItem
            label="VO2max"
            value={thresholds?.vo2max_cycling != null ? `${thresholds.vo2max_cycling}` : "–"}
            unit={thresholds?.vo2max_cycling != null ? "ml/kg/min" : undefined}
            date={thresholds?.vo2max_cycling_date}
          />
          {/* cycling_threshold_hr stammt aus derselben Garmin-Zeile wie run_threshold_date (siehe
              ThresholdsResponse in backend/routers/performance.py) - kein eigenes Datumsfeld. */}
          <DiagnosticItem
            label="Schwellen-HF"
            value={thresholds?.cycling_threshold_hr != null ? `${thresholds.cycling_threshold_hr}` : "–"}
            unit={thresholds?.cycling_threshold_hr != null ? "bpm" : undefined}
            date={thresholds?.run_threshold_date}
          />
          <DiagnosticItem
            label="FTP Leistung"
            value={thresholds?.ftp_watts != null ? `${thresholds.ftp_watts}` : "–"}
            unit={thresholds?.ftp_watts != null ? "W" : undefined}
            date={thresholds?.ftp_date}
          />
        </div>
      </Subsection>

      <Subsection title="Ziel-Tracking & Fortschritt">
        <GoalProgressBar goal={ftpGoal} tooltip={ftpTooltip} />
      </Subsection>

      <Subsection title="Wettkampf-Prognose">
        <CyclingRacePredictions prediction={cyclingPrediction} />
      </Subsection>
    </div>
  );
}

function SwimPerformanceCard({ swim, goals }: { swim: SwimDiagnostics | null; goals: PerformanceGoal[] }) {
  const swimGoal = goals.find((g) => g.key === "swim_pace_100m");
  const hasData = swim?.swolf != null || swim?.pace_sec_per_100m != null;

  return (
    <div className="card performance-card performance-sport-card">
      <h3>Schwimmen</h3>

      <Subsection title="Diagnostik">
        {hasData ? (
          <div className="performance-diagnostics-row">
            <DiagnosticItem
              label="SWOLF (Pool)"
              value={swim?.swolf != null ? `${swim.swolf}` : "–"}
              date={swim?.date}
            />
            <DiagnosticItem
              label="Ø-Pace (Pool)"
              value={swim?.pace_sec_per_100m != null ? formatSecondsToPace(swim.pace_sec_per_100m) : "–"}
              unit={swim?.pace_sec_per_100m != null ? "min/100m" : undefined}
              date={swim?.date}
            />
          </div>
        ) : (
          <p className="week-rationale">Noch keine Schwimm-Aktivität mit Pace-Daten synchronisiert.</p>
        )}
      </Subsection>

      <Subsection title="Ziel-Tracking & Fortschritt">
        {swimGoal ? (
          <GoalProgressBar goal={swimGoal} />
        ) : (
          <p className="week-rationale">Noch kein Schwimm-Ziel angelegt (Einstellungen &rarr; Leistungsziele).</p>
        )}
      </Subsection>
    </div>
  );
}

// Gemini-Einschätzung zur Erreichbarkeit der Ziele + Tipps (siehe performance_insight.py) - volle
// Kartenbreite oben auf der Seite, da sie über alle Sportart-Karten hinweg einordnet statt zu
// einer einzelnen zu gehören. .sleep-insight-text ist bewusst generisch benannt (siehe
// App.css-Kommentar) und wird hier ohne die dort übliche Chart-Flex-Zeile wiederverwendet.
function GoalsInsightCard({ insight, loading }: { insight: PerformanceGoalsInsight | null; loading: boolean }) {
  return (
    <div className="card performance-card">
      <h3>Einschätzung zu deinen Zielen</h3>
      {loading && !insight ? (
        <p className="week-rationale">Lade Einschätzung…</p>
      ) : insight ? (
        <p className="sleep-insight-text">{insight.insight_text}</p>
      ) : (
        <p className="week-rationale">
          Noch keine Leistungsziele hinterlegt (Einstellungen &rarr; Leistungsziele).
        </p>
      )}
    </div>
  );
}

function PerformanceView() {
  const today = todayIso();
  const [loadStatus, setLoadStatus] = useState<LoadStatus | null>(null);
  const [ctlTrend, setCtlTrend] = useState<CtlTrendPoint[]>([]);
  const [thresholds, setThresholds] = useState<Thresholds | null>(null);
  const [goals, setGoals] = useState<PerformanceGoal[]>([]);
  const [goalsInsight, setGoalsInsight] = useState<PerformanceGoalsInsight | null>(null);
  const [goalsInsightLoading, setGoalsInsightLoading] = useState(false);
  const [racePredictions, setRacePredictions] = useState<RacePredictions | null>(null);
  const [cyclingPrediction, setCyclingPrediction] = useState<CyclingPrediction | null>(null);
  const [swim, setSwim] = useState<SwimDiagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchLoadStatus(today)
      .then(setLoadStatus)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchCtlTrend()
      .then((res) => setCtlTrend(res.points))
      .catch(() => setCtlTrend([]));
    fetchThresholds()
      .then(setThresholds)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchPerformanceGoals()
      .then(setGoals)
      .catch(() => setGoals([]));
    fetchRacePredictions()
      .then(setRacePredictions)
      .catch(() => setRacePredictions(null));
    fetchCyclingPrediction()
      .then(setCyclingPrediction)
      .catch(() => setCyclingPrediction(null));
    fetchSwimDiagnostics()
      .then(setSwim)
      .catch(() => setSwim(null));
  }, [today]);

  // Erst nach Laden der Ziele - kein Gemini-Call, solange (noch) keine Ziele hinterlegt sind
  // (gleiches Gating-Prinzip wie die Trend-Einschätzung auf der Körper-Seite).
  useEffect(() => {
    if (goals.length === 0) return;
    setGoalsInsightLoading(true);
    fetchPerformanceGoalsInsight()
      .then(setGoalsInsight)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setGoalsInsightLoading(false));
  }, [goals.length]);

  return (
    <div className="today-view performance-view">
      {error && <p className="error-banner">Fehler: {error}</p>}

      <section>
        <GoalsInsightCard insight={goalsInsight} loading={goalsInsightLoading} />
      </section>

      <section>
        <div className="performance-row">
          <LoadStatusCard loadStatus={loadStatus} ctlTrend={ctlTrend} />
          <LoadFocusBars loadStatus={loadStatus} />
        </div>
      </section>

      <section>
        <div className="performance-row">
          <RunPerformanceCard thresholds={thresholds} goals={goals} racePredictions={racePredictions} />
          <BikePerformanceCard thresholds={thresholds} goals={goals} cyclingPrediction={cyclingPrediction} />
          <SwimPerformanceCard swim={swim} goals={goals} />
        </div>
      </section>
    </div>
  );
}

export default PerformanceView;
