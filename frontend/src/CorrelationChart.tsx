import { Chart as ChartJSComponent } from "react-chartjs-2";
import {
  Chart as ChartJS,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  ScatterController,
  LineController,
  Tooltip,
  Legend,
} from "chart.js";
import { BoxAndWiskers, BoxPlotController } from "@sgratzl/chartjs-chart-boxplot";
import type { CorrelationStats, CorrelationStrength } from "./api";
import Icon from "./Icon";
import { useCssVar } from "./useCssVar";

// Gemeinsames Korrelations-Chart-Modul für Schlaf- und Körper-Seite (siehe SleepView.tsx/
// BodyView.tsx) - Scatter mit Regressionsgerade + Stärke-Badge, sowie ein echtes Boxplot für
// Gruppenvergleiche (z.B. "späte Einheit"). Statistik (r/Regression/Stärke) kommt IMMER vom
// Backend (correlation_stats.py) - hier wird nichts nachgerechnet, nur dargestellt.
// ScatterController + LineController explizit nötig: die generische react-chartjs-2 <Chart>-
// Komponente registriert sie (anders als die dedizierte <Scatter>-Komponente) nicht automatisch.
ChartJS.register(
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  ScatterController,
  LineController,
  Tooltip,
  Legend,
  BoxPlotController,
  BoxAndWiskers,
);

// Gleicher Wert wie correlation_stats.MIN_CORRELATION_SAMPLE_SIZE (Backend) - hier nur als
// Fallback/Anzeige-Schwelle für Charts ohne eigenes stats-Objekt (z.B. Boxplot-Gruppen, die
// serverseitig keinen eigenen Pearson-r haben). Kein Settings-UI, gleiche Konvention wie alle
// anderen Schwellenwerte dieser App.
export const MIN_CORRELATION_SAMPLE_SIZE = 10;

function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="info-tooltip" title={text} tabIndex={0}>
      <Icon name="info" />
    </span>
  );
}

const STRENGTH_LABEL_DE: Record<CorrelationStrength, string> = {
  none: "Kein Zusammenhang",
  weak: "Schwach",
  moderate: "Moderat",
  strong: "Stark",
};

// Badge-Farbe zeigt NUR die statistische Stärke, nie die Richtung/Wünschbarkeit - bewusst nie Rot
// (das ist app-weit für echte Warnzustände reserviert, siehe .readiness-factor-dot-poor). Ein
// starker, aber für den Athleten guter Zusammenhang soll nicht alarmierend aussehen.
function badgeColor(strength: CorrelationStrength, accentColor: string, borderColor: string): string {
  if (strength === "strong") return accentColor;
  if (strength === "moderate") return "#f5a623";
  return borderColor;
}

function correlationLabel(stats: CorrelationStats): string {
  if (stats.r == null) {
    return `n=${stats.n} · zu wenig Varianz für eine Korrelation`;
  }
  const strengthDe = STRENGTH_LABEL_DE[stats.strength];
  const directionDe = stats.direction === "positive" ? "positiv" : stats.direction === "negative" ? "negativ" : "";
  const label = stats.strength === "none" ? strengthDe : `${strengthDe} ${directionDe}`;
  return `r = ${stats.r.toFixed(2)} | ${label}`;
}

export function CorrelationBadge({ stats }: { stats: CorrelationStats }) {
  const accentColor = useCssVar("--accent");
  const borderColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  const color = badgeColor(stats.strength, accentColor, borderColor);
  const strong = stats.strength === "strong" || stats.strength === "moderate";
  return (
    <span
      className="correlation-badge"
      style={{ borderColor: color, color: strong ? color : textColor }}
      title="Farbe zeigt nur die statistische Stärke, nicht ob der Zusammenhang wünschenswert ist."
    >
      {correlationLabel(stats)}
    </span>
  );
}

// --- Scatter mit optionaler Regressionsgerade + Badge ---

