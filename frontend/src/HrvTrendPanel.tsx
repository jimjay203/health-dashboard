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

// Rot = schlechter/auffälliger als Orange (Alert-Tage ggü. normalen Tagen).
const RHR_ALERT_COLOR = "#f87171";
const RHR_NORMAL_COLOR = "#f5a623";
// Deckt sich mit dem ±3bpm-Schwellenwert der RHR-Pille (siehe PerformanceView.tsx) - derselbe
// Wert markiert dort den Pillen-Text, hier die "Alert"-Punkte im Abweichungs-Chart.
const RHR_ALERT_THRESHOLD = 3;

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
          pointBackgroundColor: hrvColor,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: hrvColor,
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
          pointBackgroundColor: hrvColor,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: hrvColor,
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
              x: { display: false },
              y: {
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

function RestingHrDeviationChart({ trend }: { trend: HrvTrendPoint[] }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  const labels = trend.map((p) => formatShortDate(p.date));

  const known = trend.map((p) => p.resting_hr).filter((v): v is number => v !== null);
  const refAvg = known.length ? known.reduce((sum, v) => sum + v, 0) / known.length : null;
  const deviations = trend.map((p) => (p.resting_hr != null && refAvg != null ? p.resting_hr - refAvg : null));

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
                backgroundColor: deviations.map((d) =>
                  d != null && Math.abs(d) >= RHR_ALERT_THRESHOLD ? RHR_ALERT_COLOR : RHR_NORMAL_COLOR
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
              x: { display: false },
              y: {
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
                    return Math.abs(value) >= RHR_ALERT_THRESHOLD ? `Alert: RHR ${formatted}` : formatted;
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
                backgroundColor: accentColor,
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
                grid: { display: false },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 7, autoSkip: true },
              },
              y: {
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 3 },
              },
            },
            plugins: {
              legend: { display: false },
              tooltip: { enabled: true, padding: 6, titleFont: { size: 11 }, bodyFont: { size: 11 } },
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
      <RestingHrDeviationChart trend={trend} />
      <TrainingLoadChart trend={trend} />
    </div>
  );
}

export default HrvTrendPanel;
