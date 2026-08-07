import { useEffect, useState } from "react";
import {
  todayIso,
  fetchReadinessOverview,
  fetchRecommendation,
  postOverride,
  type ReadinessOverview,
  type Recommendation,
  type OverrideValue,
} from "./api";
import HrvCard from "./HrvCard";
import JournalCard from "./JournalCard";
import ReadinessGauge from "./ReadinessGauge";
import Icon from "./Icon";

// Garmins feedback_short ist ein SCREAMING_SNAKE_CASE-Kurzcode - anhand echter synchronisierter
// Werte übersetzt (12 beobachtete Ausprägungen, siehe Ground-Truth-Check), nicht geraten. UNKNOWN
// ist Garmins eigener "kein klares Signal"-Wert - zeigt bewusst nichts an statt "Unbekannt".
const READINESS_FEEDBACK_DE: Record<string, string> = {
  LET_YOUR_BODY_RECOVER: "Lass deinem Körper Zeit zur Erholung",
  IMPROVED_BY_NAPPING: "Durch ein Nickerchen verbessert",
  GOOD_SLEEP_LAST_NIGHT: "Guter Schlaf letzte Nacht",
  ENERGIZING_NAP: "Belebendes Nickerchen",
  RESTED_AND_READY: "Ausgeruht und bereit",
  ENERGIZED_BY_GOOD_SLEEP: "Durch guten Schlaf energiegeladen",
  WELL_RECOVERED: "Gut erholt",
  HIGH_RECOVERY_NEEDS: "Hoher Erholungsbedarf",
  GOOD_SLEEP_HISTORY: "Gute Schlafhistorie",
  BOOSTED_BY_GOOD_SLEEP: "Durch guten Schlaf gestärkt",
  LISTEN_TO_YOUR_BODY: "Höre auf deinen Körper",
  EXCELLENT_RECOVERY: "Ausgezeichnete Erholung",
};

function translateFeedbackShort(raw: string | null): string | null {
  if (!raw || raw === "UNKNOWN") return null;
  return READINESS_FEEDBACK_DE[raw] ?? raw;
}

// Garmins eigene Faktoren-Aufschlüsselung des Trainingsbereitschafts-Scores (garmin_training_
// readiness) - ground-truth-verifiziert nur diese vier Ausprägungen + NONE (kein Signal) über die
// komplette bisherige Sync-Historie. NONE zeigt bewusst keinen Status an (analog zu hrv_status
// UNKNOWN), statt einen nicht vorhandenen Zustand vorzutäuschen.
const FACTOR_FEEDBACK_LABEL_DE: Record<string, string> = {
  VERY_GOOD: "Sehr gut",
  GOOD: "Gut",
  MODERATE: "Mittel",
  POOR: "Niedrig",
};

// Dieselbe Grün/Orange/Rot-Ampel wie überall sonst in der App.
const FACTOR_FEEDBACK_DOT_CLASS: Record<string, string> = {
  VERY_GOOD: "readiness-factor-dot-good",
  GOOD: "readiness-factor-dot-good",
  MODERATE: "readiness-factor-dot-moderate",
  POOR: "readiness-factor-dot-poor",
};

// Einzelner Faktor (Label + Wert links, übersetzter Status + Ampel-Punkt rechts) - angelehnt an die
// "Faktoren"-Liste in der Garmin-Connect-App selbst. Ganze Zeile wird ausgelassen, wenn für diesen
// Faktor gar kein Wert vorliegt (kein "–"-Platzhalter, der nur Rauschen wäre).
function ReadinessFactorRow({
  label,
  value,
  feedback,
}: {
  label: string;
  value: string | null;
  feedback: string | null;
}) {
  if (value == null) return null;
  const statusLabel = feedback ? FACTOR_FEEDBACK_LABEL_DE[feedback] : undefined;
  const dotClass = feedback ? FACTOR_FEEDBACK_DOT_CLASS[feedback] : undefined;
  return (
    <div className="readiness-factor-row">
      <div>
        <div className="readiness-factor-label">{label}</div>
        <div className="readiness-factor-value">{value}</div>
      </div>
      {statusLabel && dotClass && (
        <span className="readiness-factor-status">
          {statusLabel}
          <span className={`readiness-factor-dot ${dotClass}`} />
        </span>
      )}
    </div>
  );
}

