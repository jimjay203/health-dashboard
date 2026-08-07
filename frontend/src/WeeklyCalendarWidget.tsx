import { useEffect, useState } from "react";
import {
  todayIso,
  nextMondayIso,
  weekAfterNextMondayIso,
  formatShortDate,
  roundedDurationLabel,
  fetchWeeklyPlan,
  regenerateWeeklyPlan,
  fetchWorkoutDraft,
  uploadWorkoutDraft,
  fetchFarWeeksOutlook,
  workoutBuilderUrl,
  SPORT_TYPE_ICON,
  type SportType,
  type WeeklyPlan,
  type WeeklyPlanDay,
  type ActualActivity,
  type WorkoutDraft,
  type FarWeekBar,
} from "./api";
import Icon from "./Icon";

const WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

// Garmins rohe activity_type-Werte (ground-truth: pages/4_🏃_Aktivitäten.py::SPORT_ICONS deckt die
// bekannte Werteliste ab, auch wenn im eigenen Konto bisher nur running/cycling/road_biking/
// lap_swimming aufgetreten sind) - Material-Symbols-Namen statt der dortigen Emoji.
const ACTIVITY_TYPE_ICON: Record<string, string> = {
  running: "directions_run",
  trail_running: "directions_run",
  treadmill_running: "directions_run",
  track_running: "directions_run",
  street_running: "directions_run",
  indoor_running: "directions_run",
  ultra_run: "directions_run",
  cycling: "directions_bike",
  road_biking: "directions_bike",
  mountain_biking: "directions_bike",
  indoor_cycling: "directions_bike",
  gravel_cycling: "directions_bike",
  cyclocross: "directions_bike",
  lap_swimming: "pool",
  open_water_swimming: "pool",
  walking: "directions_walk",
  casual_walking: "directions_walk",
  speed_walking: "directions_walk",
  strength_training: "fitness_center",
  multi_sport: "swap_horiz",
};

const ACTIVITY_TYPE_LABEL_DE: Record<string, string> = {
  running: "Laufen",
  trail_running: "Trail-Lauf",
  treadmill_running: "Laufband",
  track_running: "Bahnlauf",
  street_running: "Straßenlauf",
  indoor_running: "Indoor-Lauf",
  ultra_run: "Ultra-Lauf",
  cycling: "Rad",
  road_biking: "Rad",
  mountain_biking: "Mountainbike",
  indoor_cycling: "Indoor-Rad",
  gravel_cycling: "Gravel-Rad",
  cyclocross: "Cyclocross",
  lap_swimming: "Schwimmen",
  open_water_swimming: "Freiwasser",
  walking: "Gehen",
  casual_walking: "Gehen",
  speed_walking: "Gehen",
  strength_training: "Kraft",
  multi_sport: "Brick",
};

function activityIconName(activityType: string | null): string {
  return activityType ? ACTIVITY_TYPE_ICON[activityType] ?? "sports" : "sports";
}

function activityLabel(activityType: string | null): string {
  return activityType ? ACTIVITY_TYPE_LABEL_DE[activityType] ?? activityType : "Aktivität";
}

function isSportType(value: string | null): value is SportType {
  return value !== null && value in SPORT_TYPE_ICON;
}

// week_id ist "YYYY-Wnn" (siehe weekly_planner.py::_week_bounds) - reines String-Splitting statt
// erneuter Datumsberechnung im Frontend.
function isoWeekNumber(weekId: string): string {
  return weekId.split("-W")[1] ?? "?";
}

// weekly_plan.sport_type ist Freitext vom Gemini-Modell, aber per System-Prompt auf exakt die
// SPORT_TYPES-Werte beschränkt (siehe weekly_planner.py) - Fallback nur als Sicherheitsnetz.
// Gibt einen Material-Symbols-Icon-Namen zurück (siehe Icon.tsx), keinen Emoji-Zeichen mehr.
function planDayIconName(day: { sport_type: string | null; source: string | null }): string {
  if (day.source === "race") return "flag";
  if (isSportType(day.sport_type)) return SPORT_TYPE_ICON[day.sport_type];
  return day.sport_type ? "directions_run" : "bedtime";
}

