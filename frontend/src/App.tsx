import { useState } from "react";
import "./App.css";
import Sidebar, { type View } from "./Sidebar";
import TopBar from "./TopBar";
import TodayView from "./TodayView";
import WeekView from "./WeekView";
import PerformanceView from "./PerformanceView";
import InsightMemoryView from "./InsightMemoryView";
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
  // Nur auf schmalen Bildschirmen relevant (siehe App.css Responsive-Block) - dort ist die
  // Sidebar ein per Hamburger-Button geöffneter Drawer statt einer permanenten Spalte. Auf dem
  // Desktop bleibt der Button unsichtbar (CSS), der State also dauerhaft false.
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="app-shell">
      <Sidebar
        view={view}
        onViewChange={setView}
        collapsed={sidebarCollapsed}
        onCollapsedChange={setSidebarCollapsed}
        mobileOpen={mobileNavOpen}
        onMobileClose={() => setMobileNavOpen(false)}
      />
      <div className="main-content">
        <TopBar view={view} theme={theme} onThemeChange={setTheme} onMenuClick={() => setMobileNavOpen(true)} />
        <div className="main-content-body">
          {view === "today" && <TodayView />}
          {view === "week" && <WeekView />}
          {view === "performance" && <PerformanceView />}
          {view === "insights" && <InsightMemoryView />}
          {view === "settings" && <SettingsView />}
        </div>
      </div>
    </div>
  );
}

export default App;
