import { useState } from "react";
import "./App.css";
import Sidebar, { type View } from "./Sidebar";
import TopBar from "./TopBar";
import TodayView from "./TodayView";
import ClubSlotsSettings from "./ClubSlotsSettings";
import { useTheme } from "./theme";

function App() {
  const [view, setView] = useState<View>("today");
  const [theme, setTheme] = useTheme();

  return (
    <div className="app-shell">
      <Sidebar view={view} onViewChange={setView} />
      <div className="main-content">
        <TopBar view={view} theme={theme} onThemeChange={setTheme} />
        <div className="main-content-body">
          {view === "today" ? <TodayView /> : <ClubSlotsSettings />}
        </div>
      </div>
    </div>
  );
}

export default App;
