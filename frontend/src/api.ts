// Dünne, typisierte fetch()-Wrapper für die Heute-Ansicht + Vereins-Slot-Einstellungen (Schritt 2
// des FastAPI+React-Rebuilds). Im Docker-Build liefert FastAPI selbst /api/* aus derselben
// Origin aus, lokal übernimmt vite.config.ts den Dev-Proxy.

export interface Recommendation {
  date: string;
  recommendation_text: string;
  reasoning_bullets: string[];
  generated_at: string;
}

export type OverrideValue = "worse" | "better" | "neutral";

export type WeekDayCategory = "race" | "completed" | "club" | "rest";

export interface WeekDay {
  date: string;
  weekday: number;
  category: WeekDayCategory;
  label: string | null;
  sport_type: SportType | null;
  is_today: boolean;
}

export interface WeekStrip {
  week_start: string;
  week_end: string;
  days: WeekDay[];
}

// Feste Sportart-Auswahl fürs Dropdown in ClubSlotsSettings.tsx - muss mit backend/routers/
// club_slots.py::SportType übereinstimmen (dort per Pydantic Literal validiert).
export const SPORT_TYPES = ["Schwimmen", "Laufen", "Rad", "Krafttraining", "Mobility"] as const;
export type SportType = (typeof SPORT_TYPES)[number];

// Material-Symbols-Icon-Namen (siehe Icon.tsx) statt Emoji-Zeichen.
export const SPORT_TYPE_ICON: Record<SportType, string> = {
  Schwimmen: "pool",
  Laufen: "directions_run",
  Rad: "directions_bike",
  Krafttraining: "fitness_center",
  Mobility: "self_improvement",
};

export interface ClubSlot {
  id: number;
  weekday: number;
  sport_type: SportType;
  label: string;
  valid_from: string;
  valid_to: string | null;
  typical_character: string | null;
}

export type ClubSlotInput = Omit<ClubSlot, "id">;

// --- Rolling-Horizon-Wochenplaner ---

// Tatsächlich absolvierte Aktivität (garmin_activities) - siehe backend/routers/weekly_plan.py::
// _actual_activities_by_date. Für vergangene Tage zeigt WeeklyCalendarWidget.tsx damit Plan vs.
// Ist statt weiterhin nur die (überholte) Planung.
export interface ActualActivity {
  activity_type: string | null;
  distance_meters: number | null;
  duration_seconds: number | null;
  start_time_local: string | null;
}

// is_key_session: null nur bei Wettkampftagen (nicht bewertbar) - sonst true/false vom Modell
// eingeschätzt (siehe weekly_planner.py SYSTEM_PROMPT, Kern- vs. flexible Einheit).
export interface WeeklyPlanDay {
  date: string;
  week_id: string;
  weekday: number;
  sport_type: string | null;
  session_type: string | null;
  target_zone: string | null;
  target_duration_minutes: number | null;
  target_distance_m: number | null;
  is_key_session: boolean | null;
  is_club_slot: boolean;
  source: string | null;
  data_quality_flag: string | null;
  actual_activities: ActualActivity[];
}

export interface WeeklyPlan {
  week_id: string;
  week_start: string;
  week_end: string;
  // Eigene, für DIESE Woche berechnete Phase (siehe weekly_planner.py::get_week_phase) - jede der
  // drei Wochen-Ebenen im Kalender-Widget bekommt ihre eigene, korrekt für ihren eigenen
  // Wochenstart berechnete Phase, keine geteilte/wiederverwendete.
  training_phase: string | null;
  week_rationale_text: string | null;
  days: WeeklyPlanDay[];
  // >0 nur direkt nach regenerateWeeklyPlan(), wenn dabei bereits zu Garmin hochgeladene
  // Workout-Entwürfe ersetzt wurden (der alte Garmin-Termin bleibt davon unberührt bestehen).
  already_uploaded_count: number;
}

export interface WorkoutDraft {
  id: number | null;
  uploaded: boolean;
}

export interface UploadDraftResult {
  success: boolean;
  workout_id: number | null;
  error: string | null;
}

// Ab Woche 4: eine Zeile pro Woche bis zum nächsten Rennen (siehe
// weekly_planner.py::get_far_weeks_outlook). training_phase ist None für Wochen, die zu weit in
// der Zukunft liegen, um eine Phase ehrlich zu bestimmen (kein synchronisiertes Trainingsvolumen
// vorhanden) - siehe Funktions-Docstring.
export interface FarWeekBar {
  week_id: string;
  iso_week: number;
  week_start: string;
  week_end: string;
  training_phase: string | null;
  // Nur in der Woche des Rennens selbst gesetzt (siehe weekly_planner.py::get_far_weeks_outlook) -
  // dort wird der Wettkampf explizit benannt statt nur die Trainingsphase zu zeigen.
  race_title: string | null;
  race_date: string | null;
}

export interface FarWeeksOutlook {
  weeks: FarWeekBar[];
}

// --- Leistung-Seite (Trainingsdiagnostik-KPIs) ---

export interface HrvTrendPoint {
  date: string;
  avg_hrv: number | null;
  resting_hr: number | null;
  training_load: number | null;
}

