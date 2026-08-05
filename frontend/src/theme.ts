import { useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const STORAGE_KEY = "health-dashboard-theme";

function readStoredTheme(): ThemeChoice {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
}

// "system" entfernt data-theme wieder - die vorhandene @media (prefers-color-scheme: dark)-Regel
// in index.css greift dann automatisch, inkl. Live-Reaktion auf spätere OS-Theme-Wechsel (rein
// CSS-gesteuert, kein matchMedia-Listener nötig).
export function useTheme(): [ThemeChoice, (theme: ThemeChoice) => void] {
  const [theme, setTheme] = useState<ThemeChoice>(readStoredTheme);

  useEffect(() => {
    if (theme === "system") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", theme);
    }
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  return [theme, setTheme];
}