// Reduzierte Ansicht (Nächste/Übernächste Woche): nur das kurze Stichwort, ohne die
// Klammer-Erklärung/Begründung dahinter (z.B. "Langer Lauf (Marathon-Vorbereitung)" ->
// "Langer Lauf") - die gehört in die fixierte Woche, nicht in die grobe Vorschau.
function shortSessionLabel(day: { session_type: string | null; sport_type: string | null }): string {
  const text = day.session_type ?? (day.sport_type ? day.sport_type : "Ruhetag");
  return text.split("(")[0].trim();
}

// Minuten statt Sekunden (roundedDurationLabel rundet auf eine grobe Leiter für die reduzierte
// Ansicht - hier soll die tatsächlich absolvierte Dauer exakt stehen, analog zu detail oben).
function formatActualDuration(seconds: number | null): string | null {
  if (!seconds) return null;
  return `${Math.round(seconds / 60)}min`;
}

// Eine Zeile pro tatsächlich absolvierter Aktivität (garmin_activities) - mehrere möglich (z.B.
// Brick-Training), deshalb eine Liste statt eines einzelnen Werts.
function ActualActivityRow({ activity }: { activity: ActualActivity }) {
  const detail = [
    formatActualDuration(activity.duration_seconds),
    activity.distance_meters ? `${(activity.distance_meters / 1000).toFixed(1)}km` : null,
  ].filter((v): v is string => v !== null);
  return (
    <div className="plan-day-actual-row">
      <Icon name={activityIconName(activity.activity_type)} /> {activityLabel(activity.activity_type)}
      {detail.length > 0 && <span className="plan-day-actual-detail"> · {detail.join(" · ")}</span>}
    </div>
  );
}

