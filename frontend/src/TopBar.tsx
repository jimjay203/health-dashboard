import { useEffect, useState } from "react";
import {
  fetchSyncStatus,
  triggerSync,
  fetchSyncActivity,
  regenerateAllAiTexts,
  type SyncStatus,
  type SyncStatusValue,
  type SyncActivity,
} from "./api";
import type { View } from "./Sidebar";
import type { ThemeChoice } from "./theme";
import Icon from "./Icon";

const PAGE_INFO: Record<View, { title: string; subtitle: string }> = {
  today: { title: "Heute", subtitle: "Dein Trainings-Status auf einen Blick." },
  week: { title: "Woche", subtitle: "Rolling-Horizon-Wochenplan und Trainingsphase." },
  performance: { title: "Leistung", subtitle: "Belastungssteuerung, Trainingsdiagnostik und Schwellenwerte." },
  sleep: { title: "Schlaf", subtitle: "Schlafqualität, Regelmäßigkeit und Einflussfaktoren auf einen Blick." },
  body: { title: "Körper", subtitle: "Körperzusammensetzung, What-if-Simulator und Verletzungsprotokoll." },
  insights: { title: "Erkenntnisse", subtitle: "Erkenntnis-Gedächtnis: Zusatzinfos in deinen eigenen Worten." },
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

// Kein Live-Fortschritt für einen einzelnen Sync nötig - dieselbe orange Farbe wie der bestehende
// "checking"-Zustand deckt "irgendein Sync läuft gerade" ab (Garmin oder Withings, automatisch
// oder manuell, siehe SYNC_ACTIVITY_POLL_MS unten).
const SYNCING_CLASS_NAME = "sync-badge-checking";
const SYNCING_TEXT = "Sync läuft…";
// Live-Feedback für Hintergrund-Syncs (auto_sync.py/withings_auto_sync.py) - die laufen ohne
// eigenen Request vom Frontend aus, deshalb reicht das bestehende "während des manuellen Trigger-
// Requests spinnen"-Muster allein nicht. Gleicher Poll-Takt aktualisiert nebenbei auch den
// Tages-Status (reload()), damit ein im Hintergrund abgeschlossener Sync zeitnah sichtbar wird.
const SYNC_ACTIVITY_POLL_MS = 5000;

function formatSyncTime(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(
    date
  );
}

function SyncBadge() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [activity, setActivity] = useState<SyncActivity | null>(null);
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

  useEffect(() => {
    reload();
    fetchSyncActivity()
      .then(setActivity)
      .catch(() => setActivity(null));
    const interval = setInterval(() => {
      reload();
      fetchSyncActivity()
        .then(setActivity)
        .catch(() => setActivity(null));
    }, SYNC_ACTIVITY_POLL_MS);
    return () => clearInterval(interval);
  }, []);

  // sync-trigger läuft serverseitig blockierend bis der Sync fertig ist (siehe
  // triggerSync-Kommentar in api.ts) - das Icon dreht sich also sofort schon für die Dauer dieses
  // einen Requests, statt auf das nächste Poll-Intervall zu warten.
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
  const isSyncing = triggering || Boolean(activity?.garmin_syncing) || Boolean(activity?.withings_syncing);
  const info = SYNC_LABEL[status.status];
  const time = formatSyncTime(status.full_sync_completed_at ?? status.last_check_at);

  return (
    <span className={`sync-badge ${isSyncing ? SYNCING_CLASS_NAME : info.className}`}>
      <button
        type="button"
        className={`sync-badge-trigger${isSyncing ? " spinning" : ""}${triggerError ? " sync-badge-trigger-error" : ""}`}
        onClick={handleTrigger}
        disabled={triggering}
        title={triggerError ?? "Sync jetzt anstoßen"}
      >
        <Icon name="sync" />
      </button>
      {isSyncing ? SYNCING_TEXT : info.text}
      {time && <span className="sync-badge-time"> · {time}</span>}
      {triggerError && <span className="sync-badge-error-text"> · {triggerError}</span>}
    </span>
  );
}

// KI-Texte werden seit dem 2026-08-08 nicht mehr automatisch beim Seitenaufruf generiert (Nutzer-
// Vorgabe) - diese Pille bündelt die Regenerate-Funktionen aller Insight-/Empfehlungs-Karten zu
// einem Klick (Tagesempfehlung, Sleep-Trend/-Korrelationen, Körper-Trend, Leistungsziele-
// Einschätzung - siehe backend/routers/ai_texts.py). Bewusst OHNE Wochenplan, siehe dortiger
// Docstring. Kein Live-Polling nötig wie bei SyncBadge (kein Hintergrund-Task dahinter, läuft nur
// während des eigenen Requests) - gleiche Farb-/Spin-Klassen wie SyncBadge wiederverwendet.
function AiTextsBadge() {
  const [running, setRunning] = useState(false);
  const [hasRun, setHasRun] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setRunning(true);
    setError(null);
    try {
      const result = await regenerateAllAiTexts();
      const failed = result.results.filter((r) => !r.success);
      setError(failed.length > 0 ? failed.map((f) => `${f.label}: ${f.error}`).join(" · ") : null);
      setHasRun(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const className = running ? "sync-badge-checking" : error ? "sync-badge-warn" : hasRun ? "sync-badge-ok" : "sync-badge-idle";
  const label = running ? "Generiert…" : error ? "Fehler" : hasRun ? "KI-Texte aktuell" : "KI-Texte";

  return (
    <span className={`sync-badge ${className}`}>
      <button
        type="button"
        className={`sync-badge-trigger${running ? " spinning" : ""}`}
        onClick={handleClick}
        disabled={running}
        title="Alle KI-Texte neu generieren (Tagesempfehlung, Sleep/Körper/Leistung-Einschätzungen)"
      >
        <Icon name="auto_awesome" />
      </button>
      {label}
      {error && <span className="sync-badge-error-text"> · {error}</span>}
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
  onMenuClick,
}: {
  view: View;
  theme: ThemeChoice;
  onThemeChange: (t: ThemeChoice) => void;
  onMenuClick: () => void;
}) {
  const { title, subtitle } = PAGE_INFO[view];

  return (
    <div className="top-bar">
      <div className="top-bar-left">
        {/* Nur auf schmalen Bildschirmen sichtbar (siehe App.css) - öffnet die Sidebar als
            Drawer-Overlay, da dort für eine permanente Spalte kein Platz ist. */}
        <button className="top-bar-menu-button" title="Menü öffnen" onClick={onMenuClick}>
          <Icon name="menu" />
        </button>
        <div className="top-bar-heading">
          <h1 className="top-bar-title">{title}</h1>
          <p className="top-bar-subtitle">{subtitle}</p>
        </div>
      </div>
      <div className="top-bar-right">
        <SyncBadge />
        <AiTextsBadge />
        <ThemeToggle theme={theme} onThemeChange={onThemeChange} />
      </div>
    </div>
  );
}

export default TopBar;
