import { formatEnumLabel, type ReadinessOverview } from "./api";
import HrvTrendPanel from "./HrvTrendPanel";
import { useCssVar } from "./useCssVar";

// Kein Garmin-Original-Status für den Ruhepuls (anders als hrv_status) - eigener, abgeleiteter
// Vergleich des heutigen Werts ggü. dem eigenen 7-Tage-Schnitt (resting_hr_7d_avg). Visuell exakt
// wie die HRV-Pille dargestellt (dieselbe .status-pill-Klasse), damit beide Pillen gleich aussehen.
function restingHrPillText(resting: number | null, avg7d: number | null): string | null {
  if (resting == null || avg7d == null) return null;
  const diff = resting - avg7d;
  if (diff >= 3) return "Erhöht ggü. 7-Tage-Schnitt";
  if (diff <= -3) return "Niedrig ggü. 7-Tage-Schnitt";
  return "Im 7-Tage-Schnitt";
}

// "HRV & Ruhepuls" - Headline-Werte + Statuspillen + 28-Tage-Bilanz-Panel (HrvTrendPanel). Auf der
// Heute-Seite ganz oben neben der Trainingsbereitschaft platziert (siehe TodayView.tsx).
function HrvCard({ overview }: { overview: ReadinessOverview | null }) {
  // Canvas kann var(--accent) nicht selbst auflösen (siehe useCssVar.ts) - vorher ging das über
  // die SVG-Sparkline "kostenlos".
  const accentColor = useCssVar("--accent");
  const status = formatEnumLabel(overview?.hrv_status ?? null);
  // Headline zeigt wie bei HRV den Wochenschnitt (resting_hr_7d_avg), nicht den rohen Tageswert -
  // die Pille vergleicht trotzdem weiterhin den heutigen Ist-Wert damit.
  const rhrPillText = restingHrPillText(overview?.resting_hr ?? null, overview?.resting_hr_7d_avg ?? null);
  const trend = overview?.hrv_trend ?? [];

  return (
    <div className="card performance-card performance-card-wide">
      <h3>HRV &amp; Ruhepuls</h3>
      <div className="performance-metric-row">
        <div>
          <div className="performance-metric-value">
            {overview?.avg_hrv != null ? `${overview.avg_hrv} ms` : "–"}
            <span className="performance-metric-caption"> HRV-Wochenschnitt</span>
          </div>
          {status && status !== "None" && <span className="status-pill">{status}</span>}
        </div>
        <div>
          <div className="performance-metric-value">
            {overview?.resting_hr_7d_avg != null ? `${overview.resting_hr_7d_avg} bpm` : "–"}
            <span className="performance-metric-caption"> Ruhepuls-Wochenschnitt</span>
          </div>
          {rhrPillText && <span className="status-pill">{rhrPillText}</span>}
        </div>
      </div>
      {trend.length >= 2 && (
        <HrvTrendPanel
          trend={trend}
          baselineLow={overview?.hrv_baseline_balanced_low ?? null}
          baselineUpper={overview?.hrv_baseline_balanced_upper ?? null}
          hrvColor={accentColor}
        />
      )}
    </div>
  );
}

export default HrvCard;