export interface ReadinessOverview {
  date: string;
  score: number | null;
  level: string | null;
  feedback_short: string | null;
  // Garmins Trainingsbereitschafts-Faktoren (garmin_training_readiness) - dieselbe Aufschlüsselung
  // wie in der Garmin-Connect-App ("Faktoren"-Liste, siehe TodayView.tsx::ReadinessFactorsList).
  // feedback-Felder sind rohe Garmin-Enums (GOOD/VERY_GOOD/MODERATE/POOR/NONE).
  sleep_score: number | null;
  sleep_score_factor_feedback: string | null;
  recovery_time_minutes: number | null;
  recovery_time_factor_feedback: string | null;
  acwr_factor_percent: number | null;
  acwr_factor_feedback: string | null;
  hrv_weekly_average: number | null;
  hrv_factor_feedback: string | null;
  sleep_history_factor_percent: number | null;
  sleep_history_factor_feedback: string | null;
  stress_history_factor_percent: number | null;
  stress_history_factor_feedback: string | null;
  avg_hrv: number | null;
  // Garmins eigene Einordnung ("BALANCED"/"UNBALANCED"/"LOW", "NONE" während der Onboarding-Phase
  // des Geräts) - roh vom Backend durchgereicht.
  hrv_status: string | null;
  hrv_last_night_avg: number | null;
  hrv_baseline_balanced_low: number | null;
  hrv_baseline_balanced_upper: number | null;
  resting_hr: number | null;
  // Kein Garmin-Original-Status (den gibt es für den Ruhepuls nicht, anders als hrv_status) -
  // nur der 7-Tage-Schnitt, aus dem das Frontend selbst eine Einordnung ableitet.
  resting_hr_7d_avg: number | null;
  hrv_trend: HrvTrendPoint[];
}

export interface LoadStatus {
  // Datum, dessen Wert tatsächlich angezeigt wird (Backend fällt auf die letzte vorhandene
  // daily_summary-Zeile mit tsb zurück).
  data_date: string | null;
  // CTL/ATL/TSB (PMC-Modell) statt Garmins eigener, unzuverlässiger Trainingszustand-
  // Klassifizierung - siehe Ground-Truth-Fund in backend/routers/performance.py.
  ctl: number | null;
  atl: number | null;
  tsb: number | null;
  training_state_key: string | null;
  training_state_label: string | null;
  // Eigene Berechnung aus HF-Zonen-Zeiten (garmin_activities.hr_zone_1..5, 28-Tage-Fenster) -
  // Garmins eigene Verteilung liefert für dieses Konto durchgängig keine Daten, siehe
  // backend/routers/performance.py-Docstring (Ground-Truth-Fund).
  load_focus_anaerobic_pct: number | null;
  load_focus_high_aerobic_pct: number | null;
  load_focus_low_aerobic_pct: number | null;
}

export interface CtlTrendPoint {
  date: string;
  ctl: number | null;
  atl: number | null;
  tsb: number | null;
}

export interface CtlTrend {
  points: CtlTrendPoint[];
}

export interface Thresholds {
  run_threshold_pace_sec_per_km: number | null;
  run_threshold_hr: number | null;
  run_threshold_date: string | null;
  cycling_threshold_hr: number | null;
  ftp_watts: number | null;
  ftp_power_to_weight: number | null;
  ftp_date: string | null;
  vo2max_running: number | null;
  vo2max_running_date: string | null;
  vo2max_cycling: number | null;
  vo2max_cycling_date: string | null;
}

// Echter Garmin Race-Predictor (garmin_race_predictions, täglich synchronisiert) - Finish-Zeiten
// in Sekunden für die vier Standard-Laufdistanzen.
export interface RacePredictions {
  date: string | null;
  time_5k: number | null;
  time_10k: number | null;
  time_half_marathon: number | null;
  time_marathon: number | null;
}

// Kein Garmin-Pendant fürs Rad - Schätzung aus dem eigenen Wirkungsgrad (km/h pro Watt), siehe
// backend/routers/performance.py::get_cycling_prediction. sample_size zeigt die Datenbasis, damit
// die Schätzung transparent als "wird mit mehr Fahrten belastbarer" statt als Fakt erscheint.
export interface CyclingPredictionScenario {
  key: string;
  label: string;
  distance_km: number;
  target_power_watts: number | null;
  estimated_speed_kmh: number | null;
  estimated_duration_seconds: number | null;
}

export interface CyclingPrediction {
  sample_size: number;
  efficiency_kmh_per_watt: number | null;
  scenarios: CyclingPredictionScenario[];
}

export interface SwimDiagnostics {
  date: string | null;
  swolf: number | null;
  pace_sec_per_100m: number | null;
}

export interface PerformanceGoal {
  key: string;
  label: string;
  target_value: number;
  unit: string;
  derived_from_race_goal_id: number | null;
  notes: string | null;
  target_date: string | null;
  start_date: string | null;
  updated_at: string;
  // Serverseitig abgeleitet aus echten Garmin-Zeitreihen (siehe backend/routers/performance.py::
  // _metric_value) - null nur, falls für diesen Ziel-Typ noch kein Ist-Wert vorliegt.
  current_value: number | null;
  current_value_date: string | null;
  start_value: number | null;
  // Datum des tatsächlich verwendeten Startwerts - entspricht start_date, wenn gesetzt, sonst der
  // frühesten verfügbaren Messung (impliziter Start, siehe _enrich_goal im Backend). Für die
  // Fortschrittsbalken-Anzeige verwenden, NICHT start_date selbst (das bleibt das reine
  // Formular-Feld).
  start_value_date: string | null;
}

export type PerformanceGoalInput = Omit<
  PerformanceGoal,
  "updated_at" | "current_value" | "current_value_date" | "start_value" | "start_value_date"
>;

export function fetchReadinessOverview(date: string): Promise<ReadinessOverview> {
  return fetch(`/api/performance/readiness-overview/${date}`).then((res) => handle<ReadinessOverview>(res));
}

export function fetchLoadStatus(date: string): Promise<LoadStatus> {
  return fetch(`/api/performance/load-status/${date}`).then((res) => handle<LoadStatus>(res));
}

