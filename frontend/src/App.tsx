import { useEffect, useState } from "react";

interface DailySummary {
  date: string;
  hrv_vs_7d_avg_pct: number | null;
  hrv_vs_28d_avg_pct: number | null;
  sleep_vs_7d_avg_pct: number | null;
  resting_hr_vs_7d_avg_pct: number | null;
  training_load_7d: number | null;
  training_load_28d: number | null;
  acute_chronic_ratio: number | null;
  training_monotony: number | null;
  training_strain: number | null;
  sleep_debt_cumulative: number | null;
  overreach_flag: number | null;
  days_until_next_race: number | null;
  weight_vs_avg_pct: number | null;
  data_quality_flag: string | null;
  notable_events_text: string | null;
  ctl: number | null;
  atl: number | null;
  tsb: number | null;
  journal_rpe: number | null;
  journal_soreness: number | null;
  journal_energy_level: number | null;
}

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: DailySummary };

function todayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function App() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    const date = todayIso();
    fetch(`/api/daily-summary/${date}`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail ?? `HTTP ${res.status}`);
        }
        return (await res.json()) as DailySummary;
      })
      .then((data) => setState({ status: "success", data }))
      .catch((err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : String(err) })
      );
  }, []);

  return (
    <div style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>Health Dashboard — Schritt 1 (Grundgerüst)</h1>
      <p>Backend-Grundgerüst: FastAPI + React, kein Styling/Design in diesem Schritt.</p>

      {state.status === "loading" && <p>Lade daily_summary für heute...</p>}

      {state.status === "error" && (
        <p style={{ color: "crimson" }}>Fehler: {state.message}</p>
      )}

      {state.status === "success" && (
        <div>
          <h2>daily_summary ({state.data.date})</h2>
          <ul>
            {Object.entries(state.data).map(([key, value]) => (
              <li key={key}>
                <strong>{key}:</strong> {value === null ? "–" : String(value)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default App;
