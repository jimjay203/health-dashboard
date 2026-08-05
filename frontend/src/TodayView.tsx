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
import ReadinessGauge from "./ReadinessGauge";

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
};

function translateFeedbackShort(raw: string | null): string | null {
  if (!raw || raw === "UNKNOWN") return null;
  return READINESS_FEEDBACK_DE[raw] ?? raw;
}

// Kopfzeile (Label + Empfehlungssatz) steht neben dem Gauge; Begründungs-Bullets + Override-
// Buttons bleiben darunter in voller Breite (siehe ReadinessCard).
function RecommendationHeadline({
  recommendation,
  loading,
}: {
  recommendation: Recommendation | null;
  loading: boolean;
}) {
  return (
    <div className="recommendation-panel">
      <div className="recommendation-label">Empfehlung heute</div>
      {recommendation ? (
        <p className="recommendation-text">{recommendation.recommendation_text}</p>
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
        <ul className="reasoning-bullets">
          {recommendation.reasoning_bullets.map((bullet, i) => (
            <li key={i}>{bullet}</li>
          ))}
        </ul>
      )}
      <div className="override-buttons">
        <button disabled={overriding} onClick={() => onOverride("worse")}>
          Fühle mich schlechter
        </button>
        <button disabled={overriding} onClick={() => onOverride("better")}>
          Fühle mich besser
        </button>
      </div>
    </>
  );
}

// Empfehlung heute ist komplett in die Trainingsbereitschaft-Karte integriert: Gauge links,
// Empfehlungs-Kopfzeile rechts daneben (readiness-card-top), Bullets/Buttons weiterhin volle
// Breite darunter. Gleiche Karten-Breitenklassen wie auf der Leistung-Seite
// (performance-card-narrow/-wide), da hier dieselben Komponenten (ReadinessGauge/HrvCard) wie
// dort verwendet werden.
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
        <RecommendationHeadline recommendation={recommendation} loading={loading} />
      </div>
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
