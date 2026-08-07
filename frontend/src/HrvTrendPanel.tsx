import { Line, Bar } from "react-chartjs-2";
import {
  Chart as ChartJS,
  LineElement,
  BarElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Tooltip,
  Legend,
} from "chart.js";
import { formatShortDate, type HrvTrendPoint } from "./api";
import { useCssVar } from "./useCssVar";

ChartJS.register(LineElement, BarElement, PointElement, LinearScale, CategoryScale, Tooltip, Legend);

// Ruhepuls-Abweichung ist NICHT symmetrisch zu bewerten: ein niedrigerer Puls als üblich ist bei
// stabiler/hoher HRV physiologisch ein Regenerations-Signal (Superkompensation/Tapering), kein
// Warnsignal - die vorherige reine |Abweichung|>=3-Schwelle hat das fälschlich rot markiert.
//   +1 bpm: neutral (normale Schwankung)
//   +2 bpm: Warnung, mild (Orange)
//   >= +3 bpm: Warnung (Rot - Puls über Baseline: Stress/Infekt/schlechte Regeneration)
//   -1 bpm: neutral
//   <= -2 bpm: positiv (Regeneration/Tapering)
// Liegt die HRV desselben Tages innerhalb der aktuellen Baseline-Bänder (dieselben Werte, die oben
// im HRV-Trend-Chart als Band eingezeichnet sind - kein separat erfundener "HRV-Status pro Tag")
// UND die Abweichung ist negativ, gilt sie unabhängig von der Größe als positiv (deckt z.B. -1 bpm
// bei balancierter HRV mit ab).
// Geteilte Ampel-Farben (Rot/Orange/Hellgrau) - werden sowohl von der Ruhepuls-Abweichung als auch
// vom Trainings-Load-Chart unten verwendet.
const CHART_ALERT_RED = "#f87171";
const CHART_ALERT_ORANGE = "#f5a623";
// Hellgrau statt der (dunkleren) sekundären Textfarbe - neutrale/unauffällige Tage sollen
// gegenüber den farbigen (roten/orangenen/grünen) Balken bewusst zurücktreten.
const CHART_NEUTRAL_GRAY = "#d1d5db";
const RHR_POSITIVE_WARNING_THRESHOLD = 3;
const RHR_POSITIVE_MILD_WARNING_THRESHOLD = 2;
const RHR_REGENERATION_THRESHOLD = -2;

function rhrDeviationColor(d: number, hrvBalanced: boolean, neutralColor: string, positiveColor: string): string {
  if (d >= RHR_POSITIVE_WARNING_THRESHOLD) return CHART_ALERT_RED;
  if (d >= RHR_POSITIVE_MILD_WARNING_THRESHOLD) return CHART_ALERT_ORANGE;
  if (d <= RHR_REGENERATION_THRESHOLD) return positiveColor;
  if (d < 0 && hrvBalanced) return positiveColor;
  return neutralColor;
}

function rhrDeviationTooltipPrefix(d: number, hrvBalanced: boolean): string | null {
  if (d >= RHR_POSITIVE_MILD_WARNING_THRESHOLD) return "Alert";
  if (d <= RHR_REGENERATION_THRESHOLD || (d < 0 && hrvBalanced)) return "Regeneration";
  return null;
}

// Trainings-Load (Tages-Summe von garmin_activities.activity_training_load) - dieselbe
// Grün/Orange/Rot-Ampel wie überall sonst in der App, zusätzlich Hellgrau für echte Ruhe-/
// Rekom-Tage (< 50).
const TRAINING_LOAD_GREEN_MIN = 50;
const TRAINING_LOAD_ORANGE_MIN = 150;
const TRAINING_LOAD_RED_MIN = 250;

function trainingLoadColor(load: number, greenColor: string): string {
  if (load >= TRAINING_LOAD_RED_MIN) return CHART_ALERT_RED;
  if (load >= TRAINING_LOAD_ORANGE_MIN) return CHART_ALERT_ORANGE;
  if (load >= TRAINING_LOAD_GREEN_MIN) return greenColor;
  return CHART_NEUTRAL_GRAY;
}

function trainingLoadTooltipLabel(load: number): string {
  if (load >= TRAINING_LOAD_RED_MIN) return "Sehr hohe Spitzenbelastung (Wettkampf/Longday)";
  if (load >= TRAINING_LOAD_ORANGE_MIN) return "Hohe Belastung (Schlüsseleinheit)";
  if (load >= TRAINING_LOAD_GREEN_MIN) return "Moderate Belastung (Grundlagenbereich)";
  return "Ruhetag / Rekom";
}

