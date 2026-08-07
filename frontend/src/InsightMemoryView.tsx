import { useEffect, useState, type FormEvent } from "react";
import {
  fetchInsightMemoryCompressed,
  fetchInsightMemoryRaw,
  addInsightMemoryEntry,
  deleteInsightMemoryEntry,
  deleteAllInsightMemoryVersions,
  type InsightMemoryVersion,
  type InsightRawEntry,
  type InsightSource,
} from "./api";
import Icon from "./Icon";

const SOURCE_LABEL: Record<InsightSource, { text: string; icon: string }> = {
  user: { text: "Du", icon: "person" },
  claude_import: { text: "Claude-Import", icon: "smart_toy" },
  journal: { text: "Journal", icon: "edit_note" },
};

// Aktueller verdichteter Stand + einklappbarer Verlauf älterer Versionen. Rein lesend, keine
// eigene Bearbeitung - der verdichtete Text entsteht ausschließlich über neue Rohtext-Einträge
// unten (siehe insight_memory.py::_compress).
function CompressedTextCard({
  versions,
  onDeleteAll,
}: {
  versions: InsightMemoryVersion[];
  onDeleteAll: () => void;
}) {
  const [showHistory, setShowHistory] = useState(false);
  const latest = versions[0] ?? null;
  const history = versions.slice(1);

  function handleDeleteAll() {
    if (
      window.confirm(
        `Wirklich den kompletten verdichteten Stand löschen (alle ${versions.length} Versionen)? Die Rohtext-Einträge unten bleiben erhalten, der nächste neue Eintrag verdichtet wieder bei "(noch leer)" startend.`
      )
    ) {
      onDeleteAll();
    }
  }

  return (
    <div className="card">
      <h3>
        Aktueller Stand
        {versions.length > 0 && (
          <button
            type="button"
            className="insight-delete-all-button"
            title="Alle Versionen löschen"
            onClick={handleDeleteAll}
          >
            <Icon name="delete" /> Alle Versionen löschen
          </button>
        )}
      </h3>
      {latest ? (
        <>
          <p className="week-rationale">
            Version {latest.version} · zuletzt aktualisiert {latest.updated_at}
          </p>
          <div className="insight-compressed-box">{latest.compressed_text || "(leer)"}</div>
          {history.length > 0 && (
            <>
              <button type="button" className="insight-history-toggle" onClick={() => setShowHistory((v) => !v)}>
                <Icon name={showHistory ? "expand_less" : "expand_more"} />
                Verlauf ({history.length} {history.length === 1 ? "Version" : "Versionen"})
              </button>
              {showHistory && (
                <div className="insight-history-list">
                  {history.map((v) => (
                    <div key={v.version} className="insight-history-entry">
                      <div className="insight-history-version">
                        Version {v.version} · {v.updated_at}
                      </div>
                      <div className="insight-history-text">{v.compressed_text || "(leer)"}</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      ) : (
        <p className="week-rationale">Noch kein verdichteter Text vorhanden - lege unten den ersten Eintrag an.</p>
      )}
    </div>
  );
}

// Verdichtung läuft synchron/blockierend gegen Gemini (siehe backend/routers/insight_memory.py) -
// das Formular bleibt bis zur Antwort deaktiviert und zeigt einen drehenden Status-Hinweis, statt
// stillschweigend zu warten.
function NewEntryCard({ onAdded }: { onAdded: () => void }) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await addInsightMemoryEntry(text.trim());
      setText("");
      onAdded();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card">
      <h3>Neuen Eintrag hinzufügen</h3>
      <p className="week-rationale">
        Wird sofort verdichtet (nicht gesammelt): präzisiert/korrigiert der Eintrag Bestehendes, wird die
        alte Stelle ersetzt statt dupliziert; ist er redundant, wird er ignoriert.
      </p>
      {error && <p className="error-banner">Fehler: {error}</p>}
      <form className="insight-entry-form" onSubmit={handleSubmit}>
        <textarea
          placeholder='z. B. "Ich vertrage Hitze über 25°C schlecht, sollte im Sommer früh morgens laufen."'
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={submitting}
          required
        />
        <button type="submit" disabled={submitting || !text.trim()}>
          Merken
        </button>
      </form>
      {submitting && (
        <p className="insight-status">
          <Icon name="autorenew" className="insight-status-icon" /> Gemini verdichtet den neuen Eintrag…
        </p>
      )}
    </div>
  );
}

function RawEntriesCard({ entries, onDelete }: { entries: InsightRawEntry[]; onDelete: (id: number) => void }) {
  return (
    <div className="card">
      <h3>Bisherige Rohtext-Einträge</h3>
      <p className="week-rationale">
        Archiv, wird nie von der KI verändert. Löschen entfernt nur den Rohtext, keine erneute Verdichtung.
      </p>
      {entries.length === 0 ? (
        <p className="week-rationale">Noch keine Einträge.</p>
      ) : (
        <div className="insight-raw-list">
          {entries.map((entry) => {
            const source = SOURCE_LABEL[entry.source];
            return (
              <div key={entry.id} className="insight-raw-entry">
                <div className="insight-raw-entry-body">
                  <div className="insight-raw-entry-meta">
                    {entry.created_at}
                    <span className="insight-source-badge">
                      <Icon name={source.icon} /> {source.text}
                    </span>
                  </div>
                  <div className="insight-raw-entry-text">{entry.raw_text}</div>
                </div>
                <button
                  type="button"
                  className="insight-raw-entry-delete"
                  title="Eintrag löschen"
                  onClick={() => onDelete(entry.id)}
                >
                  <Icon name="delete" />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function InsightMemoryView() {
  const [versions, setVersions] = useState<InsightMemoryVersion[]>([]);
  const [entries, setEntries] = useState<InsightRawEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  function reload() {
    fetchInsightMemoryCompressed()
      .then(setVersions)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    fetchInsightMemoryRaw()
      .then(setEntries)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(reload, []);

  async function handleDelete(id: number) {
    try {
      await deleteInsightMemoryEntry(id);
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDeleteAll() {
    try {
      await deleteAllInsightMemoryVersions();
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="today-view">
      {error && <p className="error-banner">Fehler: {error}</p>}
      <CompressedTextCard versions={versions} onDeleteAll={handleDeleteAll} />
      <NewEntryCard onAdded={reload} />
      <RawEntriesCard entries={entries} onDelete={handleDelete} />
    </div>
  );
}

export default InsightMemoryView;