export function fetchCtlTrend(): Promise<CtlTrend> {
  return fetch(`/api/performance/ctl-trend`).then((res) => handle<CtlTrend>(res));
}

export function fetchThresholds(): Promise<Thresholds> {
  return fetch(`/api/performance/thresholds`).then((res) => handle<Thresholds>(res));
}

export function fetchRacePredictions(): Promise<RacePredictions> {
  return fetch(`/api/performance/race-predictions`).then((res) => handle<RacePredictions>(res));
}

export function fetchCyclingPrediction(): Promise<CyclingPrediction> {
  return fetch(`/api/performance/cycling-prediction`).then((res) => handle<CyclingPrediction>(res));
}

export function fetchSwimDiagnostics(): Promise<SwimDiagnostics> {
  return fetch(`/api/performance/swim-diagnostics`).then((res) => handle<SwimDiagnostics>(res));
}

// --- Erkenntnisse (Schicht 3, insight_memory.py) ---

export interface InsightMemoryVersion {
  version: number;
  updated_at: string;
  compressed_text: string | null;
}

export type InsightSource = "user" | "claude_import" | "journal";

export interface InsightRawEntry {
  id: number;
  created_at: string;
  raw_text: string;
  source: InsightSource;
}

export function fetchInsightMemoryCompressed(): Promise<InsightMemoryVersion[]> {
  return fetch(`/api/insight-memory/compressed`).then((res) => handle<InsightMemoryVersion[]>(res));
}

export function fetchInsightMemoryRaw(): Promise<InsightRawEntry[]> {
  return fetch(`/api/insight-memory/raw`).then((res) => handle<InsightRawEntry[]>(res));
}

// Läuft serverseitig blockierend bis Gemini die Verdichtung abgeschlossen hat (siehe
// backend/routers/insight_memory.py) - das fetch-Promise löst sich entsprechend erst danach auf.
export function addInsightMemoryEntry(rawText: string): Promise<InsightMemoryVersion> {
  return fetch(`/api/insight-memory/raw`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_text: rawText }),
  }).then((res) => handle<InsightMemoryVersion>(res));
}

export function deleteInsightMemoryEntry(id: number): Promise<{ success: boolean }> {
  return fetch(`/api/insight-memory/raw/${id}`, { method: "DELETE" }).then((res) =>
    handle<{ success: boolean }>(res)
  );
}

export function fetchPerformanceGoals(): Promise<PerformanceGoal[]> {
  return fetch(`/api/performance/goals`).then((res) => handle<PerformanceGoal[]>(res));
}