export function CorrelationScatter({
  title,
  tooltip,
  points,
  xLabel,
  yLabel,
  yMin,
  yMax,
  color,
  stats,
  formatY,
}: {
  title: string;
  tooltip: string;
  points: { x: number; y: number }[];
  xLabel: string;
  yLabel: string;
  yMin?: number;
  yMax?: number;
  color: string;
  stats?: CorrelationStats;
  // Optionaler Tick-/Tooltip-Formatierer für die y-Achse (z.B. Sekunden/km -> "5:30 min/km") -
  // Rohwerte bleiben die Chart.js-Datenbasis, nur die Anzeige wird formatiert.
  formatY?: (value: number) => string;
}) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");

  // stats.sufficient ist maßgeblich (serverseitig gegen MIN_CORRELATION_SAMPLE_SIZE geprüft) -
  // points.length nur als Fallback, falls ein Chart (noch) ohne stats-Prop aufgerufen wird.
  const sufficient = stats ? stats.sufficient : points.length >= MIN_CORRELATION_SAMPLE_SIZE;
  if (!sufficient) {
    return (
      <div className="hrv-trend-chart-block">
        <div className="hrv-trend-chart-title">{title}</div>
        <p className="week-rationale">
          Noch nicht genug Datenpunkte für eine Auswertung (mind. {MIN_CORRELATION_SAMPLE_SIZE}, aktuell {points.length}).
        </p>
      </div>
    );
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const datasets: any[] = [{ type: "scatter" as const, label: title, data: points, backgroundColor: color, pointRadius: 4 }];
  if (stats && stats.slope != null && stats.intercept != null && points.length > 0) {
    const xs = points.map((p) => p.x);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    datasets.push({
      type: "line" as const,
      label: "Trend",
      data: [
        { x: xMin, y: stats.slope * xMin + stats.intercept },
        { x: xMax, y: stats.slope * xMax + stats.intercept },
      ],
      borderColor: textColor,
      borderWidth: 1.5,
      borderDash: [4, 3],
      pointRadius: 0,
      fill: false,
      tension: 0,
    });
  }

  return (
    <div className="hrv-trend-chart-block">
      <div className="hrv-trend-chart-title correlation-chart-title-row">
        <span>
          {title}
          <InfoTooltip text={tooltip} />
        </span>
        {stats && <CorrelationBadge stats={stats} />}
      </div>
      <div className="hrv-trend-chart-canvas">
        <ChartJSComponent
          type="scatter"
          data={{ datasets }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: {
                title: { display: true, text: xLabel, color: textColor, font: { size: 10 } },
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 } },
              },
              y: {
                title: { display: true, text: yLabel, color: textColor, font: { size: 10 } },
                min: yMin,
                max: yMax,
                grid: { color: gridColor },
                ticks: {
                  color: textColor,
                  font: { size: 10 },
                  maxTicksLimit: 4,
                  callback: (v) => (formatY ? formatY(Number(v)) : String(v)),
                },
              },
            },
            plugins: {
              legend: { display: false },
              tooltip: {
                enabled: true,
                padding: 6,
                titleFont: { size: 11 },
                bodyFont: { size: 11 },
                filter: (item) => item.dataset.label !== "Trend",
                ...(formatY
                  ? {
                      callbacks: {
                        label: (item) =>
                          `${xLabel}: ${item.parsed.x} · ${yLabel}: ${item.parsed.y == null ? "–" : formatY(item.parsed.y)}`,
                      },
                    }
                  : {}),
              },
            },
          }}
        />
      </div>
    </div>
  );
}

// --- Boxplot für Gruppenvergleiche (z.B. "späte Einheit ja/nein") ---

export function CorrelationBoxplot({
  title,
  tooltip,
  yLabel,
  groups,
  color,
}: {
  title: string;
  tooltip: string;
  yLabel: string;
  groups: { label: string; values: number[] }[];
  color: string;
}) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");

  const insufficientGroup = groups.length === 0 || groups.some((g) => g.values.length < MIN_CORRELATION_SAMPLE_SIZE);
  if (insufficientGroup) {
    const counts = groups.map((g) => `${g.label}: n=${g.values.length}`).join(", ");
    return (
      <div className="hrv-trend-chart-block">
        <div className="hrv-trend-chart-title">{title}</div>
        <p className="week-rationale">
          Noch nicht genug Datenpunkte je Gruppe für eine Auswertung (mind. {MIN_CORRELATION_SAMPLE_SIZE} je Gruppe
          {counts ? `, aktuell ${counts}` : ""}).
        </p>
      </div>
    );
  }

  return (
    <div className="hrv-trend-chart-block">
      <div className="hrv-trend-chart-title">
        {title}
        <InfoTooltip text={tooltip} />
      </div>
      <div className="hrv-trend-chart-canvas">
        <ChartJSComponent
          type="boxplot"
          data={{
            labels: groups.map((g) => `${g.label} (n=${g.values.length})`),
            datasets: [
              {
                label: yLabel,
                data: groups.map((g) => g.values),
                backgroundColor: `${color}33`,
                borderColor: color,
                borderWidth: 1.5,
                itemRadius: 2,
                itemBackgroundColor: color,
              },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 } } },
              y: {
                title: { display: true, text: yLabel, color: textColor, font: { size: 10 } },
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 } },
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
