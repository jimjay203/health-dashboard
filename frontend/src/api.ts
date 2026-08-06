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
  // Datum, dessen Wert tatsächlich angezeigt wird (training_status wird nicht an jedem
  // Sync-Tag neu geliefert - Backend fällt auf die letzte vorhandene Zeile zurück).
  data_date: string | null;
  training_status_label: string | null;
  acute_training_load: number | null;
  chronic_training_load: number | null;
  chronic_load_min: number | null;
  chronic_load_max: number | null;
  acwr_status: string | null;
  acwr_ratio: number | null;
  // Alle drei bleiben None, falls Garmin die Verteilung für dieses Konto (noch) nicht liefert -
  // siehe backend/routers/performance.py-Docstring (Ground-Truth-Fund).
  load_focus_anaerobic_pct: number | null;
  load_focus_high_aerobic_pct: number | null;
  load_focus_low_aerobic_pct: number | null;
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

export interface PerformanceGoal {
  key: string;
  label: string;
  target_value: number;
  unit: string;
  derived_from_race_goal_id: number | null;
  notes: string | null;
  target_date: string | null;
  updated_at: string;
}

export type PerformanceGoalInput = Omit<PerformanceGoal, "updated_at">;

export function fetchReadinessOverview(date: string): Promise<ReadinessOverview> {
  return fetch(`/api/performance/readiness-overview/${date}`).then((res) => handle<ReadinessOverview>(res));
}

export function fetchLoadStatus(date: string): Promise<LoadStatus> {
  return fetch(`/api/performance/load-status/${date}`).then((res) => handle<LoadStatus>(res));
}

export function fetchThresholds(): Promise<Thresholds> {
  return fetch(`/api/performance/thresholds`).then((res) => handle<Thresholds>(res));
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

// Sekunden/km -> "4:31 min/km", konsistent für Ist- und Ziel-Pace verwendet.
export function formatPace(secPerKm: number | null): string {
  if (secPerKm === null) return "–";
  const minutes = Math.floor(secPerKm / 60);
  const seconds = Math.round(secPerKm % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")} min/km`;
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

export function fetchWeekStrip(date: string): Promise<WeekStrip> {
  return fetch(`/api/week-strip/${date}`).then((res) => handle<WeekStrip>(res));
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
