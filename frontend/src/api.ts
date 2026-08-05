// Dünne, typisierte fetch()-Wrapper für die Heute-Ansicht + Vereins-Slot-Einstellungen (Schritt 2
// des FastAPI+React-Rebuilds). Im Docker-Build liefert FastAPI selbst /api/* aus derselben
// Origin aus, lokal übernimmt vite.config.ts den Dev-Proxy.

export interface Readiness {
  date: string;
  score: number | null;
  level: string | null;
  feedback_short: string | null;
}

export interface TrendPoint {
  date: string;
  avg_hrv: number | null;
  sleep_hours: number | null;
  resting_hr: number | null;
  body_battery_max: number | null;
}

export interface Trends {
  days: TrendPoint[];
}

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

export const SPORT_TYPE_EMOJI: Record<SportType, string> = {
  Schwimmen: "🏊",
  Laufen: "🏃",
  Rad: "🚴",
  Krafttraining: "🏋️",
  Mobility: "🧘",
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

export interface WeeklyPlanDay {
  date: string;
  week_id: string;
  weekday: number;
  sport_type: string | null;
  session_type: string | null;
  target_zone: string | null;
  target_duration_minutes: number | null;
  target_distance_m: number | null;
  is_club_slot: boolean;
  source: string | null;
  data_quality_flag: string | null;
}

export interface WeeklyPlan {
  week_id: string;
  week_start: string;
  week_end: string;
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

export interface TrainingOutlook {
  week_id: string | null;
  training_phase: string | null;
  days_until_next_race: number | null;
}

// Woche 3: Andeutungs-Ebene, kein Gemini-Call (siehe weekly_planner.py::get_week_outlook).
export interface WeekOutlookDay {
  date: string;
  weekday: number;
  sport_type: string | null;
  hint: string | null;
}

export interface WeekOutlook {
  week_id: string;
  week_start: string;
  week_end: string;
  days: WeekOutlookDay[];
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

export function fetchReadiness(date: string): Promise<Readiness> {
  return fetch(`/api/readiness/${date}`).then((res) => handle<Readiness>(res));
}

export function fetchTrends(date: string, days = 14): Promise<Trends> {
  return fetch(`/api/trends/${date}?days=${days}`).then((res) => handle<Trends>(res));
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

export function fetchTrainingOutlook(): Promise<TrainingOutlook> {
  return fetch(`/api/training-outlook`).then((res) => handle<TrainingOutlook>(res));
}

export function fetchWeekOutlook(date: string): Promise<WeekOutlook> {
  return fetch(`/api/week-outlook/${date}`).then((res) => handle<WeekOutlook>(res));
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

// Montag der übernächsten Kalenderwoche - für die Andeutungs-Ebene ("Woche 3") im Kalender-Widget.
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
