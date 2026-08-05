import { useEffect, useState } from "react";
import {
  todayIso,
  nextMondayIso,
  weekAfterNextMondayIso,
  formatShortDate,
  fetchWeeklyPlan,
  fetchWeekOutlook,
  fetchWorkoutDraft,
  uploadWorkoutDraft,
  fetchTrainingOutlook,
  fetchFarWeeksOutlook,
  workoutBuilderUrl,
  SPORT_TYPE_EMOJI,
  type SportType,
  type WeeklyPlan,
  type WeeklyPlanDay,
  type WeekOutlook,
  type WorkoutDraft,
  type TrainingOutlook,
  type FarWeekBar,
} from "./api";

const WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

function isSportType(value: string | null): value is SportType {
  return value !== null && value in SPORT_TYPE_EMOJI;
}

// week_id ist "YYYY-Wnn" (siehe weekly_planner.py::_week_bounds) - reines String-Splitting statt
// erneuter Datumsberechnung im Frontend.
function isoWeekNumber(weekId: string): string {
  return weekId.split("-W")[1] ?? "?";
}

// weekly_plan.sport_type ist Freitext vom Gemini-Modell, aber per System-Prompt auf exakt die
// SPORT_TYPES-Werte beschränkt (siehe weekly_planner.py) - Fallback nur als Sicherheitsnetz.
function planDayIcon(day: { sport_type: string | null; source: string | null }): string {
  if (day.source === "race") return "🏁";
  if (isSportType(day.sport_type)) return SPORT_TYPE_EMOJI[day.sport_type];
  return day.sport_type ? "🏃" : "😴";
}

// Nächste/Übernächste Woche zeigen die Sportart als Emoji statt als Wort (kompaktere Zeilen) -
// gleiche Icon-Logik wie planDayIcon, nur anhand des hint-Texts statt eines source-Felds, da
// WeekOutlookDay kein source hat (siehe get_week_outlook()).
function outlookIcon(day: { sport_type: string | null; hint: string | null }): string {
  if (day.hint?.startsWith("Wettkampf:")) return "🏁";
  if (isSportType(day.sport_type)) return SPORT_TYPE_EMOJI[day.sport_type];
  return day.sport_type ? "🏃" : "😴";
}

