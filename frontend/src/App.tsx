import { useState } from "react";
import "./App.css";
import Sidebar, { type View } from "./Sidebar";
import TopBar from "./TopBar";
import TodayView from "./TodayView";
import WeekView from "./WeekView";
import PerformanceView from "./PerformanceView";
import ClubSlotsSettings from "./ClubSlotsSettings";
import PerformanceGoalsSettings from "./PerformanceGoalsSettings";
import { useTheme } from "./theme";
import { useSidebarCollapsed } from "./sidebarCollapsed";

function SettingsView() {
  return (
    <div className="today-view">
      <ClubSlotsSettings />
      <PerformanceGoalsSettings />
    </div>
  );
}

function App() {
  const [view, setView] = useState<View>("today");
  const [theme, setTheme] = useTheme();
  const [sidebarCollapsed, setSidebarCollapsed] = useSidebarCollapsed();

  return (
    <div className="app-shell">
      <Sidebar
        view={view}
        onViewChange={setView}
        collapsed={sidebarCollapsed}
        onCollapsedChange={setSidebarCollapsed}
      />
      <div className="main-content">
        <TopBar view={view} theme={theme} onThemeChange={setTheme} />
        <div className="main-content-body">
          {view === "today" && <TodayView />}
          {view === "week" && <WeekView />}
          {view === "performance" && <PerformanceView />}
          {view === "settings" && <SettingsView />}
        </div>
      </div>
    </div>
  );
}

export default App;
