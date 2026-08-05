import { useEffect, useState } from "react";
import {
  todayIso,
  fetchReadiness,
  fetchTrends,
  fetchRecommendation,
  postOverride,
  type Readiness,
  type Trends,
  type Recommendation,
  type OverrideValue,
} from "./api";
import WeeklyCalendarWidget from "./WeeklyCalendarWidget";

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

function sparklinePoints(values: (number | null)[], width: number, height: number): string {
  const valid = values
    .map((v, i) => (v === null ? null : { i, v }))
    .filter((x): x is { i: number; v: number } => x !== null);
  if (valid.length < 2) return "";
  const min = Math.min(...valid.map((x) => x.v));
  const max = Math.max(...valid.map((x) => x.v));
  const range = max - min || 1;
  const stepX = width / Math.max(values.length - 1, 1);
  return valid
    .map(({ i, v }) => {
      const x = i * stepX;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function ReadinessDial({ score, level }: { score: number | null; level: string | null }) {
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  const dash = circumference * pct;
  const upperLevel = level?.toUpperCase() ?? null;
  const color = (upperLevel && LEVEL_COLORS[upperLevel]) || "var(--accent)";

  return (
    <div className="readiness-dial">
      <svg width="140" height="140" viewBox="0 0 140 140">
        <circle cx="70" cy="70" r={radius} fill="none" stroke="var(--border)" strokeWidth="12" />
        <circle
          cx="70"
          cy="70"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          transform="rotate(-90 70 70)"
        />
        <text x="70" y="66" textAnchor="middle" className="readiness-dial-score">
          {score ?? "–"}
        </text>
        <text x="70" y="88" textAnchor="middle" className="readiness-dial-caption">
          DAY SCORE
        </text>
      </svg>
      {upperLevel && (
        <span className="day-score-pill" style={{ color, borderColor: color }}>
          {LEVEL_LABELS_DE[upperLevel] ?? level}
        </span>
      )}
    </div>
  );
}

function MetricTile({
  label,
  value,
  unit,
  values,
  color,
}: {
  label: string;
  value: number | null;
  unit: string;
  values: (number | null)[];
  color: string;
}) {
  return (
    <div className="card metric-tile">
      <div className="metric-tile-label">{label}</div>
      <div className="metric-tile-value">{value === null ? "–" : `${value}${unit}`}</div>
      <svg className="metric-tile-sparkline" viewBox="0 0 100 30" preserveAspectRatio="none">
        <polyline points={sparklinePoints(values, 100, 30)} fill="none" stroke={color} strokeWidth={2} />
      </svg>
    </div>
  );
}

function RecommendationPanel({
  recommendation,
  loading,
  overriding,
  onOverride,
}: {
  recommendation: Recommendation | null;
  loading: boolean;
  overriding: boolean;
  onOverride: (value: OverrideValue) => void;
}) {
  return (
    <div className="recommendation-panel">
      <div className="recommendation-label">Empfehlung heute</div>
      {recommendation ? (
        <>
          <p className="recommendation-text">{recommendation.recommendation_text}</p>
          <ul className="reasoning-bullets">
            {recommendation.reasoning_bullets.map((bullet, i) => (
              <li key={i}>{bullet}</li>
            ))}
          </ul>
        </>
      ) : (
        <p>{loading ? "Lade Empfehlung…" : "Keine Empfehlung verfügbar."}</p>
      )}
      <div className="override-buttons">
        <button disabled={overriding} onClick={() => onOverride("worse")}>
          Fühle mich schlechter
        </button>
        <button disabled={overriding} onClick={() => onOverride("better")}>
          Fühle mich besser
        </button>
      </div>
    </div>
  );
}

function TodayView() {
  const today = todayIso();
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [trends, setTrends] = useState<Trends | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [recommendationLoading, setRecommendationLoading] = useState(true);
  const [overriding, setOverriding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchReadiness(today)
      .then(setReadiness)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchTrends(today)
      .then(setTrends)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchRecommendation(today)
      .then(setRecommendation)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setRecommendationLoading(false));
  }, [today]);

  async function handleOverride(value: OverrideValue) {
    setOverriding(true);
    try {
      const fresh = await postOverride(today, value);
      setRecommendation(fresh);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setOverriding(false);
    }
  }

  const days = trends?.days ?? [];
  const latest = days[days.length - 1];

  return (
    <div className="today-view">
      {error && <p className="error-banner">Fehler: {error}</p>}
      <div className="card day-score-card">
        <ReadinessDial score={readiness?.score ?? null} level={readiness?.level ?? null} />
        <RecommendationPanel
          recommendation={recommendation}
          loading={recommendationLoading}
          overriding={overriding}
          onOverride={handleOverride}
        />
      </div>
      <div className="metric-tiles">
        <MetricTile
          label="HRV"
          value={latest?.avg_hrv ?? null}
          unit=" ms"
          values={days.map((d) => d.avg_hrv)}
          color="var(--accent)"
        />
        <MetricTile
          label="Schlaf"
          value={latest?.sleep_hours ?? null}
          unit=" h"
          values={days.map((d) => d.sleep_hours)}
          color="#60a5fa"
        />
        <MetricTile
          label="Body Battery"
          value={latest?.body_battery_max ?? null}
          unit=""
          values={days.map((d) => d.body_battery_max)}
          color="#fbbf24"
        />
        <MetricTile
          label="Ruhepuls"
          value={latest?.resting_hr ?? null}
          unit=" bpm"
          values={days.map((d) => d.resting_hr)}
          color="#f87171"
        />
      </div>
      <WeeklyCalendarWidget />
    </div>
  );
}

export default TodayView;
