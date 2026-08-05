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
}

export type ClubSlotInput = Omit<ClubSlot, "id">;

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