// acwr/sleep_history/stress_history haben keinen eigenen Rohwert wie Sleep-Score/HRV (siehe
// backend/routers/performance.py) - dort wird bewusst Garmins eigener 0-100-Beitragswert als "Wert"
// gezeigt statt eine Kennzahl zu erfinden. recovery_time_minutes wird auf volle Stunden gerundet
// (Garmins eigene App zeigt "Erholungszeit" ebenfalls in h, nicht in Minuten).
function ReadinessFactorsList({ overview }: { overview: ReadinessOverview | null }) {
  if (!overview) return null;
  const recoveryHours =
    overview.recovery_time_minutes != null ? Math.round(overview.recovery_time_minutes / 60) : null;
  return (
    // 2 Spalten x 3 Zeilen statt einer langen Liste - nach logischen Paaren sortiert (nicht
    // Garmins API-Reihenfolge): Sleep Score aktuell/Historie, HRV/Stress (beides autonome-
    // Nervensystem-Marker), Erholungszeit/Akute Belastung (beides Trainingslast-bezogen).
    <div className="readiness-factors-list">
      <ReadinessFactorRow
        label="Sleep Score"
        value={overview.sleep_score != null ? `${overview.sleep_score}` : null}
        feedback={overview.sleep_score_factor_feedback}
      />
      <ReadinessFactorRow
        label="Kürzliche Sleep Scores"
        value={overview.sleep_history_factor_percent != null ? `${overview.sleep_history_factor_percent}%` : null}
        feedback={overview.sleep_history_factor_feedback}
      />
      <ReadinessFactorRow
        label="HFV-Status"
        value={overview.hrv_weekly_average != null ? `${overview.hrv_weekly_average} ms` : null}
        feedback={overview.hrv_factor_feedback}
      />
      <ReadinessFactorRow
        label="Kürzlicher Stress"
        value={overview.stress_history_factor_percent != null ? `${overview.stress_history_factor_percent}%` : null}
        feedback={overview.stress_history_factor_feedback}
      />
      <ReadinessFactorRow
        label="Erholungszeit"
        value={recoveryHours != null ? `${recoveryHours}h` : null}
        feedback={overview.recovery_time_factor_feedback}
      />
      <ReadinessFactorRow
        label="Akute Belastung"
        value={overview.acwr_factor_percent != null ? `${overview.acwr_factor_percent}%` : null}
        feedback={overview.acwr_factor_feedback}
      />
    </div>
  );
}

// Kopfzeile (Label + Empfehlungssatz) steht neben dem Gauge; Begründungs-Bullets + Override-
// Buttons bleiben darunter in voller Breite (siehe ReadinessCard). Während overriding blendet der
// Text auf reduzierte Deckkraft ab (siehe .is-updating in App.css) - sobald die neu berechnete
// Empfehlung eintrifft, ersetzt sie den Inhalt und blendet wieder auf volle Deckkraft ein.
function RecommendationHeadline({
  recommendation,
  loading,
  overriding,
}: {
  recommendation: Recommendation | null;
  loading: boolean;
  overriding: boolean;
}) {
  return (
    <div className="recommendation-panel">
      <div className="recommendation-label">Empfehlung heute</div>
      {recommendation ? (
        <p className={`recommendation-text${overriding ? " is-updating" : ""}`}>{recommendation.recommendation_text}</p>
      ) : (
        <p>{loading ? "Lade Empfehlung…" : "Keine Empfehlung verfügbar."}</p>
      )}
    </div>
  );
}

function RecommendationDetails({
  recommendation,
  overriding,
  onOverride,
}: {
  recommendation: Recommendation | null;
  overriding: boolean;
  onOverride: (value: OverrideValue) => void;
}) {
  return (
    <>
      {recommendation && (
        <ul className={`reasoning-bullets${overriding ? " is-updating" : ""}`}>
          {recommendation.reasoning_bullets.map((bullet, i) => (
            <li key={i}>{bullet}</li>
          ))}
        </ul>
      )}
      <div className="override-buttons">
        <button className="override-button-better" disabled={overriding} onClick={() => onOverride("better")}>
          Fühle mich besser
        </button>
        <button className="override-button-worse" disabled={overriding} onClick={() => onOverride("worse")}>
          Fühle mich schlechter
        </button>
      </div>
      {overriding && (
        <p className="override-status">
          <Icon name="autorenew" className="override-status-icon" /> Empfehlung wird neu berechnet…
        </p>
      )}
    </>
  );
}

// Trainingsbereitschaft: Gauge links, Garmins Faktoren-Liste rechts daneben (readiness-card-top,
// angelehnt an die Faktoren-Ansicht der Garmin-Connect-App) - Empfehlung heute + Begründungs-
// Bullets/Override-Buttons folgen darunter in voller Kartenbreite. Gleiche Karten-Breitenklassen
// wie auf der Leistung-Seite (performance-card-narrow/-wide), da hier dieselben Komponenten
// (ReadinessGauge/HrvCard) wie dort verwendet werden.
function ReadinessCard({
  overview,
  recommendation,
  loading,
  overriding,
  onOverride,
}: {
  overview: ReadinessOverview | null;
  recommendation: Recommendation | null;
  loading: boolean;
  overriding: boolean;
  onOverride: (value: OverrideValue) => void;
}) {
  const feedback = translateFeedbackShort(overview?.feedback_short ?? null);
  return (
    <div className="card performance-card performance-card-narrow">
      <h3>
        Trainingsbereitschaft
        {feedback && <span className="tier-kw"> · {feedback}</span>}
      </h3>
      <div className="readiness-card-top">
        <div className="readiness-card-gauge-col">
          <ReadinessGauge score={overview?.score ?? null} level={overview?.level ?? null} />
        </div>
        <ReadinessFactorsList overview={overview} />
      </div>
      <RecommendationHeadline recommendation={recommendation} loading={loading} overriding={overriding} />
      <RecommendationDetails recommendation={recommendation} overriding={overriding} onOverride={onOverride} />
    </div>
  );
}

function TodayView() {
  const today = todayIso();
  const [overview, setOverview] = useState<ReadinessOverview | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [recommendationLoading, setRecommendationLoading] = useState(true);
  const [overriding, setOverriding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchReadinessOverview(today)
      .then(setOverview)
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

  return (
    <div className="today-view">
      {error && <p className="error-banner">Fehler: {error}</p>}
      <JournalCard date={today} />
      <div className="performance-row">
        <ReadinessCard
          overview={overview}
          recommendation={recommendation}
          loading={recommendationLoading}
          overriding={overriding}
          onOverride={handleOverride}
        />
        <HrvCard overview={overview} />
      </div>
    </div>
  );
}

export default TodayView;
