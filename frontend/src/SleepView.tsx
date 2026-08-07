import { useEffect, useState } from "react";
import { Line, Bar, Scatter } from "react-chartjs-2";
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
import {
  todayIso,
  formatShortDate,
  formatEnumLabel,
  fetchSleepOverview,
  fetchSleepTrend,
  fetchSleepLevels,
  fetchSleepCorrelationsInsight,
  regenerateSleepCorrelationsInsight,
  fetchSleepTrendInsight,
  regenerateSleepTrendInsight,
  type SleepOverview,
  type SleepTrend,
  type SleepTrendPoint,
  type SleepStage,
  type SleepLevels,
  type SleepCorrelationsInsight,
  type SleepTrendInsight,
} from "./api";
import HabitTrackerCard from "./HabitTrackerCard";
import { fixedYAxisWidth, X_AXIS_OFFSET } from "./HrvTrendPanel";
import Icon from "./Icon";
import { ScoreGauge } from "./ReadinessGauge";
import { useCssVar } from "./useCssVar";

ChartJS.register(LineElement, BarElement, PointElement, LinearScale, CategoryScale, Tooltip, Legend);

// --- Formatierung ---

// sleep_start_local/sleep_end_local sind bereits als lokale ISO-Datetime-Strings vom Backend
// aufbereitet (siehe garmin_service.py::_epoch_ms_local_to_iso) - reines String-Slicing statt
// new Date(), gleiche Konvention wie formatShortDate in api.ts.
function formatClock(isoLocal: string | null): string {
  if (!isoLocal) return "–";
  return isoLocal.slice(11, 16);
}

// Wie formatClock: sleepLevels-Segmente kommen als lokale ISO-Strings ohne Zeitzonen-Suffix vom
// Backend. new Date(isoString) würde das als UTC lesen und riskiert je nach Zeitzone eine
// Zeitverschiebung - stattdessen Komponenten einzeln auslesen und über den Mehrargument-
// Date-Konstruktor (immer lokal, unzweideutig) zusammensetzen.
function parseLocalIso(iso: string): Date {
  return new Date(
    Number(iso.slice(0, 4)),
    Number(iso.slice(5, 7)) - 1,
    Number(iso.slice(8, 10)),
    Number(iso.slice(11, 13)),
    Number(iso.slice(14, 16)),
    Number(iso.slice(17, 19)),
  );
}

