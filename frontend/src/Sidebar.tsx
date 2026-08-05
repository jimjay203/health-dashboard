import Icon from "./Icon";

export type View = "today" | "week" | "performance" | "settings";

const NAV_ITEMS: { view: View; label: string; icon: string }[] = [
  { view: "today", label: "Heute", icon: "home" },
  { view: "week", label: "Woche", icon: "calendar_month" },
  { view: "performance", label: "Leistung", icon: "trending_up" },
  { view: "settings", label: "Einstellungen", icon: "settings" },
];

function Sidebar({
  view,
  onViewChange,
  collapsed,
  onCollapsedChange,
}: {
  view: View;
  onViewChange: (view: View) => void;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}) {
  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
      <div className="sidebar-brand">
        <div className="sidebar-brand-mark">H</div>
        {!collapsed && <span className="sidebar-brand-name">Health Dashboard</span>}
      </div>
      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.view}
            className={`sidebar-nav-item${view === item.view ? " active" : ""}`}
            title={collapsed ? item.label : undefined}
            onClick={() => onViewChange(item.view)}
          >
            <span className="sidebar-nav-icon">
              <Icon name={item.icon} />
            </span>
            {!collapsed && <span className="sidebar-nav-label">{item.label}</span>}
          </button>
        ))}
      </nav>
      <button
        className="sidebar-collapse-toggle"
        title={collapsed ? "Seitenleiste ausklappen" : "Seitenleiste einklappen"}
        onClick={() => onCollapsedChange(!collapsed)}
      >
        <Icon name={collapsed ? "chevron_right" : "chevron_left"} />
      </button>
    </aside>
  );
}

export default Sidebar;
