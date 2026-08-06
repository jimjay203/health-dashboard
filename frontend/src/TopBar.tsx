import { useEffect, useState } from "react";
import { fetchSyncStatus, triggerSync, type SyncStatus, type SyncStatusValue } from "./api";
import type { View } from "./Sidebar";
import type { ThemeChoice } from "./theme";
import Icon from "./Icon";

const PAGE_INFO: Record<View, { title: string; subtitle: string }> = {
  today: { title: "Heute", subtitle: "Dein Trainings-Status auf einen Blick." },
  week: { title: "Woche", subtitle: "Rolling-Horizon-Wochenplan und Trainingsphase." },
  performance: { title: "Leistung", subtitle: "Trainingsdiagnostik, Belastungssteuerung und Schwellenwerte." },
  settings: { title: "Einstellungen", subtitle: "Vereins-Trainingstermine und Leistungsziele verwalten." },
};

const SYNC_LABEL: Record<SyncStatusValue, { text: string; className: string }> = {
  completed: { text: "Sync OK", className: "sync-badge-ok" },
  checking: { text: "Sync läuft…", className: "sync-badge-checking" },
  gave_up: { text: "Sync ausgeblieben", className: "sync-badge-warn" },
  rate_limited: { text: "Sync ausgeblieben", className: "sync-badge-warn" },
  not_started: { text: "Sync ausstehend", className: "sync-badge-idle" },
};

const THEME_OPTIONS: { value: ThemeChoice; icon: string; label: string }[] = [
  { value: "light", icon: "light_mode", label: "Hell" },
  { value: "system", icon: "desktop_windows", label: "System" },
  { value: "dark", icon: "dark_mode", label: "Dunkel" },
];

function formatClock(date: Date): string {
  const datePart = new Intl.DateTimeFormat("de-DE", {
    weekday: "long",
    day: "2-digit",
    month: "long",
  }).format(date);
  const timePart = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" }).format(date);
  return `${datePart} · ${timePart} Uhr`;
}

function formatSyncTime(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(
    date
  );
}

function SyncBadge() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [triggering, setTriggering] = useState(false);
  // sync-trigger antwortet bei einem fehlgeschlagenen Sync mit HTTP 200 + {success:false, error}
  // (kein HTTP-Fehler, siehe backend/routers/sync_status.py) - ohne explizite Prüfung von
  // result.success würde ein Fehlschlag (z.B. Garmin-Rate-Limit) lautlos verschwinden, weder Zeit
  // noch Daten ändern sich dann, ohne dass sichtbar wird warum.
  const [triggerError, setTriggerError] = useState<string | null>(null);

  function reload() {
    fetchSyncStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }

  useEffect(reload, []);

  // sync-trigger läuft serverseitig blockierend bis der Sync fertig ist (siehe
  // triggerSync-Kommentar in api.ts) - das Icon dreht sich also für die tatsächliche Dauer dieses
  // einen Requests, kein separates Polling nötig.
  async function handleTrigger() {
    setTriggering(true);
    setTriggerError(null);
    try {
      const result = await triggerSync();
      if (!result.success) {
        setTriggerError(result.error ?? "Sync fehlgeschlagen.");
      }
    } catch (e: unknown) {
      setTriggerError(e instanceof Error ? e.message : String(e));
    } finally {
      setTriggering(false);
      reload();
    }
  }

  if (!status) return null;
  const info = SYNC_LABEL[status.status];
  const time = formatSyncTime(status.full_sync_completed_at ?? status.last_check_at);

  return (
    <span className={`sync-badge ${info.className}`}>
      <button
        type="button"
        className={`sync-badge-trigger${triggering ? " spinning" : ""}${triggerError ? " sync-badge-trigger-error" : ""}`}
        onClick={handleTrigger}
        disabled={triggering}
        title={triggerError ?? "Sync jetzt anstoßen"}
      >
        <Icon name="sync" />
      </button>
      {info.text}
      {time && <span className="sync-badge-time"> · {time}</span>}
      {triggerError && <span className="sync-badge-error-text"> · {triggerError}</span>}
    </span>
  );
}

function ThemeToggle({ theme, onThemeChange }: { theme: ThemeChoice; onThemeChange: (t: ThemeChoice) => void }) {
  return (
    <div className="theme-toggle">
      {THEME_OPTIONS.map((option) => (
        <button
          key={option.value}
          className={theme === option.value ? "active" : ""}
          title={option.label}
          onClick={() => onThemeChange(option.value)}
        >
          <Icon name={option.icon} />
        </button>
      ))}
    </div>
  );
}

function TopBar({
  view,
  theme,
  onThemeChange,
}: {
  view: View;
  theme: ThemeChoice;
  onThemeChange: (t: ThemeChoice) => void;
}) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const { title, subtitle } = PAGE_INFO[view];

  return (
    <div className="top-bar">
      <div className="top-bar-left">
        <div className="top-bar-clock">{formatClock(now)}</div>
        <h1 className="top-bar-title">{title}</h1>
        <p className="top-bar-subtitle">{subtitle}</p>
      </div>
      <div className="top-bar-right">
        <SyncBadge />
        <ThemeToggle theme={theme} onThemeChange={onThemeChange} />
      </div>
    </div>
  );
}

export default TopBar;
