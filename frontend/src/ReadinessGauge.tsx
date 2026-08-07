import { Doughnut } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip } from "chart.js";
import { useCssVar } from "./useCssVar";

ChartJS.register(ArcElement, Tooltip);

const LEVEL_COLORS: Record<string, string> = {
  LOW: "#e5484d",
  MODERATE: "#f5a623",
  HIGH: "#3dd68c",
};

const LEVEL_LABELS_DE: Record<string, string> = {
  LOW: "Niedrig",
  MODERATE: "Mittel",
  HIGH: "Hoch",
};

// Ersetzt die frühere handgerollte SVG-Ringanzeige durch einen Chart.js-Doughnut (2 Segmente:
// Score + Rest), Mittentext als HTML-Overlay statt Canvas-Text (einfacher, folgt normalen
// CSS-Text-Tokens statt Canvas-fillStyle). --border/--accent werden per useCssVar aufgelöst, da
// Canvas var() nicht selbst auflösen kann (siehe useCssVar.ts-Kommentar).
//
// Generisch gehalten (statusKey/colorMap/labelMap/caption statt fest auf "level"), weil die
// Schlaf-Seite (SleepScoreGauge, SleepView.tsx) exakt dieselbe Optik braucht, nur mit Garmins
// Sleep-Score-Qualifiern (EXCELLENT/GOOD/FAIR/POOR) statt Readiness-Levels (LOW/MODERATE/HIGH).
export function ScoreGauge({
  score,
  statusKey,
  colorMap,
  labelMap,
  caption,
}: {
  score: number | null;
  statusKey: string | null;
  colorMap: Record<string, string>;
  labelMap: Record<string, string>;
  caption: string;
}) {
  const trackColor = useCssVar("--border");
  const accentColor = useCssVar("--accent");
  const upperKey = statusKey?.toUpperCase() ?? null;
  const color = (upperKey && colorMap[upperKey]) || accentColor;
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score));

  return (
    <div className="readiness-dial">
      <div className="readiness-gauge-canvas">
        <Doughnut
          data={{
            datasets: [
              {
                data: [pct, 100 - pct],
                backgroundColor: [color, trackColor],
                borderWidth: 0,
              },
            ],
          }}
          options={{
            cutout: "78%",
            // Chart.js' Default (rotation:0) beginnt bereits um 12 Uhr im Uhrzeigersinn - die
            // vorherigen -90 verschoben den Start um 90° gegen den Uhrzeigersinn auf 9 Uhr.
            rotation: 0,
            circumference: 360,
            animation: false,
            events: [],
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
          }}
        />
        <div className="readiness-gauge-center">
          <div className="readiness-gauge-score">{score ?? "–"}</div>
          <div className="readiness-gauge-caption">{caption}</div>
        </div>
      </div>
      {upperKey && (
        // Gleiche Optik wie .status-pill (Text-/Randfarbe + halbtransparente Füllung derselben
        // Farbe) - hier dynamisch pro Status statt fest auf --accent, da die Stufen
        // unterschiedliche Farben brauchen.
        <span className="day-score-pill" style={{ color, borderColor: color, backgroundColor: `${color}1a` }}>
          {labelMap[upperKey] ?? statusKey}
        </span>
      )}
    </div>
  );
}

function ReadinessGauge({ score, level }: { score: number | null; level: string | null }) {
  return (
    <ScoreGauge score={score} statusKey={level} colorMap={LEVEL_COLORS} labelMap={LEVEL_LABELS_DE} caption="DAY SCORE" />
  );
}

export default ReadinessGauge;
