import { useEffect, useRef, useState } from "react";
import {
  todayIso,
  syncGarminDay,
  syncWithingsDay,
  syncWithingsFullHistory,
  fetchWithingsAutoSyncStatus,
  startBackfill,
  fetchBackfillStatus,
  fetchActivitiesSummary,
  fetchActivities,
  syncActivitiesList,
  startActivityDetailsSync,
  fetchActivityDetailsStatus,
  type BackfillStatus,
  type ActivitiesSummary,
  type ActivityRow,
  type ActivityDetailsStatus,
  type WithingsAutoSyncStatus,
} from "./api";

const POLL_INTERVAL_MS = 2000;
// Kein schnelles Polling nötig (kein laufender Fortschritt wie bei Backfill/Aktivitäten-Details) -
// der Hintergrund-Task selbst läuft stündlich, ein Minuten-Takt reicht, um den Status aktuell zu halten.
const AUTO_SYNC_STATUS_POLL_MS = 60_000;

function formatDateTime(iso: string | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium" });
}

function formatUnixSeconds(sec: number | null): string {
  if (sec == null) return "–";
  return new Date(sec * 1000).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium" });
}

// Status des stündlichen Hintergrund-Tasks (siehe withings_auto_sync.py) - primärer Zweck ist,
// den OAuth2-Token aktiv zu halten (Root-Cause des Ausfalls vom 2026-08-07: ein über 52h nie
// genutzter Refresh-Token wurde beim fälligen Refresh ungültig), synct nebenbei den heutigen Tag.
function WithingsAutoSyncStatusSection() {
  const [status, setStatus] = useState<WithingsAutoSyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  function reload() {
    fetchWithingsAutoSyncStatus()
      .then((s) => {
        setStatus(s);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(() => {
    reload();
    const interval = setInterval(reload, AUTO_SYNC_STATUS_POLL_MS);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="data-sync-section">
      <h4>Withings Auto-Sync</h4>
      <p className="week-rationale">
        Läuft seit der Automatisierung stündlich im Hintergrund, hält den OAuth2-Token aktiv und
        synct nebenbei den heutigen Tag - verhindert, dass der Token wie zuvor durch Inaktivität abläuft.
      </p>
      {error && <p className="error-banner">{error}</p>}
      {status && (
        <>
          <p className="week-rationale">
            Letzter Lauf: {formatDateTime(status.last_run_at)}
            {status.last_success_at && ` · letzter Erfolg: ${formatDateTime(status.last_success_at)}`}
          </p>
          <p className="week-rationale">Token gültig bis: {formatUnixSeconds(status.token_expires_at)}</p>
          {status.last_error ? (
            <p className="error-banner">{status.last_error}</p>
          ) : status.last_success_at ? (
            <p className="data-sync-success">Aktiv, keine Fehler.</p>
          ) : null}
        </>
      )}
    </div>
  );
}

// Einzel-Tages-Sync für ein beliebiges Datum (ergänzt die "Sync jetzt"-Pille in der TopBar, die
// nur "heute" synct) - Garmin und Withings, gleiches Formular-Muster (Datum + Button).
function DaySyncSection({
  title,
  caption,
  onSync,
}: {
  title: string;
  caption: string;
  onSync: (date: string) => Promise<{ success: boolean; error: string | null; measurement_count?: number | null }>;
}) {
  const [date, setDate] = useState(todayIso());
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<{ text: string; isError: boolean } | null>(null);

  async function handleClick() {
    setSyncing(true);
    setMessage(null);
    try {
      const result = await onSync(date);
      if (result.success) {
        const detail = result.measurement_count != null ? ` (${result.measurement_count} Messung(en))` : "";
        setMessage({ text: `Erfolgreich synchronisiert${detail}.`, isError: false });
      } else {
        setMessage({ text: result.error ?? "Sync fehlgeschlagen.", isError: true });
      }
    } catch (e: unknown) {
      setMessage({ text: e instanceof Error ? e.message : String(e), isError: true });
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="data-sync-section">
      <h4>{title}</h4>
      <p className="week-rationale">{caption}</p>
      <div className="data-sync-form-row">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <button type="button" onClick={handleClick} disabled={syncing}>
          {syncing ? "Synchronisiert…" : "Jetzt synchronisieren"}
        </button>
      </div>
      {message && <p className={message.isError ? "error-banner" : "data-sync-success"}>{message.text}</p>}
    </div>
  );
}

// Backfill läuft als Hintergrund-Task (siehe backend/routers/data_sync.py) - Status wird gepollt,
// solange "running" true ist, damit die Anfrage nicht in einem Request-Timeout läuft und ein
// Fortschritt sichtbar bleibt (analog zum bestehenden Sync-Status-Polling in TopBar.tsx).
function BackfillSection() {
  const [start, setStart] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return d.toISOString().slice(0, 10);
  });
  const [end, setEnd] = useState(todayIso());
  const [status, setStatus] = useState<BackfillStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function poll() {
    fetchBackfillStatus()
      .then((s) => {
        setStatus(s);
        if (!s.running && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      })
      .catch(() => undefined);
  }

  useEffect(() => {
    // Läuft der Backfill server-seitig noch (z.B. nach Verlassen und Zurückkehren zur
    // Einstellungen-Seite - der Task selbst läuft unabhängig vom Frontend weiter), Polling direkt
    // wieder aufnehmen statt nur einen einmaligen Schnappschuss zu zeigen, der dann einfriert.
    fetchBackfillStatus()
      .then((s) => {
        setStatus(s);
        if (s.running) pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
      })
      .catch(() => undefined);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleStart() {
    setError(null);
    if (start > end) {
      setError("Das Startdatum muss vor oder gleich dem Enddatum liegen.");
      return;
    }
    try {
      await startBackfill(start, end);
      poll();
      pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const running = status?.running ?? false;
  const pct = status && status.total > 0 ? ((status.success_count + status.error_count) / status.total) * 100 : 0;

  return (
    <div className="data-sync-section">
      <h4>Backfill über Zeitraum</h4>
      <p className="week-rationale">Lädt Daten für jeden Tag zwischen Start- und Enddatum nach.</p>
      <div className="data-sync-form-row">
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} disabled={running} />
        <span>bis</span>
        <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} disabled={running} />
        <button type="button" onClick={handleStart} disabled={running}>
          {running ? "Läuft…" : "Backfill starten"}
        </button>
      </div>
      {error && <p className="error-banner">{error}</p>}
      {status && (status.running || status.total > 0) && (
        <div className="data-sync-progress">
          <div className="data-sync-progress-track">
            <div className="data-sync-progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <p className="week-rationale">
            {status.current_date && `${status.current_date} · `}
            {status.success_count} erfolgreich, {status.error_count} Fehler von {status.total} Tagen
            {status.stopped_early && " · wegen Rate-Limit abgebrochen"}
          </p>
          {status.last_error && <p className="error-banner">{status.last_error}</p>}
        </div>
      )}
    </div>
  );
}

const ACTIVITY_TYPE_LABEL: Record<string, string> = {
  running: "Laufen",
  cycling: "Rad",
  road_biking: "Rad",
  lap_swimming: "Schwimmen",
};

function ActivitiesSection() {
  const [summary, setSummary] = useState<ActivitiesSummary | null>(null);
  const [activities, setActivities] = useState<ActivityRow[]>([]);
  const [showTable, setShowTable] = useState(false);
  const [listLimit, setListLimit] = useState(20);
  const [listSyncing, setListSyncing] = useState(false);
  const [listMessage, setListMessage] = useState<string | null>(null);
  const [detailLimit, setDetailLimit] = useState(5);
  const [detailStatus, setDetailStatus] = useState<ActivityDetailsStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function reloadSummary() {
    fetchActivitiesSummary()
      .then(setSummary)
      .catch(() => undefined);
  }

  useEffect(() => {
    reloadSummary();
    // Läuft der Detail-Sync server-seitig noch (siehe gleiches Prinzip bei BackfillSection oben),
    // Polling direkt wieder aufnehmen statt eines einfrierenden Schnappschusses.
    fetchActivityDetailsStatus()
      .then((s) => {
        setDetailStatus(s);
        if (s.running) pollRef.current = setInterval(pollDetails, POLL_INTERVAL_MS);
      })
      .catch(() => undefined);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleLoadList() {
    setListSyncing(true);
    setListMessage(null);
    try {
      const result = await syncActivitiesList(listLimit);
      if (result.success) {
        setListMessage(`${result.count} Aktivitäten gespeichert/aktualisiert.`);
        reloadSummary();
        if (showTable) loadTable();
      } else {
        setListMessage(result.error ?? "Fehler beim Laden der Aktivitätsliste.");
      }
    } catch (e: unknown) {
      setListMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setListSyncing(false);
    }
  }

  function pollDetails() {
    fetchActivityDetailsStatus()
      .then((s) => {
        setDetailStatus(s);
        if (!s.running && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          reloadSummary();
          if (showTable) loadTable();
        }
      })
      .catch(() => undefined);
  }

  async function handleLoadDetails() {
    try {
      await startActivityDetailsSync(detailLimit);
      pollDetails();
      pollRef.current = setInterval(pollDetails, POLL_INTERVAL_MS);
    } catch (e: unknown) {
      setDetailStatus({
        running: false, current_index: 0, total: 0, current_activity_name: null,
        synced_count: 0, error_count: 0, last_error: e instanceof Error ? e.message : String(e),
      });
    }
  }

  function loadTable() {
    fetchActivities(50)
      .then(setActivities)
      .catch(() => undefined);
  }

  function toggleTable() {
    if (!showTable) loadTable();
    setShowTable(!showTable);
  }

  const detailsRunning = detailStatus?.running ?? false;

  return (
    <div className="data-sync-section">
      <h4>Aktivitäten (Läufe, Rad, Schwimmen)</h4>
      <p className="week-rationale">
        Neue Aktivitäten seit gestern werden automatisch mit im täglichen Auto-Sync erfasst (Liste + wenige offene
        Detail-Zeitreihen). Die Formulare hier sind für einen großen, seltenen Nachholbedarf - eine volle Historie
        kann mehrere hundert Aktivitäten und pro Aktivität mehrere hundert Detail-Zeilen umfassen.
      </p>
      {summary && (
        <p className="week-rationale">
          {summary.total_activities} Aktivitäten gespeichert · {summary.pending_details} davon noch ohne
          Detail-Zeitreihe
        </p>
      )}

      <div className="data-sync-activities-row">
        <div className="data-sync-section">
          <strong>1. Aktivitätsliste aktualisieren</strong>
          <div className="data-sync-form-row">
            <input
              type="number"
              min={1}
              max={200}
              value={listLimit}
              onChange={(e) => setListLimit(Number(e.target.value))}
            />
            <button type="button" onClick={handleLoadList} disabled={listSyncing}>
              {listSyncing ? "Lädt…" : "Aktivitätsliste laden"}
            </button>
          </div>
          {listMessage && <p className="week-rationale">{listMessage}</p>}
        </div>

        <div className="data-sync-section">
          <strong>2. Detail-Zeitreihen nachladen</strong>
          <div className="data-sync-form-row">
            <input
              type="number"
              min={1}
              max={50}
              value={detailLimit}
              onChange={(e) => setDetailLimit(Number(e.target.value))}
              disabled={detailsRunning}
            />
            <button type="button" onClick={handleLoadDetails} disabled={detailsRunning}>
              {detailsRunning ? "Lädt…" : "Detaildaten laden"}
            </button>
          </div>
          {detailStatus && (detailStatus.running || detailStatus.total > 0) && (
            <p className="week-rationale">
              {detailStatus.current_activity_name && `${detailStatus.current_activity_name} · `}
              {detailStatus.synced_count} synchronisiert, {detailStatus.error_count} Fehler
              {detailStatus.total > 0 && ` von ${detailStatus.total}`}
            </p>
          )}
          {detailStatus?.last_error && <p className="error-banner">{detailStatus.last_error}</p>}
        </div>
      </div>

      {summary && summary.total_activities > 0 && (
        <>
          <button type="button" className="data-sync-toggle-table" onClick={toggleTable}>
            {showTable ? "Aktivitäten ausblenden" : "Gespeicherte Aktivitäten anzeigen"}
          </button>
          {showTable && (
            <table className="club-slots-table">
              <thead>
                <tr>
                  <th>Datum</th>
                  <th>Sportart</th>
                  <th>Name</th>
                  <th>km</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {activities.map((a) => (
                  <tr key={a.activity_id}>
                    <td>{a.start_time_local?.slice(0, 16).replace("T", " ") ?? "–"}</td>
                    <td>{a.activity_type ? ACTIVITY_TYPE_LABEL[a.activity_type] ?? a.activity_type : "–"}</td>
                    <td>{a.activity_name ?? "–"}</td>
                    <td>{a.distance_km ?? "–"}</td>
                    <td>{a.has_details_synced ? "✓" : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

// Einmaliger Voll-Import der kompletten Withings-Historie (siehe
// withings_service.py::fetch_full_withings_history) - kein Datumsfeld wie bei DaySyncSection oben,
// da Withings ohne startdate/enddate paginiert die gesamte Historie liefert (bewusst blockierend,
// kein Hintergrund-Task/Polling wie beim Garmin-Backfill nötig - siehe backend/routers/data_sync.py).
function WithingsFullHistorySection() {
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<{ text: string; isError: boolean } | null>(null);

  async function handleClick() {
    setSyncing(true);
    setMessage(null);
    try {
      const result = await syncWithingsFullHistory();
      if (result.success) {
        const detail = result.measurement_count != null ? ` (${result.measurement_count} Messung(en))` : "";
        setMessage({ text: `Erfolgreich synchronisiert${detail}.`, isError: false });
      } else {
        setMessage({ text: result.error ?? "Sync fehlgeschlagen.", isError: true });
      }
    } catch (e: unknown) {
      setMessage({ text: e instanceof Error ? e.message : String(e), isError: true });
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="data-sync-section">
      <h4>Withings Voll-Historie</h4>
      <p className="week-rationale">
        Holt einmalig die komplette bei Withings vorliegende Mess-Historie statt nur eines
        Tagesfensters wie beim Sync oben - sinnvoll direkt nach der ersten Autorisierung, um die
        volle Historie zu bekommen.
      </p>
      <div className="data-sync-form-row">
        <button type="button" onClick={handleClick} disabled={syncing}>
          {syncing ? "Synchronisiert…" : "Komplette Historie laden"}
        </button>
      </div>
      {message && <p className={message.isError ? "error-banner" : "data-sync-success"}>{message.text}</p>}
    </div>
  );
}

// Bewusst KEINE Portierung der Streamlit-API-Exploration (Tier-1/2-Testabruf) - das ist ein
// Debug-/Explorations-Werkzeug, keine Sync-Funktion, und bleibt vorerst nur in Streamlit verfügbar.
function DataSyncSettings() {
  return (
    <div className="card data-sync-card">
      <h3>Daten-Synchronisation</h3>
      <DaySyncSection
        title="Garmin Connect Sync"
        caption="Synchronisiert alle Garmin-Kern-/Erweiterungsdaten für ein beliebiges Datum (ergänzt die automatische/tägliche Sync-Pille oben, die nur den heutigen Tag abdeckt)."
        onSync={syncGarminDay}
      />
      <WithingsAutoSyncStatusSection />
      <DaySyncSection
        title="Withings Sync"
        caption='Holt Waagen-Daten direkt bei Withings statt über Garmins lückenhafte Weiterleitung. Erstmalige Nutzung erfordert eine einmalige Autorisierung über "python3 -m examples.withings_authorize".'
        onSync={syncWithingsDay}
      />
      <WithingsFullHistorySection />
      <BackfillSection />
      <ActivitiesSection />
    </div>
  );
}

export default DataSyncSettings;
