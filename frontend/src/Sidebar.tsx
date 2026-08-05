export type View = "today" | "settings";

const NAV_ITEMS: { view: View; label: string; icon: string }[] = [
  { view: "today", label: "Heute", icon: "🏠" },
  { view: "settings", label: "Einstellungen", icon: "⚙️" },
];

function Sidebar({ view, onViewChange }: { view: View; onViewChange: (view: View) => void }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-mark">H</div>
        <span className="sidebar-brand-name">Health Dashboard</span>
      </div>
      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.view}
            className={`sidebar-nav-item${view === item.view ? " active" : ""}`}
            onClick={() => onViewChange(item.view)}
          >
            <span className="sidebar-nav-icon">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>
    </aside>
  );
}

export default Sidebar;