// hint kommt vom Backend als vollständiger Satz ("Laufen (Longrun)", "Wettkampf: <Titel>") - das
// Icon deckt die Sportart bereits ab (outlookIcon), hier nur noch der kurze Zusatz-Teil, damit die
// Zeile so schlank wie möglich bleibt. Backend umschließt den Zusatz-Teil immer mit genau einem
// äußeren Klammernpaar (f"{sport_type} ({session_hint})", siehe get_week_outlook()) - deshalb nur
// das äußere Klammernpaar abschneiden statt mit einer Regex nach "(...)" zu suchen, da session_hint
// selbst verschachtelte Klammern enthalten kann (z.B. "Laufen (Langer Lauf (Marathon-Vorbereitung))").
function outlookDetail(day: { sport_type: string | null; hint: string | null }): string | null {
  if (!day.hint) return null;
  if (day.hint.startsWith("Wettkampf: ")) return day.hint.slice("Wettkampf: ".length);
  if (!day.sport_type || !day.hint.startsWith(day.sport_type)) return null;
  const rest = day.hint.slice(day.sport_type.length).trim();
  if (!rest.startsWith("(") || !rest.endsWith(")")) return null;
  return rest.slice(1, -1);
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
      <div className="plan-day-icon">{planDayIcon(day)}</div>
      <div className="plan-day-session">{day.session_type ?? (day.sport_type ? day.sport_type : "Ruhetag")}</div>
      {(detail.length > 0 || day.target_zone) && (
        <div className="plan-day-detail">
          {detail.join(" · ")}
          {day.target_zone && ` · Zone ${day.target_zone}`}
        </div>
      )}
      {draft?.id != null && (
        <div className="plan-day-actions">
          {draft.uploaded ? (
            <span className="plan-day-uploaded">✅ Hochgeladen</span>
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

function PlanWeekTier({ title, plan, phase }: { title: string; plan: WeeklyPlan | null; phase: string | null }) {
  return (
    <div className="card calendar-tier">
      <h2>
        {title}
        {plan && (
          <span className="tier-kw">
            {" "}
            · KW {isoWeekNumber(plan.week_id)} ({formatShortDate(plan.week_start)}–{formatShortDate(plan.week_end)})
          </span>
        )}
        {phase && <span className="tier-phase"> · {phase}</span>}
      </h2>
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

// Nächste Woche + Übernächste Woche: gleiche Regeln (nur eine kurze Tages-Andeutung je Sportart-
// Emoji, keine Workout-Details, kein Gemini-Call, siehe get_week_outlook()) - einziger Unterschied
// ist Titel/Opacity-Stufe (tierVariant).
function WeekOutlookTier({
  title,
  outlook,
  phase,
  tierVariant,
}: {
  title: string;
  outlook: WeekOutlook | null;
  phase: string | null;
  tierVariant: "week2" | "week3";
}) {
  return (
    <div className={`card calendar-tier calendar-tier-outlook calendar-tier-${tierVariant}`}>
      <h3>
        {title}
        {outlook && (
          <span className="tier-kw">
            {" "}
            · KW {isoWeekNumber(outlook.week_id)} ({formatShortDate(outlook.week_start)}–{formatShortDate(outlook.week_end)})
          </span>
        )}
        {phase && <span className="tier-phase"> · {phase}</span>}
      </h3>
      {outlook ? (
        <div className="outlook-row">
          {outlook.days.map((day) => {
            const detail = outlookDetail(day);
            return (
              <div key={day.date} className="outlook-day-chip">
                <div className="outlook-day-weekday">
                  {WEEKDAY_LABELS[day.weekday]} <span className="outlook-day-date">{formatShortDate(day.date)}</span>
                </div>
                <div className="outlook-day-icon">{outlookIcon(day)}</div>
                {detail && <div className="outlook-day-hint">{detail}</div>}
              </div>
            );
          })}
        </div>
      ) : (
        <p>Lade…</p>
      )}
    </div>
  );
}

// Ab Woche 4: eine Zeile/Balken pro Woche bis zum nächsten Rennen (siehe weekly_planner.py::
// get_far_weeks_outlook). Rendert nichts, falls kein Rennen mehr ansteht - "wenn kein Wettkampf
// mehr ansteht, dann ist nach Woche 3 Schluss".
function FarWeeksBars({ weeks }: { weeks: FarWeekBar[] | null }) {
  if (!weeks || weeks.length === 0) return null;

  return (
    <div className="card calendar-tier calendar-tier-far">
      {weeks.map((week) => (
        <div key={week.week_id} className={`far-week-bar${week.race_title ? " far-week-bar-race" : ""}`}>
          <span className="far-week-bar-kw">KW {week.iso_week}</span>
          <span className="far-week-bar-range">
            {formatShortDate(week.week_start)}–{formatShortDate(week.week_end)}
          </span>
          {week.race_title ? (
            <span className="far-week-bar-race-label">
              🏁 {week.race_title} ({formatShortDate(week.race_date ?? week.week_end)})
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
  const [nextWeekOutlook, setNextWeekOutlook] = useState<WeekOutlook | null>(null);
  const [weekAfterNextOutlook, setWeekAfterNextOutlook] = useState<WeekOutlook | null>(null);
  const [outlook, setOutlook] = useState<TrainingOutlook | null>(null);
  const [farWeeks, setFarWeeks] = useState<FarWeekBar[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchWeeklyPlan(todayIso())
      .then(setThisWeek)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    // Nächste + übernächste Woche folgen jetzt denselben Regeln (kurze Andeutung, kein Gemini-
    // Call) - der konkrete Gemini-Plan für nächste Woche wird trotzdem weiterhin vom Sonntags-
    // Trigger in auto_sync.py vorbereitet, nur nicht mehr hier angezeigt, sondern erst, wenn diese
    // Woche zu "Diese Woche" wird.
    fetchWeekOutlook(nextMondayIso())
      .then(setNextWeekOutlook)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchWeekOutlook(weekAfterNextMondayIso())
      .then(setWeekAfterNextOutlook)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchTrainingOutlook()
      .then(setOutlook)
      .catch(() => setOutlook(null));
    fetchFarWeeksOutlook(todayIso())
      .then((res) => setFarWeeks(res.weeks))
      .catch(() => setFarWeeks([]));
  }, []);

  const phase = outlook?.training_phase ?? null;

  return (
    <div className="weekly-calendar-widget">
      {error && <p className="error-banner">Fehler: {error}</p>}
      <PlanWeekTier title="Diese Woche" plan={thisWeek} phase={phase} />
      <WeekOutlookTier title="Nächste Woche" outlook={nextWeekOutlook} phase={phase} tierVariant="week2" />
      <WeekOutlookTier title="Übernächste Woche" outlook={weekAfterNextOutlook} phase={phase} tierVariant="week3" />
      <FarWeeksBars weeks={farWeeks} />
    </div>
  );
}

export default WeeklyCalendarWidget;
