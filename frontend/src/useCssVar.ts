import { useEffect, useState } from "react";

// Canvas (Chart.js) kann CSS-Custom-Properties nicht selbst auflösen, anders als SVG-Attribute
// oder normale CSS-Boxen (dort funktionierte var(--accent) bisher "kostenlos" direkt als
// stroke-Wert). Liest den aktuellen Wert per getComputedStyle und aktualisiert bei Theme-Wechsel -
// sowohl explizites data-theme (siehe theme.ts) als auch die System-Einstellung im "system"-Modus,
// die dort bewusst rein CSS-gesteuert ist (kein anderer Teil der App braucht einen JS-Listener).
export function useCssVar(name: string): string {
  const read = () => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const [value, setValue] = useState(read);

  useEffect(() => {
    const update = () => setValue(read());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", update);
    };
  }, [name]);

  return value;
}
