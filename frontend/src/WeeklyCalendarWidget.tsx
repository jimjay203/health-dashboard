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
  type WorkoutDraft,
  type FarWeekBar,
} from "./api";
import Icon from "./Icon";

const WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

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

function PlanDay({ day }: { day: WeeklyPlanDay }) {
  const [draft, setDraft] = useState<WorkoutDraft | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  useEffect(() => {
    fetchWorkoutDraft(day.date)
      .then(setDraft)
      .catch(() => setDraft(null));
  }, [day.date]);

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

  return (
    <div className={`plan-day${day.date === todayIso() ? " today" : ""}`}>
      <div className="plan-day-weekday">
        {WEEKDAY_LABELS[day.weekday]} <span className="plan-day-date">{formatShortDate(day.date)}</span>
      </div>
      <div className="plan-day-icon">
        <Icon name={planDayIconName(day)} />
      </div>
      <div className="plan-day-session">{day.session_type ?? (day.sport_type ? day.sport_type : "Ruhetag")}</div>
      {(detail.length > 0 || day.target_zone) && (
        <div className="plan-day-detail">
          {detail.join(" · ")}
          {day.target_zone && ` · Zone ${day.target_zone}`}
        </div>
      )}
      {day.is_key_session && (
        <div className="plan-day-key-badge">
          <Icon name="star" /> Kern-Einheit
        </div>
      )}
      {draft?.id != null && (
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
          </span>
          {week.race_title ? (
            <span className="far-week-bar-race-label">
              <Icon name="flag" /> {week.race_title} ({formatShortDate(week.race_date ?? week.week_end)})
            </span>
          ) : (
            <span className="far-week-bar-phase">{week.training_phase ?? "–"}</span>
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