// HRV-Punkte unterhalb der Baseline-Untergrenze signalisieren erhöhten Stress/schlechte Erholung -
// je weiter unter der Untergrenze, desto deutlicher die Warnfarbe. Ohne Baseline-Daten
// (baselineLow null, z.B. Gerät noch in der Onboarding-Phase) bleibt der Punkt neutral eingefärbt
// statt einen nicht belegbaren Status vorzutäuschen.
const HRV_BELOW_BASELINE_RED_FACTOR = 0.9; // < 90% der Untergrenze = stark erniedrigt (Rot)

function hrvPointColor(value: number | null, baselineLow: number | null, greenColor: string): string {
  if (value == null || baselineLow == null) return CHART_NEUTRAL_GRAY;
  if (value >= baselineLow) return greenColor;
  if (value >= baselineLow * HRV_BELOW_BASELINE_RED_FACTOR) return CHART_ALERT_ORANGE;
  return CHART_ALERT_RED;
}

// Chart.js reserviert für die y-Achsen-Beschriftung standardmäßig genau so viel Breite, wie das
// jeweils breiteste Tick-Label ("100 ms" vs. "-5 bpm" vs. "400") braucht - dadurch verschiebt sich
// die eigentliche Plot-Fläche zwischen den drei gestapelten Charts, obwohl sie dieselbe Zeitachse
// teilen sollen. afterFit erzwingt in allen drei Charts dieselbe feste Breite, unabhängig vom
// tatsächlichen Label-Text, damit x-Achse/Datenpunkte exakt untereinander stehen. Auch von den
// "Trend (28 Tage)"-Charts auf der Schlaf-Seite (SleepView.tsx) importiert - dieselbe Ausrichtung
// wird dort für Schlafdauer/-phasen/-regelmäßigkeit gebraucht.
export const Y_AXIS_WIDTH_PX = 42;

export function fixedYAxisWidth(scale: { width: number }) {
  scale.width = Y_AXIS_WIDTH_PX;
}

// Chart.js setzt "offset" (Kategorie-Band mit Rand-Puffer, Balken/Punkte sitzen in der Mitte des
// Bands statt direkt auf der Tick-Position) bei Bar-Charts standardmäßig auf true, bei Line-Charts
// auf false - dieselben Datums-Labels landen dadurch an leicht unterschiedlichen x-Positionen.
// Explizit auf allen drei Charts gleich gesetzt (true statt false), damit Linienpunkte und Balken
// exakt übereinander liegen UND der Rand-Puffer bleibt - ohne ihn würden die äußeren Balken an
// beiden Enden nur noch zur Hälfte sichtbar sein (ihr Zentrum säße dann exakt auf der Kanten-Tick-
// Position).
export const X_AXIS_OFFSET = true;

function HrvBaselineChart({
  trend,
  baselineLow,
  baselineUpper,
  hrvColor,
}: {
  trend: HrvTrendPoint[];
  baselineLow: number | null;
  baselineUpper: number | null;
  hrvColor: string;
}) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  const labels = trend.map((p) => formatShortDate(p.date));
  const hasBaseline = baselineLow != null && baselineUpper != null;
  // Punktfarbe pro Tag statt einer einzigen Linienfarbe - grün innerhalb/über der Baseline-
  // Untergrenze, orange/rot je weiter darunter (siehe hrvPointColor-Kommentar). Die Linie selbst
  // bleibt einheitlich in hrvColor, nur die Punkt-Marker wechseln die Farbe.
  const pointColors = trend.map((p) => hrvPointColor(p.avg_hrv, baselineLow, hrvColor));

  const datasets = hasBaseline
    ? [
        {
          label: "Baseline oben",
          data: trend.map(() => baselineUpper),
          borderColor: gridColor,
          borderWidth: 1,
          borderDash: [4, 4],
          pointRadius: 0,
          fill: false,
        },
        {
          label: "HRV-Baseline (aktuell)",
          data: trend.map(() => baselineLow),
          borderColor: gridColor,
          borderWidth: 1,
          borderDash: [4, 4],
          pointRadius: 0,
          fill: 0,
          backgroundColor: `${hrvColor}1a`,
        },
        {
          label: "HRV",
          data: trend.map((p) => p.avg_hrv),
          borderColor: hrvColor,
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: pointColors,
          pointBorderColor: pointColors,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: pointColors,
          tension: 0.3,
          spanGaps: true,
        },
      ]
    : [
        {
          label: "HRV",
          data: trend.map((p) => p.avg_hrv),
          borderColor: hrvColor,
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: pointColors,
          pointBorderColor: pointColors,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: pointColors,
          tension: 0.3,
          spanGaps: true,
        },
      ];

  return (
    <div className="hrv-trend-chart-block">
      <div className="hrv-trend-chart-title">HRV-Trend{hasBaseline ? " · aktuelle Baseline" : ""}</div>
      <div className="hrv-trend-chart-canvas">
        <Line
          data={{ labels, datasets }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: { display: false, offset: X_AXIS_OFFSET },
              y: {
                afterFit: fixedYAxisWidth,
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 4, callback: (v) => `${v} ms` },
              },
            },
            plugins: {
              legend: { display: false },
              tooltip: {
                enabled: true,
                padding: 6,
                titleFont: { size: 11 },
                bodyFont: { size: 11 },
                filter: (item) => item.dataset.label === "HRV",
              },
            },
          }}
        />
      </div>
    </div>
  );
}