function PlanDay({ day }: { day: WeeklyPlanDay }) {
  const [draft, setDraft] = useState<WorkoutDraft | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const isToday = day.date === todayIso();
  // Nur echt vergangene Tage (< heute) zeigen Ist statt Plan - "heute" ist noch nicht "abgelaufen",
  // auch wenn schon eine Aktivität erfasst sein sollte.
  const isPast = day.date < todayIso();

  useEffect(() => {
    // Für vergangene Tage gibt es keinen Workout-Entwurf-Upload mehr (der Tag ist vorbei) - Fetch
    // sparen, die Actions-Zeile wird ohnehin nicht gerendert.
    if (isPast) return;
    fetchWorkoutDraft(day.date)
      .then(setDraft)
      .catch(() => setDraft(null));
  }, [day.date, isPast]);

  async function handleUpload() {
    if (!draft?.id) return;
    setUploading(true);
    setUploadError(null);
    try {
      // Lädt hoch UND plant das Workout direkt für diesen Tag in den Garmin-Kalender ein
      // (siehe backend/routers/weekly_plan.py::upload_workout_draft).
      const result = await uploadWorkoutDraft(draft.id);
      if (result.success) {
        setDraft({ ...draft, uploaded: true });
      } else {
        setUploadError(result.error ?? "Upload fehlgeschlagen.");
      }
    } catch (e: unknown) {
      setUploadError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }

  const detail: string[] = [];
  if (day.target_duration_minutes) detail.push(`${day.target_duration_minutes.toFixed(0)}min`);
  if (day.target_distance_m) detail.push(`${(day.target_distance_m / 1000).toFixed(1)}km`);
  const plannedWorkout = day.sport_type != null;
  const wasCompleted = day.actual_activities.length > 0;

  return (
    <div
      className={`plan-day${isToday ? " today" : ""}${day.is_key_session ? " key-session" : ""}${
        isPast ? " past" : ""
      }`}
    >
      <div className="plan-day-weekday">
        {WEEKDAY_LABELS[day.weekday]} <span className="plan-day-date">{formatShortDate(day.date)}</span>
      </div>

      {isPast ? (
        // Vergangener Tag: Ist statt Plan (siehe backend/routers/weekly_plan.py::
        // _actual_activities_by_date) - die Planung steht bei Abweichung nur noch klein als
        // Vergleich darunter, ohne Aktivität ("Nicht absolviert") nur, wenn tatsächlich etwas
        // geplant war - ein geplanter Ruhetag ohne Aktivität ist kein Compliance-Problem.
        <>
          {wasCompleted ? (
            <div className="plan-day-actual-list">
              {day.actual_activities.map((activity, i) => (
                <ActualActivityRow key={i} activity={activity} />
              ))}
            </div>
          ) : (
            <>
              <div className="plan-day-icon">
                <Icon name={plannedWorkout ? "cancel" : "bedtime"} />
              </div>
              <div className="plan-day-session">{plannedWorkout ? "Nicht absolviert" : "Ruhetag"}</div>
            </>
          )}
          {plannedWorkout && (
            <div className="plan-day-plan-comparison">
              Plan: {day.session_type ?? day.sport_type}
              {detail.length > 0 && ` (${detail.join(" · ")})`}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="plan-day-icon">
            <Icon name={planDayIconName(day)} />
          </div>
          <div className="plan-day-session">{day.session_type ?? (day.sport_type ? day.sport_type : "Ruhetag")}</div>
          {/* Nur bei tatsächlicher Sportart - Dauer/Distanz/Zone sind an einem Ruhetag bedeutungslos
              (Ground-Truth-Fund: weekly_planner.py hat "Zone 1" auf einem Ruhetag ohne sport_type
              zurückgegeben; backend-seitig jetzt normalisiert, hier zusätzlich defensiv, falls noch
              ältere ungenerierte Zeilen ohne die Normalisierung angezeigt werden). */}
          {day.sport_type && (detail.length > 0 || day.target_zone) && (
            <div className="plan-day-detail">
              {detail.join(" · ")}
              {day.target_zone && ` · Zone ${day.target_zone}`}
            </div>
          )}
        </>
      )}

      {day.is_key_session && (
        <div className="plan-day-key-badge">
          <Icon name="star" /> Kern-Einheit
        </div>
      )}
      {!isPast && draft?.id != null && (
        <div className="plan-day-actions">
          {draft.uploaded ? (
            <span className="plan-day-uploaded">
              <Icon name="check_circle" /> Hochgeladen
            </span>
          ) : (
            <button disabled={uploading} onClick={handleUpload}>
              {uploading ? "…" : "Hochladen"}
            </button>
          )}
          <a href={workoutBuilderUrl(draft.id)} target="_blank" rel="noreferrer">
            Anpassen
          </a>
        </div>
      )}
      {uploadError && <div className="plan-day-error">{uploadError}</div>}
    </div>
  );
}

// Erzwingt eine Neu-Generierung dieser Woche (z.B. nachdem nachträglich ein Vereins-Termin
// angelegt wurde - bereits generierte Wochen aktualisieren sich sonst nicht automatisch, siehe
// backend/routers/weekly_plan.py::regenerate_weekly_plan). already_uploaded_count macht
// transparent, falls dabei schon zu Garmin hochgeladene Workout-Entwürfe ersetzt wurden (der alte
// Garmin-Termin selbst bleibt davon unberührt bestehen).
function RegenerateButton({ dateStr, onRegenerated }: { dateStr: string; onRegenerated: (plan: WeeklyPlan) => void }) {
  const [loading, setLoading] = useState(false);
  const [warning, setWarning] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setWarning(null);
    try {
      const plan = await regenerateWeeklyPlan(dateStr);
      onRegenerated(plan);
      if (plan.already_uploaded_count > 0) {
        setWarning(
          `${plan.already_uploaded_count} bereits zu Garmin hochgeladene${plan.already_uploaded_count > 1 ? "" : "r"} ` +
            `Workout-Entwurf${plan.already_uploaded_count > 1 ? "e" : ""} wurde${plan.already_uploaded_count > 1 ? "n" : ""} ` +
            "lokal ersetzt - der bestehende Garmin-Termin bleibt unverändert, ggf. dort manuell aufräumen."
        );
      }
    } catch (e: unknown) {
      setWarning(e instanceof Error ? e.message : String(e));
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
        title="Woche neu generieren"
      >
        <Icon name="refresh" />
      </button>
      {warning && <p className="tier-regenerate-warning">{warning}</p>}
    </>
  );
}

function PlanWeekTier({
  title,
  plan,
  dateStr,
  onRegenerated,
}: {
  title: string;
  plan: WeeklyPlan | null;
  dateStr: string;
  onRegenerated: (plan: WeeklyPlan) => void;
}) {
  return (
    <div className="calendar-tier calendar-tier-current">
      <h3>
        {title}
        {plan && (
          <span className="tier-kw">
            {" "}
            · KW {isoWeekNumber(plan.week_id)} ({formatShortDate(plan.week_start)}–{formatShortDate(plan.week_end)})
          </span>
        )}
        {plan?.training_phase && <span className="tier-phase"> · {plan.training_phase}</span>}
        <RegenerateButton dateStr={dateStr} onRegenerated={onRegenerated} />
      </h3>
      {plan ? (
        <>
          {plan.week_rationale_text && <p className="week-rationale">{plan.week_rationale_text}</p>}
          <div className="plan-days-row">
            {plan.days.map((day) => (
              <PlanDay key={day.date} day={day} />
            ))}
          </div>
        </>
      ) : (
        <p>Lade Wochenplan…</p>
      )}
    </div>
  );
}

// Reduzierte Tages-Karte für Nächste/Übernächste Woche: Icon + kurzes Stichwort + gerundete Dauer,
// keine Zone/exakte Distanz/Begründungstext, keine Action-Buttons (die gibt es nur in der
// fixierten Woche). Kern-Einheiten (is_key_session) werden komplett in Akzentfarbe dargestellt,
// statt der gedämpften Sekundärfarbe - so bleiben sie auch in der reduzierten Ansicht erkennbar.
function CompactPlanDay({ day }: { day: WeeklyPlanDay }) {
  return (
    <div className={`compact-plan-day${day.is_key_session ? " key-session" : ""}`}>
      <div className="compact-plan-day-weekday">
        {WEEKDAY_LABELS[day.weekday]} <span className="compact-plan-day-date">{formatShortDate(day.date)}</span>
      </div>
      <div className="compact-plan-day-icon">
        <Icon name={planDayIconName(day)} />
      </div>
      <div className="compact-plan-day-session">{shortSessionLabel(day)}</div>
      {day.target_duration_minutes != null && (
        <div className="compact-plan-day-duration">{roundedDurationLabel(day.target_duration_minutes)}</div>
      )}
    </div>
  );
}

// Nächste Woche + Übernächste Woche: dieselbe Datengrundlage wie "Diese Woche" (echter,
// Gemini-generierter weekly_plan - siehe get_weekly_plan-Endpoint), aber reduziert dargestellt
// (CompactPlanDay statt PlanDay) - spürbar weniger Detailtiefe, aber genug für die grobe
// Zeitplanung pro Tag. Einziger Unterschied zwischen den beiden: Titel/Opacity-Stufe (tierVariant).
function CompactWeekTier({
  title,
  plan,
  tierVariant,
  dateStr,
  onRegenerated,
}: {
  title: string;
  plan: WeeklyPlan | null;
  tierVariant: "week2" | "week3";
  dateStr: string;
  onRegenerated: (plan: WeeklyPlan) => void;
}) {
  return (
    <div className={`calendar-tier calendar-tier-compact calendar-tier-${tierVariant}`}>
      <h3>
        {title}
        {plan && (
          <span className="tier-kw">
            {" "}
            · KW {isoWeekNumber(plan.week_id)} ({formatShortDate(plan.week_start)}–{formatShortDate(plan.week_end)})
          </span>
        )}
        {plan?.training_phase && <span className="tier-phase"> · {plan.training_phase}</span>}
        <RegenerateButton dateStr={dateStr} onRegenerated={onRegenerated} />
      </h3>
      {plan ? (
        <div className="compact-plan-days-row">
          {plan.days.map((day) => (
            <CompactPlanDay key={day.date} day={day} />
          ))}
        </div>
      ) : (
        <p>Lade…</p>
      )}
    </div>
  );
}

// Ab Woche 4: eine Zeile/Balken pro Woche bis zum nächsten Rennen (siehe weekly_planner.py::
// get_far_weeks_outlook). Rendert nichts, falls kein Rennen mehr ansteht - "wenn kein Wettkampf
// mehr ansteht, dann ist nach Übernächste Woche Schluss".
function FarWeeksBars({ weeks }: { weeks: FarWeekBar[] | null }) {
  if (!weeks || weeks.length === 0) return null;

  return (
    <div className="calendar-tier calendar-tier-far">
      {weeks.map((week) => (
        <div key={week.week_id} className={`far-week-bar${week.race_title ? " far-week-bar-race" : ""}`}>
          <span className="far-week-bar-kw">KW {week.iso_week}</span>
          <span className="far-week-bar-range">
            {formatShortDate(week.week_start)}–{formatShortDate(week.week_end)}
            {week.training_phase && <span className="far-week-bar-phase"> · {week.training_phase}</span>}
          </span>
          {week.race_title && (
            <span className="far-week-bar-race-label">
              <Icon name="flag" /> {week.race_title} ({formatShortDate(week.race_date ?? week.week_end)})
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function WeeklyCalendarWidget() {
  const [thisWeek, setThisWeek] = useState<WeeklyPlan | null>(null);
  const [nextWeek, setNextWeek] = useState<WeeklyPlan | null>(null);
  const [weekAfterNext, setWeekAfterNext] = useState<WeeklyPlan | null>(null);
  const [farWeeks, setFarWeeks] = useState<FarWeekBar[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchWeeklyPlan(todayIso())
      .then(setThisWeek)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    // Nächste + übernächste Woche nutzen dieselbe echte weekly_plan-Datengrundlage wie "Diese
    // Woche" (der Sonntags-Trigger in auto_sync.py hat sie i.d.R. schon vorbereitet, sonst lazy
    // generiert wie bei "Diese Woche") - nur die Darstellung ist reduziert (CompactWeekTier).
    fetchWeeklyPlan(nextMondayIso())
      .then(setNextWeek)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchWeeklyPlan(weekAfterNextMondayIso())
      .then(setWeekAfterNext)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchFarWeeksOutlook(todayIso())
      .then((res) => setFarWeeks(res.weeks))
      .catch(() => setFarWeeks([]));
  }, []);

  return (
    <div>
      {error && <p className="error-banner">Fehler: {error}</p>}
      <div className="card weekly-calendar-widget">
        <PlanWeekTier title="Diese Woche" plan={thisWeek} dateStr={todayIso()} onRegenerated={setThisWeek} />
        <CompactWeekTier
          title="Nächste Woche"
          plan={nextWeek}
          tierVariant="week2"
          dateStr={nextMondayIso()}
          onRegenerated={setNextWeek}
        />
        <CompactWeekTier
          title="Übernächste Woche"
          plan={weekAfterNext}
          tierVariant="week3"
          dateStr={weekAfterNextMondayIso()}
          onRegenerated={setWeekAfterNext}
        />
        <FarWeeksBars weeks={farWeeks} />
      </div>
    </div>
  );
}

export default WeeklyCalendarWidget;
