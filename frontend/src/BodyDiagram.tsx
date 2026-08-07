import { useState } from "react";
import {
  BODY_OUTLINE_FRONT,
  BODY_OUTLINE_BACK,
  BODY_PARTS_FRONT,
  BODY_PARTS_BACK,
  BODY_PART_LABEL_DE,
  type BodyRegion,
} from "./bodyDiagramData";

// Der Original-Koordinatenraum (724x1448 je Hälfte, siehe bodyDiagramData.ts) hat oben/unten/
// seitlich deutlich mehr Leerraum, als die eigentliche Körper-Silhouette braucht - eng auf die
// tatsächliche Bounding Box aller Pfade zugeschnitten (per svgelements berechnet, +20 Rand), damit
// die Figur den verfügbaren Platz füllt statt mit Luft nach oben zu schweben.
const VIEW_BOX: Record<"front" | "back", string> = {
  front: "29 106 671 1266",
  back: "749 146 671 1225",
};

const REGION_DEFAULT_COLOR = "#8a8f98";
const REGION_HOVER_COLOR = "#f5a623";

function regionLabel(slug: BodyRegion["slug"], side?: "left" | "right"): string {
  const base = BODY_PART_LABEL_DE[slug];
  if (!side) return base;
  return `${base} ${side === "left" ? "links" : "rechts"}`;
}

// Interaktiver 2D-Körper-Dummy fürs Verletzungs-/Schmerzprotokoll (siehe BodyView.tsx) - Klick auf
// eine Region liefert ein deutsches Label (z. B. "Knie rechts"), das den Formular-Text vorbefüllt.
// Pfaddaten adaptiert aus react-native-body-highlighter (MIT, siehe bodyDiagramData.ts).
function BodyDiagram({
  onSelect,
  selectedLabel,
}: {
  onSelect: (label: string) => void;
  selectedLabel?: string | null;
}) {
  const [view, setView] = useState<"front" | "back">("front");
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);

  const regions = view === "front" ? BODY_PARTS_FRONT : BODY_PARTS_BACK;

  function renderRegion(region: BodyRegion) {
    const segments: { d: string; side?: "left" | "right" }[] = [
      ...(region.path.common ?? []).map((d) => ({ d })),
      ...(region.path.left ?? []).map((d) => ({ d, side: "left" as const })),
      ...(region.path.right ?? []).map((d) => ({ d, side: "right" as const })),
    ];

    return segments.map(({ d, side }, i) => {
      const key = `${region.slug}:${side ?? "common"}`;
      const label = regionLabel(region.slug, side);
      const isHovered = hoveredKey === key;
      const isSelected = selectedLabel === label;
      const fill = isSelected ? "var(--accent)" : isHovered ? REGION_HOVER_COLOR : REGION_DEFAULT_COLOR;

      return (
        <path
          key={`${key}:${i}`}
          d={d}
          fill={fill}
          fillOpacity={isSelected || isHovered ? 0.9 : 0.5}
          stroke={isSelected ? "var(--accent)" : "none"}
          strokeWidth={isSelected ? 2 : 0}
          vectorEffect="non-scaling-stroke"
          className="body-diagram-region"
          onMouseEnter={() => setHoveredKey(key)}
          onMouseLeave={() => setHoveredKey((h) => (h === key ? null : h))}
          onClick={() => onSelect(label)}
        >
          <title>{label}</title>
        </path>
      );
    });
  }

  return (
    <div className="body-diagram">
      <div className="body-diagram-toggle">
        <button type="button" className={view === "front" ? "active" : ""} onClick={() => setView("front")}>
          Vorderseite
        </button>
        <button type="button" className={view === "back" ? "active" : ""} onClick={() => setView("back")}>
          Rückseite
        </button>
      </div>
      <svg viewBox={VIEW_BOX[view]} className="body-diagram-svg">
        <path
          d={view === "front" ? BODY_OUTLINE_FRONT : BODY_OUTLINE_BACK}
          fill="none"
          stroke="var(--border)"
          strokeWidth={2}
          vectorEffect="non-scaling-stroke"
        />
        {regions.map((region) => renderRegion(region))}
      </svg>
    </div>
  );
}

export default BodyDiagram;