export function savePerformanceGoal(goal: PerformanceGoalInput): Promise<PerformanceGoal> {
  return fetch(`/api/performance/goals/${goal.key}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(goal),
  }).then((res) => handle<PerformanceGoal>(res));
}

export function deletePerformanceGoal(key: string): Promise<{ success: boolean }> {
  return fetch(`/api/performance/goals/${key}`, { method: "DELETE" }).then((res) =>
    handle<{ success: boolean }>(res)
  );
}

// Gemini-Einschätzung zur Erreichbarkeit der Leistungsziele (siehe performance_insight.py) -
// gleiches Muster wie fetchBodyTrendInsight/fetchSleepTrendInsight.
export interface PerformanceGoalsInsight {
  date: string;
  insight_text: string;
  generated_at: string;
}

export function fetchPerformanceGoalsInsight(): Promise<PerformanceGoalsInsight> {
  return fetch("/api/performance/goals-insight").then((res) => handle<PerformanceGoalsInsight>(res));
}

export function regeneratePerformanceGoalsInsight(): Promise<PerformanceGoalsInsight> {
  return fetch("/api/performance/goals-insight/regenerate", { method: "POST" }).then((res) =>
    handle<PerformanceGoalsInsight>(res)
  );
}

// Sekunden/km -> "4:31 min/km", konsistent für Ist- und Ziel-Pace verwendet.
export function formatPace(secPerKm: number | null): string {
  if (secPerKm === null) return "–";
  const minutes = Math.floor(secPerKm / 60);
  const seconds = Math.round(secPerKm % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")} min/km`;
}

// Geteilte Pace-/Dezimal-Formatierung für Leistungsziele (PerformanceGoalsSettings + Performance-
// View) - sec/km und sec/100m sind intern in Sekunden gespeichert, an der Oberfläche aber
// ausschließlich als "mm:ss min/km"/"mm:ss min/100m" ein-/ausgegeben; W/kg mit deutschem Komma.
export function isPaceUnit(unit: string): boolean {
  return unit === "sec/km" || unit === "sec/100m";
}

export function paceUnitLabel(unit: string): string {
  return unit === "sec/100m" ? "min/100m" : "min/km";
}

export function unitDisplayLabel(unit: string): string {
  return isPaceUnit(unit) ? paceUnitLabel(unit) : unit;
}

export function parsePaceToSeconds(text: string): number | null {
  const match = text.trim().match(/^(\d{1,3}):([0-5]\d)$/);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

export function formatSecondsToPace(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function parseGermanDecimal(text: string): number | null {
  const normalized = text.trim().replace(",", ".");
  if (normalized === "") return null;
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

export function formatGermanDecimal(value: number): string {
  return String(value).replace(".", ",");
}

// Zeigt einen Wert in derselben oberflächen-gerechten Einheit wie unitDisplayLabel (Pace ->
// mm:ss, W/kg -> Komma) - für current_value/start_value/target_value gleichermaßen verwendet.
// current_value/start_value kommen aus echten Garmin-Werten mit vielen Nachkommastellen (siehe
// GOAL_METRIC_SOURCES in backend/routers/performance.py) - W/kg wird deshalb hier (nicht in
// formatGermanDecimal selbst, das bleibt für die editierbare Zielwert-Eingabe exakt) auf eine
// Nachkommastelle gerundet, konsistent mit der Kopfzeilen-Anzeige in BikeThresholdCard.
export function formatGoalValue(value: number, unit: string): string {
  if (isPaceUnit(unit)) return formatSecondsToPace(value);
  if (unit === "W/kg") return formatGermanDecimal(Math.round(value * 10) / 10);
  return String(value);
}

// sec/km und sec/100m sind "niedriger ist besser" (schnellere Pace), alles andere (W/kg, ...)
// "höher ist besser" - dieselbe Konvention wie die bestehende goalIsMet-Logik in PerformanceView.
export function goalProgressPct(startValue: number, currentValue: number, targetValue: number, unit: string): number {
  const lowerIsBetter = unit.includes("sec");
  const span = lowerIsBetter ? startValue - targetValue : targetValue - startValue;
  if (span === 0) return currentValue === targetValue ? 100 : 0;
  const progressed = lowerIsBetter ? startValue - currentValue : currentValue - startValue;
  return Math.max(0, Math.min(100, (progressed / span) * 100));
}

// Garmins hrvSummary.status/trainingStatusFeedbackPhrase sind SCREAMING_SNAKE_CASE-Enums - reine
// Lesbarkeits-Formatierung ("NO_STATUS_1" -> "No Status 1"), keine inhaltliche Übersetzung, da für
// die meisten Werte keine verifizierte deutsche Entsprechung vorliegt. Geteilt zwischen TodayView
// (HRV-Status) und PerformanceView (Trainingszustand/ACWR-Status).
export function formatEnumLabel(raw: string | null): string | null {
  if (!raw) return null;
  return raw
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export type SyncStatusValue = "not_started" | "checking" | "completed" | "gave_up" | "rate_limited";

export interface SyncStatus {
  date: string;
  status: SyncStatusValue;
  last_check_at: string | null;
  full_sync_completed_at: string | null;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export function fetchRecommendation(date: string): Promise<Recommendation> {
  return fetch(`/api/daily-recommendation/${date}`).then((res) => handle<Recommendation>(res));
}

export function postOverride(date: string, overrideValue: OverrideValue): Promise<Recommendation> {
  return fetch(`/api/daily-override/${date}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ override_value: overrideValue }),
  }).then((res) => handle<Recommendation>(res));
}

// --- Tagesjournal (RPE/Muskelkater/Energie + Freitext, siehe backend/routers/today.py) ---

export interface DailyJournal {
  date: string;
  rpe_score: number | null;
  muscle_soreness: number | null;
  energy_level: number | null;
  notes: string | null;
}

export interface DailyJournalInput {
  rpe_score: number;
  muscle_soreness: number;
  energy_level: number;
  notes: string | null;
}

export interface SaveJournalResult {
  journal: DailyJournal;
  // Freitext fließt automatisch ins Erkenntnis-Gedächtnis (source="journal", siehe
  // InsightMemoryView.tsx) - ein Gemini-Fehler dabei lässt das Journal-Speichern selbst nicht
  // fehlschlagen, wird aber transparent als Warnung statt stillschweigend verschluckt angezeigt.
  insight_memory_warning: string | null;
}

export function fetchDailyJournal(date: string): Promise<DailyJournal> {
  return fetch(`/api/daily-journal/${date}`).then((res) => handle<DailyJournal>(res));
}

export function saveDailyJournal(date: string, entry: DailyJournalInput): Promise<SaveJournalResult> {
  return fetch(`/api/daily-journal/${date}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  }).then((res) => handle<SaveJournalResult>(res));
}

export function fetchWeekStrip(date: string): Promise<WeekStrip> {
  return fetch(`/api/week-strip/${date}`).then((res) => handle<WeekStrip>(res));
}

// --- Schlaf-Seite (siehe backend/routers/sleep.py) ---

export interface SleepOverview {
  date: string;
  sleep_score: number | null;
  sleep_hours: number | null;
  sleep_start_local: string | null;
  sleep_end_local: string | null;
  deep_sleep_seconds: number | null;
  light_sleep_seconds: number | null;
  rem_sleep_seconds: number | null;
  awake_sleep_seconds: number | null;
  deep_pct: number | null;
  light_pct: number | null;
  rem_pct: number | null;
  deep_qualifier: string | null;
  light_qualifier: string | null;
  rem_qualifier: string | null;
  total_duration_qualifier: string | null;
  stress_qualifier: string | null;
  restlessness_qualifier: string | null;
  awake_count: number | null;
  awake_count_qualifier: string | null;
  avg_sleep_stress: number | null;
  avg_sleep_hr: number | null;
  sleep_need_seconds: number | null;
  sleep_need_baseline_seconds: number | null;
  sleep_need_hrv_adjustment: string | null;
  sleep_need_training_feedback: string | null;
  // Bereits als "HH:MM"-Uhrzeit formatiert (siehe backend/routers/sleep.py::_mins_to_clock).
  recommended_bedtime_start: string | null;
  recommended_bedtime_end: string | null;
  restless_moments_count: number | null;
  avg_overnight_hrv: number | null;
  body_battery_change: number | null;
  avg_skin_temp_deviation_c: number | null;
  avg_sleep_spo2: number | null;
  lowest_sleep_spo2: number | null;
  avg_sleep_respiration: number | null;
  sleep_score_feedback: string | null;
  sleep_score_insight: string | null;
  sleep_score_qualifier: string | null;
  sleep_debt_cumulative: number | null;
  sleep_vs_7d_avg_pct: number | null;
}

// prev_day_* beschreiben den Vorabend dieser Nacht (Training/Journal/Habits VOR dem Einschlafen,
// nicht den Tag der Nacht selbst - siehe Datums-Konvention in backend/routers/sleep.py).
export interface SleepTrendPoint {
  date: string;
  sleep_hours: number | null;
  sleep_score: number | null;
  deep_pct: number | null;
  light_pct: number | null;
  rem_pct: number | null;
  sleep_start_local: string | null;
  sleep_end_local: string | null;
  sleep_need_seconds: number | null;
  sleep_debt_cumulative: number | null;
  avg_overnight_hrv: number | null;
  prev_day_training_load: number | null;
  prev_day_late_workout: boolean;
  prev_day_rpe: number | null;
  prev_day_caffeine_after_noon: boolean | null;
  // Serverseitig aus habit_tracker.last_screen_time (Vorabend) + sleep_start_local dieser Nacht
  // abgeleitet (siehe backend/routers/sleep.py::_screen_time_gap_minutes) - kein direkt
  // eingegebener Wert mehr (Uhrzeit lässt sich leichter erinnern als eine geschätzte Minutenzahl).
  prev_day_screen_time_gap_minutes: number | null;
}

export interface SleepTrend {
  // Ab welcher Uhrzeit ein Training des Vorabends als "spät" gilt (siehe backend/routers/sleep.py::
  // LATE_WORKOUT_HOUR_THRESHOLD) - eine transparent offengelegte Annahme, keine harte Kennzahl.
  late_workout_hour_threshold: number;
  points: SleepTrendPoint[];
}

export function fetchSleepOverview(date: string): Promise<SleepOverview> {
  return fetch(`/api/sleep/overview/${date}`).then((res) => handle<SleepOverview>(res));
}

export function fetchSleepTrend(days = 28): Promise<SleepTrend> {
  return fetch(`/api/sleep/trend?days=${days}`).then((res) => handle<SleepTrend>(res));
}

// Gemini-Einordnung der "Korrelationen"-Charts (siehe sleep_insight.py) - Cache-dann-lazy-
// generieren pro Tag, gleiches Muster wie fetchRecommendation.
export interface SleepCorrelationsInsight {
  date: string;
  insight_text: string;
  generated_at: string;
}

export function fetchSleepCorrelationsInsight(): Promise<SleepCorrelationsInsight> {
  return fetch("/api/sleep/correlations-insight").then((res) => handle<SleepCorrelationsInsight>(res));
}

export function regenerateSleepCorrelationsInsight(): Promise<SleepCorrelationsInsight> {
  return fetch("/api/sleep/correlations-insight/regenerate", { method: "POST" }).then((res) =>
    handle<SleepCorrelationsInsight>(res)
  );
}

// Gemini-Einordnung des 28-Tage-Trends (siehe sleep_trend_insight.py) - gleiches Muster wie
// fetchSleepCorrelationsInsight.
export interface SleepTrendInsight {
  date: string;
  insight_text: string;
  generated_at: string;
}

export function fetchSleepTrendInsight(): Promise<SleepTrendInsight> {
  return fetch("/api/sleep/trend-insight").then((res) => handle<SleepTrendInsight>(res));
}

export function regenerateSleepTrendInsight(): Promise<SleepTrendInsight> {
  return fetch("/api/sleep/trend-insight/regenerate", { method: "POST" }).then((res) =>
    handle<SleepTrendInsight>(res)
  );
}

// Minuten-genauer Phasenverlauf einer einzelnen Nacht (Apple-Health-Vorbild) - nur bei Bedarf pro
// Anfrage aus garmin_daily.raw_json geparst, keine eigene Tabelle (siehe backend/routers/sleep.py).
export type SleepStage = "deep" | "light" | "rem" | "awake";

export interface SleepLevelSegment {
  start_local: string;
  end_local: string;
  stage: SleepStage;
}

export interface SleepLevels {
  date: string;
  segments: SleepLevelSegment[];
}

export function fetchSleepLevels(date: string): Promise<SleepLevels> {
  return fetch(`/api/sleep/levels/${date}`).then((res) => handle<SleepLevels>(res));
}

// --- Habit-Tracker (siehe habit_tracker.py) - startet auf der Schlaf-Seite, bewusst als
// eigenständiges Feature gebaut, um später auch außerhalb des Schlaf-Kontexts erweiterbar zu sein. ---

export interface HabitEntry {
  date: string;
  caffeine_after_noon: boolean | null;
  last_screen_time: string | null;
  last_meal_time: string | null;
}

export type HabitEntryInput = Omit<HabitEntry, "date"> & {
  caffeine_after_noon: boolean;
};

export function fetchHabitEntry(date: string): Promise<HabitEntry> {
  return fetch(`/api/habit-tracker/${date}`).then((res) => handle<HabitEntry>(res));
}

export function saveHabitEntry(date: string, entry: HabitEntryInput): Promise<HabitEntry> {
  return fetch(`/api/habit-tracker/${date}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  }).then((res) => handle<HabitEntry>(res));
}

// --- Daten-Engine (Einstellungen-Seite, siehe backend/routers/data_sync.py) - die aus Streamlit
// noch fehlenden Sync-Funktionen: Einzel-Tages-Sync für ein beliebiges Datum, Backfill über einen
// Zeitraum, Aktivitäten-Sync. Backfill/Aktivitäten-Details laufen als Hintergrund-Task mit
// Status-Polling statt eines lange blockierenden Requests. ---

export interface DaySyncResult {
  success: boolean;
  error: string | null;
  measurement_count: number | null;
}

export function syncGarminDay(date: string): Promise<DaySyncResult> {
  return fetch(`/api/data-sync/garmin-day/${date}`, { method: "POST" }).then((res) => handle<DaySyncResult>(res));
}

export function syncWithingsDay(date: string): Promise<DaySyncResult> {
  return fetch(`/api/data-sync/withings-day/${date}`, { method: "POST" }).then((res) => handle<DaySyncResult>(res));
}

// Einmaliger Voll-Import der kompletten Withings-Historie (siehe
// withings_service.py::fetch_full_withings_history) - kein Datum, bewusst blockierend (Withings
// liefert alles über wenige paginierte Aufrufe, kein Hintergrund-Task wie beim Garmin-Backfill nötig).
export function syncWithingsFullHistory(): Promise<DaySyncResult> {
  return fetch("/api/data-sync/withings-full-history", { method: "POST" }).then((res) => handle<DaySyncResult>(res));
}

// Status des stündlichen Hintergrund-Tasks (siehe withings_auto_sync.py) - hält primär den
// OAuth2-Token aktiv, synct nebenbei den heutigen Tag.
export interface WithingsAutoSyncStatus {
  last_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  last_measurement_count: number | null;
  token_created_at: number | null;
  token_expires_at: number | null;
}

export function fetchWithingsAutoSyncStatus(): Promise<WithingsAutoSyncStatus> {
  return fetch("/api/data-sync/withings-auto-sync-status").then((res) => handle<WithingsAutoSyncStatus>(res));
}

export interface BackfillStatus {
  running: boolean;
  current_date: string | null;
  success_count: number;
  error_count: number;
  total: number;
  stopped_early: boolean;
  last_error: string | null;
}

export function startBackfill(startDate: string, endDate: string): Promise<{ started: boolean }> {
  return fetch(`/api/data-sync/backfill`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_date: startDate, end_date: endDate }),
  }).then((res) => handle<{ started: boolean }>(res));
}

export function fetchBackfillStatus(): Promise<BackfillStatus> {
  return fetch(`/api/data-sync/backfill-status`).then((res) => handle<BackfillStatus>(res));
}

// CTL/ATL/TSB (daily_summary/weekly_summary) für einen Zeitraum neu berechnen - rein lokal, kein
// Garmin-API-Call (siehe daily_summary.py::recompute_summary_range), deshalb blockierend statt
// Hintergrund-Task mit Polling wie beim Backfill oben.
export interface RecomputeSummaryResult {
  success: boolean;
  days_recomputed: number;
  error: string | null;
}

export function recomputeSummary(startDate: string, endDate: string): Promise<RecomputeSummaryResult> {
  return fetch(`/api/data-sync/recompute-summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_date: startDate, end_date: endDate }),
  }).then((res) => handle<RecomputeSummaryResult>(res));
}

export interface ActivitiesSummary {
  total_activities: number;
  pending_details: number;
}

export function fetchActivitiesSummary(): Promise<ActivitiesSummary> {
  return fetch(`/api/data-sync/activities-summary`).then((res) => handle<ActivitiesSummary>(res));
}

export interface ActivityRow {
  activity_id: number;
  start_time_local: string | null;
  activity_type: string | null;
  activity_name: string | null;
  distance_km: number | null;
  has_details_synced: boolean;
}

export function fetchActivities(limit = 50): Promise<ActivityRow[]> {
  return fetch(`/api/data-sync/activities?limit=${limit}`).then((res) => handle<ActivityRow[]>(res));
}

export function syncActivitiesList(limit: number): Promise<{ success: boolean; count: number; error: string | null }> {
  return fetch(`/api/data-sync/activities-list`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ limit }),
  }).then((res) => handle<{ success: boolean; count: number; error: string | null }>(res));
}