function formatHoursMinutes(seconds: number | null): string {
  if (seconds == null) return "–";
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${m}min`;
}

// Garmins eigene 4-stufige Qualifier-Skala (ground-truth: EXCELLENT/GOOD/FAIR bereits in echten
// Daten beobachtet, POOR als plausible vierte Stufe ergänzt - an anderer Stelle in dieser App
// bereits als reales Garmin-Feedback-Level bestätigt). Unbekannte Werte fallen auf formatEnumLabel
// zurück statt nichts anzuzeigen.
const QUALIFIER_LABEL_DE: Record<string, string> = {
  EXCELLENT: "Ausgezeichnet",
  GOOD: "Gut",
  FAIR: "Mittel",
  POOR: "Niedrig",
};

const QUALIFIER_COLOR_CLASS: Record<string, string> = {
  EXCELLENT: "sleep-qualifier-good",
  GOOD: "sleep-qualifier-good",
  FAIR: "sleep-qualifier-fair",
  POOR: "sleep-qualifier-poor",
};

// Daumen-Icon statt Textlabel spart Platz in der Schlafphasen-Legende - "Mittel" hat kein eigenes
// Material-Symbols-Icon, daher thumb_up um 90° gedreht ("zur Seite", siehe .icon-sideways).
// qualifierLabel() bleibt als title-Tooltip auf dem Icon erhalten.
const QUALIFIER_ICON: Record<string, string> = {
  EXCELLENT: "thumb_up",
  GOOD: "thumb_up",
  FAIR: "thumb_up",
  POOR: "thumb_down",
};

const QUALIFIER_ICON_SIDEWAYS: Record<string, boolean> = {
  FAIR: true,
};

function qualifierLabel(raw: string | null): string | null {
  if (!raw) return null;
  return QUALIFIER_LABEL_DE[raw] ?? formatEnumLabel(raw);
}

// Gleiche Grün/Orange/Rot-Systemfarben wie überall sonst auf der Seite (Trend-Charts,
// Qualifier-Badges) - hier als Ring-/Pillenfarbe für den Sleep-Score-Gauge.
const SLEEP_SCORE_QUALIFIER_COLOR: Record<string, string> = {
  EXCELLENT: "#3dd68c",
  GOOD: "#3dd68c",
  FAIR: "#f5a623",
  POOR: "#f87171",
};

// Garmins sleepScoreFeedback/-Insight sind SCREAMING_SNAKE_CASE-Enums - ground-truth-verifiziert
// gegen die real synchronisierten Werte in garmin_sleep_phases (9 Feedback-, 4 Insight-
// Ausprägungen). Unbekannte Werte fallen auf formatEnumLabel zurück statt nichts anzuzeigen.
const SLEEP_FEEDBACK_DE: Record<string, string> = {
  POSITIVE_RECOVERING: "Erholsam",
  POSITIVE_LONG_AND_DEEP: "Lang und tief",
  POSITIVE_OPTIMAL_STRUCTURE: "Optimale Struktur",
  POSITIVE_LONG_AND_RECOVERING: "Lang und erholsam",
  POSITIVE_DEEP: "Tief",
  POSITIVE_CONTINUOUS: "Durchgehend",
  POSITIVE_LONG_AND_REFRESHING: "Lang und erfrischend",
  NEGATIVE_LONG_BUT_NOT_RESTORATIVE: "Lang, aber nicht erholsam",
  NEGATIVE_NOT_ENOUGH_REM: "Zu wenig REM-Schlaf",
};

// NONE ist Garmins eigener "kein zusätzlicher Hinweis"-Wert - zeigt bewusst nichts an (analog zu
// UNKNOWN bei der Trainingsbereitschaft), statt einen nicht vorhandenen Zustand vorzutäuschen.
const SLEEP_INSIGHT_DE: Record<string, string> = {
  POSITIVE_EXERCISE: "Training",
  POSITIVE_RESTFUL_DAY: "Erholsamer Tag",
  POSITIVE_RESTFUL_EVENING: "Erholsamer Abend",
};

function sleepEvaluationText(feedback: string | null, insight: string | null): string | null {
  const parts = [
    feedback ? SLEEP_FEEDBACK_DE[feedback] ?? formatEnumLabel(feedback) : null,
    insight && insight !== "NONE" ? SLEEP_INSIGHT_DE[insight] ?? formatEnumLabel(insight) : null,
  ].filter((p): p is string => Boolean(p));
  return parts.length > 0 ? parts.join(" · ") : null;
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

// --- Letzte Nacht ---

function PhaseBar({ overview }: { overview: SleepOverview }) {
  const deep = overview.deep_sleep_seconds ?? 0;
  const light = overview.light_sleep_seconds ?? 0;
  const rem = overview.rem_sleep_seconds ?? 0;
  const awake = overview.awake_sleep_seconds ?? 0;
  const total = deep + light + rem + awake;
  if (total === 0) return null;
  const segments: { label: string; seconds: number; colorClass: string; qualifier: string | null }[] = [
    { label: "Tief", seconds: deep, colorClass: "sleep-phase-deep", qualifier: overview.deep_qualifier },
    { label: "Kern", seconds: light, colorClass: "sleep-phase-light", qualifier: overview.light_qualifier },
    { label: "REM", seconds: rem, colorClass: "sleep-phase-rem", qualifier: overview.rem_qualifier },
    { label: "Wach", seconds: awake, colorClass: "sleep-phase-awake", qualifier: null },
  ];

  return (
    <div className="sleep-phase-block">
      <div className="sleep-phase-track">
        {segments.map((s) => (
          <div
            key={s.label}
            className={`sleep-phase-segment ${s.colorClass}`}
            style={{ width: `${(s.seconds / total) * 100}%` }}
            title={`${s.label}: ${formatHoursMinutes(s.seconds)}`}
          />
        ))}
      </div>
      <div className="sleep-phase-legend">
        {segments.map((s) => (
          <div key={s.label} className="sleep-phase-legend-item">
            <span className={`sleep-phase-dot ${s.colorClass}`} />
            {s.label} {Math.round((s.seconds / total) * 100)}%
            {s.qualifier && (
              <span
                className={`sleep-qualifier-badge ${QUALIFIER_COLOR_CLASS[s.qualifier] ?? ""}`}
                title={qualifierLabel(s.qualifier) ?? undefined}
              >
                <Icon
                  name={QUALIFIER_ICON[s.qualifier] ?? "thumb_up"}
                  className={QUALIFIER_ICON_SIDEWAYS[s.qualifier] ? "icon-sideways" : ""}
                />
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const SLEEP_OVERVIEW_TOOLTIP =
  "sleep_need ist Garmins persönlich berechneter Schlafbedarf (passt sich an Trainingslast/HRV/" +
  "Schlafhistorie an) - kein fixer 8h-Richtwert. Bettzeit-Empfehlung ist Garmins eigener " +
  "Vorschlag fürs optimale Einschlaffenster, nicht selbst berechnet.";

function SleepOverviewCard({
  date,
  overview,
  levels,
}: {
  date: string;
  overview: SleepOverview | null;
  levels: SleepLevels | null;
}) {
  const isToday = date === todayIso();
  if (!overview || overview.sleep_hours == null) {
    return (
      <div className="card">
        <h3>
          {isToday ? "Letzte Nacht" : "Nacht"}
          <InfoTooltip text={SLEEP_OVERVIEW_TOOLTIP} />
        </h3>
        <p className="week-rationale">Noch keine Schlafdaten für diese Nacht synchronisiert.</p>
      </div>
    );
  }

  const needMet = overview.sleep_need_seconds != null && overview.sleep_hours * 3600 >= overview.sleep_need_seconds;
  const evaluationText = sleepEvaluationText(overview.sleep_score_feedback, overview.sleep_score_insight);
  const bedtime = bedtimeBadge(overview.sleep_start_local, overview.recommended_bedtime_start, overview.recommended_bedtime_end);

  // Nach logischen Paaren geordnet (2-Spalten-Grid, siehe App.css) statt alphabetisch/beliebig:
  // Herz/autonomes Nervensystem, Atmung, Unruhe/Stress, Erholung.
  const diagnostics: { label: string; value: string; unit?: string }[] = [
    { label: "Ruhepuls im Schlaf", value: overview.avg_sleep_hr != null ? `${Math.round(overview.avg_sleep_hr)}` : "–", unit: "bpm" },
    { label: "Overnight-HRV", value: overview.avg_overnight_hrv != null ? `${Math.round(overview.avg_overnight_hrv)}` : "–", unit: "ms" },
    { label: "SpO2 im Schlaf", value: overview.avg_sleep_spo2 != null ? `${Math.round(overview.avg_sleep_spo2)}` : "–", unit: "%" },
    { label: "Atemfrequenz im Schlaf", value: overview.avg_sleep_respiration != null ? `${overview.avg_sleep_respiration.toFixed(1)}` : "–", unit: "/min" },
    { label: "Stress im Schlaf", value: overview.avg_sleep_stress != null ? `${Math.round(overview.avg_sleep_stress)}` : "–" },
    { label: "Unruhige Momente", value: overview.restless_moments_count != null ? `${overview.restless_moments_count}` : "–" },
    { label: "Body Battery Δ", value: overview.body_battery_change != null ? `+${overview.body_battery_change}` : "–" },
    { label: "Hauttemp.-Abweichung", value: overview.avg_skin_temp_deviation_c != null ? `${overview.avg_skin_temp_deviation_c.toFixed(1)}` : "–", unit: "°C" },
  ];

  return (
    <div className="card">
      <h3>
        {isToday ? "Letzte Nacht" : "Nacht"}
        {evaluationText && <span className="tier-kw"> · {evaluationText}</span>}
        <InfoTooltip text={SLEEP_OVERVIEW_TOOLTIP} />
      </h3>

      <div className="sleep-card-body-row">
        <div className="sleep-gauge-col">
          <ScoreGauge
            score={overview.sleep_score}
            statusKey={overview.sleep_score_qualifier}
            colorMap={SLEEP_SCORE_QUALIFIER_COLOR}
            labelMap={QUALIFIER_LABEL_DE}
            caption="SLEEP SCORE"
          />
          <div className="sleep-badges-col">
            <span className={`status-pill${needMet ? "" : " sleep-need-not-met"}`}>
              {needMet ? <Icon name="check" /> : <Icon name="warning" />} Schlafbedarf: {formatHoursMinutes(overview.sleep_need_seconds)}
              {needMet ? " gedeckt" : " nicht gedeckt"}
            </span>
            {bedtime && (
              <span className={`status-pill${bedtime.met ? "" : " sleep-need-not-met"}`}>
                {bedtime.met ? <Icon name="check" /> : <Icon name="warning" />} {bedtime.text}
              </span>
            )}
          </div>
        </div>

        <div className="sleep-diagrams-col">
          <div className="sleep-diagrams-metrics-row">
            <div className="performance-metric-value">
              {formatHoursMinutes(overview.sleep_hours * 3600)}
              <span className="performance-metric-caption"> Schlafdauer</span>
            </div>
            <div className="sleep-bedtime-window">
              <Icon name="bedtime" /> {formatClock(overview.sleep_start_local)} – {formatClock(overview.sleep_end_local)}
            </div>
          </div>
          <SleepLevelsChart levels={levels} />
          <PhaseBar overview={overview} />
        </div>

        <div className="performance-diagnostics-row sleep-diagnostics-col">
          {diagnostics.map((d) => (
            <div key={d.label} className="performance-diagnostic-item">
              <div className="performance-diagnostic-value">
                {d.value}
                {d.unit && d.value !== "–" && <span className="performance-diagnostic-unit"> {d.unit}</span>}
              </div>
              <div className="performance-diagnostic-label">{d.label}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// --- Trend: Schlafdauer vs. persönlichem Bedarf ---

const SLEEP_DURATION_GOOD = "#3dd68c";
const SLEEP_DURATION_MODERATE = "#f5a623";
const SLEEP_DURATION_LOW = "#f87171";
const SLEEP_DURATION_UNKNOWN = "#d1d5db";

function sleepDurationColor(hours: number | null, needSeconds: number | null): string {
  if (hours == null || needSeconds == null || needSeconds === 0) return SLEEP_DURATION_UNKNOWN;
  const pct = (hours * 3600) / needSeconds;
  if (pct >= 1) return SLEEP_DURATION_GOOD;
  if (pct >= 0.85) return SLEEP_DURATION_MODERATE;
  return SLEEP_DURATION_LOW;
}

function SleepDurationChart({ points }: { points: SleepTrendPoint[] }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");

  return (
    <div className="hrv-trend-chart-block sleep-duration-chart-block">
      <div className="hrv-trend-chart-title">
        Schlafdauer vs. persönlichem Bedarf
        <InfoTooltip text="Farbe zeigt, wie nah die tatsächliche Schlafdauer an Garmins persönlich berechnetem Schlafbedarf dieser Nacht liegt (Grün ≥100%, Orange ≥85%, Rot darunter)." />
      </div>
      <div className="hrv-trend-chart-canvas">
        <Bar
          data={{
            labels: points.map((p) => formatShortDate(p.date)),
            datasets: [
              {
                label: "Schlafdauer",
                data: points.map((p) => p.sleep_hours),
                backgroundColor: points.map((p) => sleepDurationColor(p.sleep_hours, p.sleep_need_seconds)),
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
              y: {
                afterFit: fixedYAxisWidth,
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 4, callback: (v) => `${v}h` },
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
                    const p = points[item.dataIndex];
                    const need = p.sleep_need_seconds != null ? ` (Bedarf ${formatHoursMinutes(p.sleep_need_seconds)})` : "";
                    return `${formatHoursMinutes((p.sleep_hours ?? 0) * 3600)}${need}`;
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

// --- Trend: Schlafphasen-Verteilung ---

const PHASE_DEEP_COLOR = "#6366f1";
const PHASE_LIGHT_COLOR = "#38bdf8";
const PHASE_REM_COLOR = "#a78bfa";
const PHASE_AWAKE_COLOR = "#fb7185";

// --- Letzte Nacht: minutengenauer Phasenverlauf (Apple-Health-Vorbild) ---

// Reihenfolge oben -> unten wie im Apple-Health-Vorbild. Gleiche Deep/Light/REM-Farben wie die
// Trend-Charts weiter unten auf der Seite (Konsistenz).
const SLEEP_LEVEL_ROWS: SleepStage[] = ["awake", "rem", "light", "deep"];
const SLEEP_LEVEL_LABEL_DE: Record<SleepStage, string> = { awake: "Wach", rem: "REM", light: "Kern", deep: "Tief" };
const SLEEP_LEVEL_COLOR: Record<SleepStage, string> = {
  deep: PHASE_DEEP_COLOR,
  light: PHASE_LIGHT_COLOR,
  rem: PHASE_REM_COLOR,
  awake: PHASE_AWAKE_COLOR,
};

function SleepLevelsChart({ levels }: { levels: SleepLevels | null }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");

  if (!levels || levels.segments.length === 0) return null;
  const segments = levels.segments;
  const start0 = parseLocalIso(segments[0].start_local).getTime();
  const toMinutes = (iso: string) => (parseLocalIso(iso).getTime() - start0) / 60000;
  const totalMinutes = toMinutes(segments[segments.length - 1].end_local);
  const clockLabel = (minutesOffset: number) => {
    const d = new Date(start0 + minutesOffset * 60000);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  // Chart.js unterstützt mehrere Bars pro Kategorie-Zeile über {x:[start,end], y:Kategorie}-
  // Datenpunkte (Gantt-Muster) - react-chartjs-2s Default-Typisierung für 'bar' kennt dieses
  // Objektformat nicht, daher hier bewusst als any übergeben statt die Typen zu erzwingen.
  const chartData = {
    labels: SLEEP_LEVEL_ROWS.map((s) => SLEEP_LEVEL_LABEL_DE[s]),
    datasets: [
      {
        label: "Schlafphase",
        data: segments.map((seg) => ({
          x: [toMinutes(seg.start_local), toMinutes(seg.end_local)],
          y: SLEEP_LEVEL_LABEL_DE[seg.stage],
        })),
        backgroundColor: segments.map((seg) => SLEEP_LEVEL_COLOR[seg.stage]),
        borderRadius: 8,
        // Chart.js rundet bei Bar-Charts standardmäßig nur die vom Nullpunkt entfernte Seite ab
        // (borderSkipped: "start") - bei Floating-Bars gibt es aber keinen Nullpunkt-Bezug, daher
        // hier explizit beide Enden abrunden.
        borderSkipped: false,
        barThickness: 20,
      },
    ],
  };

  return (
    <div className="sleep-levels-chart-block">
      <div className="hrv-trend-chart-title">Schlafverlauf</div>
      <div className="sleep-levels-chart-canvas">
        <Bar
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          data={chartData as any}
          options={{
            indexAxis: "y" as const,
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: {
                type: "linear",
                min: 0,
                max: totalMinutes,
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 6, callback: (v) => clockLabel(Number(v)) },
              },
              y: {
                type: "category",
                labels: SLEEP_LEVEL_ROWS.map((s) => SLEEP_LEVEL_LABEL_DE[s]),
                offset: true,
                grid: { display: false },
                ticks: { color: textColor, font: { size: 11 } },
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
                  title: (items) => SLEEP_LEVEL_LABEL_DE[segments[items[0].dataIndex].stage],
                  label: (item) => {
                    const seg = segments[item.dataIndex];
                    return `${formatClock(seg.start_local)} – ${formatClock(seg.end_local)}`;
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

function SleepPhaseTrendChart({ points }: { points: SleepTrendPoint[] }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");

  return (
    <div className="hrv-trend-chart-block">
      <div className="hrv-trend-chart-title">Schlafphasen-Verteilung</div>
      <div className="hrv-trend-chart-canvas">
        <Bar
          data={{
            labels: points.map((p) => formatShortDate(p.date)),
            datasets: [
              { label: "Tief", data: points.map((p) => p.deep_pct), backgroundColor: PHASE_DEEP_COLOR, stack: "phases" },
              { label: "Kern", data: points.map((p) => p.light_pct), backgroundColor: PHASE_LIGHT_COLOR, stack: "phases" },
              { label: "REM", data: points.map((p) => p.rem_pct), backgroundColor: PHASE_REM_COLOR, stack: "phases" },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: { offset: X_AXIS_OFFSET, stacked: true, grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 7, autoSkip: true } },
              y: {
                stacked: true,
                max: 100,
                afterFit: fixedYAxisWidth,
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 4, callback: (v) => `${v}%` },
              },
            },
            plugins: {
              legend: { display: true, position: "bottom", labels: { color: textColor, font: { size: 10 }, boxWidth: 10, padding: 12 } },
              tooltip: { enabled: true, padding: 6, titleFont: { size: 11 }, bodyFont: { size: 11 } },
            },
          }}
        />
      </div>
    </div>
  );
}

// --- Trend: Regelmäßigkeit (Bettzeit/Aufwachzeit) ---

// Skala "Stunden seit dem Mittag des Vortages" (0=12:00, 12=Mitternacht, 24=12:00 des Folgetages) -
// vermeidet den Sprung um Mitternacht, den eine reine 0-24-Uhr-Skala für Bettzeiten hätte (22:00 und
// 00:30 lägen sonst an entgegengesetzten Enden der Achse statt nebeneinander).
function hoursAfterNoon(isoLocal: string | null): number | null {
  if (!isoLocal) return null;
  const hour = Number(isoLocal.slice(11, 13));
  const minute = Number(isoLocal.slice(14, 16));
  const h = hour + minute / 60;
  return h < 12 ? h + 12 : h - 12;
}

function clockFromHoursAfterNoon(value: number): string {
  const normalized = ((value % 24) + 24) % 24;
  const clockHour = Math.floor((normalized + 12) % 24);
  const clockMinute = Math.round((normalized % 1) * 60);
  return `${String(clockHour).padStart(2, "0")}:${String(clockMinute).padStart(2, "0")}`;
}

// Wie hoursAfterNoon, aber für die bereits als "HH:MM"-Uhrzeit formatierten
// recommended_bedtime_start/-end-Felder (siehe backend/routers/sleep.py::_mins_to_clock) statt
// einen vollen ISO-Datetime-String.
function hoursAfterNoonFromClock(hhmm: string | null): number | null {
  if (!hhmm) return null;
  const [hour, minute] = hhmm.split(":").map(Number);
  const h = hour + minute / 60;
  return h < 12 ? h + 12 : h - 12;
}

// Vergleicht die tatsächliche Bettzeit mit Garmins empfohlenem Fenster (analog zum
// "Schlafbedarf gedeckt/nicht gedeckt"-Badge). Früher als empfohlen gilt als eingehalten (kein
// Grund zur Warnung), nur später als das Fenster gilt als "nicht eingehalten".
function bedtimeBadge(
  sleepStartLocal: string | null,
  recommendedStart: string | null,
  recommendedEnd: string | null,
): { text: string; met: boolean } | null {
  const actual = hoursAfterNoon(sleepStartLocal);
  const start = hoursAfterNoonFromClock(recommendedStart);
  const end = hoursAfterNoonFromClock(recommendedEnd);
  if (actual == null || start == null || end == null) return null;
  if (actual >= start && actual <= end) {
    return { text: "Bettzeit eingehalten", met: true };
  }
  if (actual < start) {
    const deltaMinutes = Math.round((start - actual) * 60);
    return { text: `Bettzeit: ${deltaMinutes} Min früher als empf.`, met: true };
  }
  const deltaMinutes = Math.round((actual - end) * 60);
  return { text: `Bettzeit: ${deltaMinutes} Min später als empf.`, met: false };
}

function SleepRegularityChart({ points }: { points: SleepTrendPoint[] }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  const accentColor = useCssVar("--accent");

  return (
    <div className="hrv-trend-chart-block sleep-regularity-chart-block">
      <div className="hrv-trend-chart-title">
        Regelmäßigkeit
        <InfoTooltip text="Bettzeit/Aufwachzeit pro Nacht - je enger beieinander, desto regelmäßiger dein Schlafrhythmus." />
      </div>
      <div className="hrv-trend-chart-canvas">
        <Line
          data={{
            labels: points.map((p) => formatShortDate(p.date)),
            datasets: [
              {
                label: "Bettzeit",
                data: points.map((p) => hoursAfterNoon(p.sleep_start_local)),
                borderColor: PHASE_DEEP_COLOR,
                backgroundColor: PHASE_DEEP_COLOR,
                pointRadius: 3,
                pointBackgroundColor: PHASE_DEEP_COLOR,
                borderWidth: 2,
                tension: 0,
                spanGaps: true,
              },
              {
                label: "Aufwachzeit",
                data: points.map((p) => hoursAfterNoon(p.sleep_end_local)),
                borderColor: accentColor,
                backgroundColor: accentColor,
                pointRadius: 3,
                pointBackgroundColor: accentColor,
                borderWidth: 2,
                tension: 0,
                spanGaps: true,
              },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: { offset: X_AXIS_OFFSET, grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 7, autoSkip: true } },
              y: {
                min: 4,
                max: 24,
                afterFit: fixedYAxisWidth,
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 5, callback: (v) => clockFromHoursAfterNoon(Number(v)) },
              },
            },
            plugins: {
              legend: { display: true, position: "bottom", labels: { color: textColor, font: { size: 10 }, boxWidth: 10, padding: 12 } },
              tooltip: {
                enabled: true,
                padding: 6,
                titleFont: { size: 11 },
                bodyFont: { size: 11 },
                callbacks: {
                  label: (item) =>
                    item.parsed.y == null ? "Keine Daten" : `${item.dataset.label}: ${clockFromHoursAfterNoon(item.parsed.y)}`,
                },
              },
            },
          }}
        />
      </div>
    </div>
  );
}

// --- Korrelationen ---

function CorrelationScatter({
  title,
  tooltip,
  points,
  xLabel,
  color,
}: {
  title: string;
  tooltip: string;
  points: { x: number; y: number }[];
  xLabel: string;
  color: string;
}) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  if (points.length < 3) {
    return (
      <div className="hrv-trend-chart-block">
        <div className="hrv-trend-chart-title">{title}</div>
        <p className="week-rationale">Noch nicht genug Nächte mit beiden Werten für eine Auswertung.</p>
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
        <Scatter
          data={{ datasets: [{ label: title, data: points, backgroundColor: color, pointRadius: 4 }] }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: { title: { display: true, text: xLabel, color: textColor, font: { size: 10 } }, grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 } } },
              y: {
                title: { display: true, text: "Sleep Score", color: textColor, font: { size: 10 } },
                min: 0,
                max: 100,
                grid: { color: gridColor },
                ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 4 },
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

function LateWorkoutComparisonChart({ points }: { points: SleepTrendPoint[] }) {
  const gridColor = useCssVar("--border");
  const textColor = useCssVar("--text");
  const accentColor = useCssVar("--accent");

  const late = points.filter((p) => p.prev_day_late_workout && p.sleep_score != null).map((p) => p.sleep_score as number);
  const notLate = points
    .filter((p) => !p.prev_day_late_workout && p.prev_day_training_load != null && p.sleep_score != null)
    .map((p) => p.sleep_score as number);

  if (late.length < 2 || notLate.length < 2) {
    return (
      <div className="hrv-trend-chart-block">
        <div className="hrv-trend-chart-title">Späte Einheit am Vorabend vs. Schlaf-Score</div>
        <p className="week-rationale">Noch nicht genug Nächte mit und ohne späte Einheit für eine Auswertung.</p>
      </div>
    );
  }

  const avg = (arr: number[]) => arr.reduce((sum, v) => sum + v, 0) / arr.length;

  return (
    <div className="hrv-trend-chart-block">
      <div className="hrv-trend-chart-title">
        Späte Einheit am Vorabend vs. Schlaf-Score
        <InfoTooltip text="Vergleicht den durchschnittlichen Sleep Score von Nächten nach einem Training ab 18 Uhr mit Nächten ohne (späte) Trainingseinheit am Vorabend." />
      </div>
      <div className="hrv-trend-chart-canvas">
        <Bar
          data={{
            labels: [`Training ≥18 Uhr (${late.length})`, `Kein spätes Training (${notLate.length})`],
            datasets: [
              {
                label: "Ø Sleep Score",
                data: [avg(late), avg(notLate)],
                backgroundColor: [SLEEP_DURATION_MODERATE, accentColor],
                borderRadius: 2,
              },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 } } },
              y: { min: 0, max: 100, grid: { color: gridColor }, ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 4 } },
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

function SleepCorrelations({ points, lateThreshold }: { points: SleepTrendPoint[]; lateThreshold: number }) {
  const accentColor = useCssVar("--accent");

  const trainingLoadPoints = points
    .filter((p) => p.prev_day_training_load != null && p.sleep_score != null)
    .map((p) => ({ x: p.prev_day_training_load as number, y: p.sleep_score as number }));

  const hrvPoints = points
    .filter((p) => p.avg_overnight_hrv != null && p.sleep_score != null)
    .map((p) => ({ x: p.avg_overnight_hrv as number, y: p.sleep_score as number }));

  const rpePoints = points
    .filter((p) => p.prev_day_rpe != null && p.sleep_score != null)
    .map((p) => ({ x: p.prev_day_rpe as number, y: p.sleep_score as number }));

  return (
    <>
      <CorrelationScatter
        title="Trainingslast am Vorabend vs. Schlaf-Score"
        tooltip="Jeder Punkt eine Nacht: x = Summe der Trainingslast des Vortages (garmin_activities.activity_training_load), y = Sleep Score dieser Nacht."
        points={trainingLoadPoints}
        xLabel="Trainingslast (Vortag)"
        color={accentColor}
      />
      <LateWorkoutComparisonChart points={points} />
      <CorrelationScatter
        title="Overnight-HRV vs. Schlaf-Score"
        tooltip="Jeder Punkt eine Nacht: x = durchschnittliche HRV während des Schlafs, y = Sleep Score derselben Nacht."
        points={hrvPoints}
        xLabel="Overnight-HRV (ms)"
        color={PHASE_REM_COLOR}
      />
      <CorrelationScatter
        title="Belastungsempfinden (RPE) am Vorabend vs. Schlaf-Score"
        tooltip={`Jeder Punkt eine Nacht: x = RPE-Wert aus dem Tagesjournal des Vortages, y = Sleep Score dieser Nacht. Training ab ${lateThreshold} Uhr zählt hier zusätzlich als "späte Einheit" im Vergleichs-Chart oben.`}
        points={rpePoints}
        xLabel="RPE (Vortag, 1-10)"
        color={SLEEP_DURATION_LOW}
      />
    </>
  );
}

function SleepView() {
  const today = todayIso();
  const [overview, setOverview] = useState<SleepOverview | null>(null);
  const [levels, setLevels] = useState<SleepLevels | null>(null);
  const [trend, setTrend] = useState<SleepTrend | null>(null);
  const [correlationsInsight, setCorrelationsInsight] = useState<SleepCorrelationsInsight | null>(null);
  const [correlationsInsightLoading, setCorrelationsInsightLoading] = useState(false);
  const [trendInsight, setTrendInsight] = useState<SleepTrendInsight | null>(null);
  const [trendInsightLoading, setTrendInsightLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSleepOverview(today)
      .then(setOverview)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchSleepLevels(today)
      .then(setLevels)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchSleepTrend(28)
      .then(setTrend)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [today]);

  // Erst anfragen, sobald genug Trend-Daten für die Korrelations-/Trend-Charts da sind (gleiche
  // Bedingung wie unten beim Rendern) - vermeidet einen Gemini-Aufruf ohne sinnvolle Datenbasis.
  useEffect(() => {
    if (!trend || trend.points.length <= 1) return;
    setCorrelationsInsightLoading(true);
    fetchSleepCorrelationsInsight()
      .then(setCorrelationsInsight)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setCorrelationsInsightLoading(false));
    setTrendInsightLoading(true);
    fetchSleepTrendInsight()
      .then(setTrendInsight)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setTrendInsightLoading(false));
  }, [trend]);

  return (
    <div className="today-view">
      {error && <p className="error-banner">Fehler: {error}</p>}
      <div className="performance-row sleep-hero-cards-row">
        <div className="sleep-card-two-thirds">
          <SleepOverviewCard date={today} overview={overview} levels={levels} />
        </div>
        <div className="sleep-card-one-third">
          <HabitTrackerCard date={today} />
        </div>
      </div>
      {trend && trend.points.length > 1 && (
        <>
          <div className="card">
            <h3>
              Trend (28 Tage)
              {trendInsight && (
                <InsightRegenerateButton regenerateFn={regenerateSleepTrendInsight} onRegenerated={setTrendInsight} />
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
              <div className="hrv-trend-panel">
                <SleepDurationChart points={trend.points} />
                <SleepPhaseTrendChart points={trend.points} />
                <SleepRegularityChart points={trend.points} />
              </div>
            </div>
          </div>
          <div className="card">
            <h3>
              Korrelationen
              <InfoTooltip text="Rein beobachtend, keine statistische Signifikanzprüfung - bei wenigen Nächten können einzelne Ausreißer das Bild stark verzerren." />
              {correlationsInsight && (
                <InsightRegenerateButton
                  regenerateFn={regenerateSleepCorrelationsInsight}
                  onRegenerated={setCorrelationsInsight}
                />
              )}
            </h3>
            <div className="sleep-correlations-row">
              <div className="sleep-insight-col">
                {correlationsInsightLoading && !correlationsInsight ? (
                  <p className="week-rationale">Lade Einordnung…</p>
                ) : correlationsInsight ? (
                  <p className="sleep-insight-text">{correlationsInsight.insight_text}</p>
                ) : (
                  <p className="week-rationale">Keine Einordnung verfügbar.</p>
                )}
              </div>
              <div className="sleep-correlations-grid">
                <SleepCorrelations points={trend.points} lateThreshold={trend.late_workout_hour_threshold} />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default SleepView;