function RestingHrDeviationChart({
  trend,
  baselineLow,
  baselineUpper,
}: {
  trend: HrvTrendPoint[];
  baselineLow: number | null;
  baselineUpper: number | null;
}) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  const positiveColor = useCssVar("--accent");
  const labels = trend.map((p) => formatShortDate(p.date));

  const known = trend.map((p) => p.resting_hr).filter((v): v is number => v !== null);
  const refAvg = known.length ? known.reduce((sum, v) => sum + v, 0) / known.length : null;
  const deviations = trend.map((p) => (p.resting_hr != null && refAvg != null ? p.resting_hr - refAvg : null));
  const hasBaseline = baselineLow != null && baselineUpper != null;
  // Pro Tag: liegt die HRV innerhalb der aktuellen Baseline-Bänder (siehe HrvBaselineChart)?
  const hrvBalancedByDay = trend.map(
    (p) => hasBaseline && p.avg_hrv != null && p.avg_hrv >= baselineLow! && p.avg_hrv <= baselineUpper!
  );

  return (
    <div className="hrv-trend-chart-block">
      <div className="hrv-trend-chart-title">
        Ruhepuls-Abweichung{refAvg != null && ` · vs. 28-Tage-Schnitt: ${refAvg.toFixed(0)} bpm`}
      </div>
      <div className="hrv-trend-chart-canvas">
        <Bar
          data={{
            labels,
            datasets: [
              {
                label: "Abweichung",
                data: deviations,
                backgroundColor: deviations.map((d, i) =>
                  d == null ? gridColor : rhrDeviationColor(d, hrvBalancedByDay[i], CHART_NEUTRAL_GRAY, positiveColor)
                ),
                borderRadius: 2,
              },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: { display: false, offset: X_AXIS_OFFSET },
              y: {
                afterFit: fixedYAxisWidth,
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 4, callback: (v) => `${v} bpm` },
              },
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
                    const value = item.parsed.y;
                    if (value == null) return "Keine Daten";
                    const formatted = `${value > 0 ? "+" : ""}${value.toFixed(0)} bpm ggü. Schnitt`;
                    const prefix = rhrDeviationTooltipPrefix(value, hrvBalancedByDay[item.dataIndex]);
                    return prefix ? `${prefix}: RHR ${formatted}` : formatted;
                  },
                },
              },
            },
          }}
        />
      </div>
    </div>
  );
}

function TrainingLoadChart({ trend }: { trend: HrvTrendPoint[] }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  const accentColor = useCssVar("--accent");
  const labels = trend.map((p) => p.date);

  return (
    <div className="hrv-trend-chart-block">
      <div className="hrv-trend-chart-title">Trainings-Load</div>
      <div className="hrv-trend-chart-canvas">
        <Bar
          data={{
            labels: labels.map(formatShortDate),
            datasets: [
              {
                label: "Trainings-Load",
                data: trend.map((p) => p.training_load),
                backgroundColor: trend.map((p) =>
                  p.training_load == null ? gridColor : trainingLoadColor(p.training_load, accentColor)
                ),
                borderRadius: 2,
              },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: {
                offset: X_AXIS_OFFSET,
                grid: { display: false },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 7, autoSkip: true },
              },
              y: {
                afterFit: fixedYAxisWidth,
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 3 },
              },
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
                    const value = item.parsed.y;
                    if (value == null) return "Keine Daten";
                    return `${value.toFixed(0)} - ${trainingLoadTooltipLabel(value)}`;
                  },
                },
              },
            },
          }}
        />
      </div>
    </div>
  );
}

// Kombiniertes 28-Tage-Bilanz-Panel: drei gestapelte Small-Multiples (HRV+Baseline,
// Ruhepuls-Abweichung, Trainings-Load), gemeinsame Zeitachse. Bewusst drei getrennte Charts statt
// eines gemeinsamen (unterschiedliche Einheiten: ms, bpm-Abweichung, Load-Punkte).
function HrvTrendPanel({
  trend,
  baselineLow,
  baselineUpper,
  hrvColor,
}: {
  trend: HrvTrendPoint[];
  baselineLow: number | null;
  baselineUpper: number | null;
  hrvColor: string;
}) {
  return (
    <div className="hrv-trend-panel">
      <HrvBaselineChart trend={trend} baselineLow={baselineLow} baselineUpper={baselineUpper} hrvColor={hrvColor} />
      <RestingHrDeviationChart trend={trend} baselineLow={baselineLow} baselineUpper={baselineUpper} />
      <TrainingLoadChart trend={trend} />
    </div>
  );
}

export default HrvTrendPanel;