export interface ActivityDetailsStatus {
  running: boolean;
  current_index: number;
  total: number;
  current_activity_name: string | null;
  synced_count: number;
  error_count: number;
  last_error: string | null;
}

export function startActivityDetailsSync(maxCount: number): Promise<{ started: boolean }> {
  return fetch(`/api/data-sync/activities-details`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_count: maxCount }),
  }).then((res) => handle<{ started: boolean }>(res));
}

export function fetchActivityDetailsStatus(): Promise<ActivityDetailsStatus> {
  return fetch(`/api/data-sync/activities-details-status`).then((res) => handle<ActivityDetailsStatus>(res));
}

export function fetchClubSlots(): Promise<ClubSlot[]> {
  return fetch(`/api/club-slots`).then((res) => handle<ClubSlot[]>(res));
}

export function createClubSlot(slot: ClubSlotInput): Promise<ClubSlot> {
  return fetch(`/api/club-slots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(slot),
  }).then((res) => handle<ClubSlot>(res));
}

export function deleteClubSlot(id: number): Promise<{ success: boolean }> {
  return fetch(`/api/club-slots/${id}`, { method: "DELETE" }).then((res) =>
    handle<{ success: boolean }>(res)
  );
}

export function fetchSyncStatus(): Promise<SyncStatus> {
  return fetch(`/api/sync-status`).then((res) => handle<SyncStatus>(res));
}

// POST /api/sync-trigger läuft serverseitig blockierend bis der Sync fertig ist (siehe
// backend/routers/sync_status.py) - das fetch-Promise löst sich entsprechend erst danach auf.
export function triggerSync(): Promise<{ success: boolean; error: string | null }> {
  return fetch(`/api/sync-trigger`, { method: "POST" }).then((res) =>
    handle<{ success: boolean; error: string | null }>(res)
  );
}

export function fetchWeeklyPlan(date: string): Promise<WeeklyPlan> {
  return fetch(`/api/weekly-plan/${date}`).then((res) => handle<WeeklyPlan>(res));
}

export function regenerateWeeklyPlan(date: string): Promise<WeeklyPlan> {
  return fetch(`/api/weekly-plan/${date}/regenerate`, { method: "POST" }).then((res) => handle<WeeklyPlan>(res));
}

export function fetchWorkoutDraft(date: string): Promise<WorkoutDraft> {
  return fetch(`/api/workout-draft/${date}`).then((res) => handle<WorkoutDraft>(res));
}

export function uploadWorkoutDraft(draftId: number): Promise<UploadDraftResult> {
  return fetch(`/api/workout-draft/${draftId}/upload`, { method: "POST" }).then((res) =>
    handle<UploadDraftResult>(res)
  );
}

export function fetchFarWeeksOutlook(date: string): Promise<FarWeeksOutlook> {
  return fetch(`/api/far-weeks-outlook/${date}`).then((res) => handle<FarWeeksOutlook>(res));
}

// Streamlit läuft als getrennter Prozess/Container (Port 8501) - "Workout anpassen" ist eine
// volle Browser-Navigation dorthin, kein API-Call (siehe PROJECT_OVERVIEW.md, "Wochenplaner"-
// Abschnitt: st.session_state kann nicht zwischen den beiden Apps geteilt werden).
export function workoutBuilderUrl(draftId: number): string {
  return `http://${window.location.hostname}:8501/Workout_Builder?draft_id=${draftId}`;
}

// Reines String-Slicing auf einem bereits bekannten ISO-Datum ("YYYY-MM-DD" -> "DD.MM.") - kein
// new Date(isoString), das würde als UTC-Mitternacht interpretiert und riskiert je nach Zeitzone
// eine Tagesverschiebung (gleiche Konvention wie nextMondayIso()/weekAfterNextMondayIso() unten).
export function formatShortDate(isoDate: string): string {
  return `${isoDate.slice(8, 10)}.${isoDate.slice(5, 7)}.`;
}

// Für die reduzierte Ansicht (Nächste/Übernächste Woche) - keine exakte Minutenzahl, sondern auf
// glatte Viertel-/Halbstunden-Schritte gerundet ("20min"/"1,5 Std"), damit der grobe Zeitaufwand
// pro Tag auf einen Blick einschätzbar ist, ohne die volle Detailtiefe der fixierten Woche.
const DURATION_LADDER_MINUTES = [20, 30, 45, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360];

export function roundedDurationLabel(minutes: number): string {
  const nearest = DURATION_LADDER_MINUTES.reduce((closest, step) =>
    Math.abs(step - minutes) < Math.abs(closest - minutes) ? step : closest
  );
  if (nearest < 60) return `${nearest}min`;
  const hours = nearest / 60;
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1).replace(".", ",")} Std`;
}

function formatIso(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function todayIso(): string {
  return formatIso(new Date());
}

export function tomorrowIso(): string {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  return formatIso(tomorrow);
}

// Montag der nächsten Kalenderwoche - für die "Nächste Woche"-Ebene im Kalender-Widget (jetzt
// ebenso konkret durchgeplant wie "Diese Woche", siehe weekly_planner.py).
export function nextMondayIso(): string {
  const now = new Date();
  const isoWeekday = now.getDay() === 0 ? 7 : now.getDay(); // JS: 0=Sonntag..6=Samstag -> 1..7
  const daysUntilNextMonday = 8 - isoWeekday;
  const nextMonday = new Date(now);
  nextMonday.setDate(now.getDate() + daysUntilNextMonday);
  return formatIso(nextMonday);
}

// Montag der übernächsten Kalenderwoche - für die "Übernächste Woche"-Ebene im Kalender-Widget.
// Eigene Berechnung statt new Date(nextMondayIso()) - String->Date-Parsing würde als UTC-Mitternacht
// interpretiert und könnte je nach Zeitzone einen Tag verschieben (siehe formatIso-Konvention oben).
export function weekAfterNextMondayIso(): string {
  const now = new Date();
  const isoWeekday = now.getDay() === 0 ? 7 : now.getDay();
  const daysUntilNextMonday = 8 - isoWeekday;
  const weekAfterNext = new Date(now);
  weekAfterNext.setDate(now.getDate() + daysUntilNextMonday + 7);
  return formatIso(weekAfterNext);
}

// --- Körper-Seite (siehe backend/routers/body.py/body_composition.py) ---

// body_water_kg ist trotz des Feldnamens eine Wassermasse in kg, kein Prozentwert (Withings-
// Messtyp "Hydration" liefert eine Masse) - siehe body_composition.py-Moduldocstring.
// hydration_status: "normal" | "erhöht" - grobe Bevölkerungs-Referenz (siehe
// body_composition.py::HYDRATION_HIGH_THRESHOLD_PCT), keine personalisierte Bewertung.
// ffmi_classification: siehe body_composition.py::FFMI_CLASSIFICATION_BANDS (eine von mehreren
// gängigen Einteilungen, mit Quellenangabe im Frontend-Tooltip).
export interface BodyOverview {
  measured_date: string | null;
  weight_kg: number | null;
  weight_trend_7d_kg: number | null;
  body_fat_pct: number | null;
  body_water_kg: number | null;
  body_water_pct: number | null;
  hydration_status: string | null;
  bone_mass_kg: number | null;
  muscle_mass_kg: number | null;
  fat_mass_kg: number | null;
  fat_free_mass_kg: number | null;
  ffmi: number | null;
  ffmi_classification: string | null;
  muscle_fat_ratio: number | null;
  bmr_kcal: number | null;
  height_cm: number | null;
  target_weight_kg: number | null;
  target_body_fat_pct: number | null;
  weight_vs_avg_pct: number | null;
  days_until_next_race: number | null;
  running_power_to_weight: number | null;
  cycling_power_to_weight: number | null;
  running_ftp_watts: number | null;
  cycling_ftp_watts: number | null;
  vo2max_running: number | null;
  vo2max_cycling: number | null;
}

export function fetchBodyOverview(): Promise<BodyOverview> {
  return fetch("/api/body/overview").then((res) => handle<BodyOverview>(res));
}

export interface BodyTrendPoint {
  date: string;
  weight_kg: number | null;
  weight_rolling_avg_kg: number | null;
  body_fat_pct: number | null;
  body_water_kg: number | null;
  bone_mass_kg: number | null;
  muscle_mass_kg: number | null;
  fat_mass_kg: number | null;
}

export interface MuscleSorenessPoint {
  date: string;
  muscle_soreness: number;
}

export interface TrainingLoadPoint {
  date: string;
  training_load: number | null;
}

export interface BodyTrend {
  points: BodyTrendPoint[];
  muscle_soreness_points: MuscleSorenessPoint[];
  training_load_points: TrainingLoadPoint[];
}

export function fetchBodyTrend(days = 90): Promise<BodyTrend> {
  return fetch(`/api/body/trend?days=${days}`).then((res) => handle<BodyTrend>(res));
}

// Gemini-Einordnung des 90-Tage-Trends (siehe body_trend_insight.py) - gleiches Muster wie
// fetchSleepTrendInsight.
export interface BodyTrendInsight {
  date: string;
  insight_text: string;
  generated_at: string;
}

export function fetchBodyTrendInsight(): Promise<BodyTrendInsight> {
  return fetch("/api/body/trend-insight").then((res) => handle<BodyTrendInsight>(res));
}

export function regenerateBodyTrendInsight(): Promise<BodyTrendInsight> {
  return fetch("/api/body/trend-insight/regenerate", { method: "POST" }).then((res) =>
    handle<BodyTrendInsight>(res)
  );
}

// Lauf-Zeit-Prognose skaliert direkt proportional zum Gewichtsverhältnis (new_time = current_time
// * target_weight/current_weight) - dieselbe Annahme wie bei vo2max_running_target (konstante
// absolute VO2max-Kapazität, siehe body_composition.py::compute_what_if).
export interface RaceTimeProjectionEntry {
  current_seconds: number;
  target_seconds: number;
}

export interface WhatIfResult {
  current_weight_kg: number | null;
  target_weight_kg: number;
  cycling_ftp_watts: number | null;
  cycling_power_to_weight_current: number | null;
  cycling_power_to_weight_target: number | null;
  vo2max_running_current: number | null;
  vo2max_running_target: number | null;
  race_time_projection: Record<string, RaceTimeProjectionEntry> | null;
}

export function fetchBodyWhatIf(targetWeightKg: number): Promise<WhatIfResult> {
  return fetch(`/api/body/what-if?target_weight_kg=${targetWeightKg}`).then((res) => handle<WhatIfResult>(res));
}

// height_source unterscheidet, ob die Körpergröße automatisch aus Garmins Profil kommt
// ("garmin", täglich aktualisiert) oder unter Einstellungen manuell überschrieben wurde
// ("manual", wird von künftigen Garmin-Syncs nicht mehr überschrieben - siehe
// body_composition.py::sync_height_from_garmin).
export interface BodySettings {
  height_cm: number | null;
  height_source: string | null;
  target_weight_kg: number | null;
  target_body_fat_pct: number | null;
}

export interface BodySettingsUpdate {
  height_cm?: number | null;
  target_weight_kg?: number | null;
  target_body_fat_pct?: number | null;
  reset_height_to_garmin?: boolean;
}

export function fetchBodySettings(): Promise<BodySettings> {
  return fetch("/api/body/settings").then((res) => handle<BodySettings>(res));
}

export function saveBodySettings(update: BodySettingsUpdate): Promise<BodySettings> {
  return fetch("/api/body/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  }).then((res) => handle<BodySettings>(res));
}

export function resetHeightToGarmin(): Promise<BodySettings> {
  return saveBodySettings({ reset_height_to_garmin: true });
}

// resolved_at === null markiert einen noch aktiven Eintrag ("aktive Baustelle").
export interface Injury {
  id: number;
  date: string;
  body_part: string;
  severity: number;
  pain_type: string | null;
  context: string | null;
  notes: string | null;
  resolved_at: string | null;
  created_at: string;
}

export interface InjuryInput {
  date: string;
  body_part: string;
  severity: number;
  pain_type: string | null;
  context: string | null;
  notes: string | null;
}

export interface InjuryUpdateInput {
  body_part?: string | null;
  severity?: number | null;
  pain_type?: string | null;
  context?: string | null;
  notes?: string | null;
  resolved?: boolean | null;
}

export function fetchInjuries(activeOnly = false): Promise<Injury[]> {
  return fetch(`/api/body/injuries?active_only=${activeOnly}`).then((res) => handle<Injury[]>(res));
}

export function createInjury(input: InjuryInput): Promise<Injury> {
  return fetch("/api/body/injuries", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then((res) => handle<Injury>(res));
}

export function updateInjury(id: number, input: InjuryUpdateInput): Promise<Injury> {
  return fetch(`/api/body/injuries/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }).then((res) => handle<Injury>(res));
}

export function deleteInjury(id: number): Promise<{ success: boolean }> {
  return fetch(`/api/body/injuries/${id}`, { method: "DELETE" }).then((res) => handle<{ success: boolean }>(res));
}
