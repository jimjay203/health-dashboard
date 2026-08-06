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
function ReadinessGauge({ score, level }: { score: number | null; level: string | null }) {
  const trackColor = useCssVar("--border");
  const accentColor = useCssVar("--accent");
  const upperLevel = level?.toUpperCase() ?? null;
  const color = (upperLevel && LEVEL_COLORS[upperLevel]) || accentColor;
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
            rotation: -90,
            circumference: 360,
            animation: false,
            events: [],
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
          }}
        />
        <div className="readiness-gauge-center">
          <div className="readiness-gauge-score">{score ?? "–"}</div>
          <div className="readiness-gauge-caption">DAY SCORE</div>
        </div>
      </div>
      {upperLevel && (
        // Gleiche Optik wie .status-pill (Text-/Randfarbe + halbtransparente Füllung derselben
        // Farbe) - hier dynamisch pro Level statt fest auf --accent, da Low/Moderate/High
        // unterschiedliche Farben brauchen.
        <span className="day-score-pill" style={{ color, borderColor: color, backgroundColor: `${color}1a` }}>
          {LEVEL_LABELS_DE[upperLevel] ?? level}
        </span>
      )}
    </div>
  );
}

export default ReadinessGauge;
