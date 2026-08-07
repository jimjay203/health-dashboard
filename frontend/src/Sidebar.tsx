import Icon from "./Icon";

export type View = "today" | "week" | "performance" | "sleep" | "insights" | "settings";

const NAV_ITEMS: { view: View; label: string; icon: string }[] = [
  { view: "today", label: "Heute", icon: "home" },
  { view: "week", label: "Woche", icon: "calendar_month" },
  { view: "performance", label: "Leistung", icon: "trending_up" },
  { view: "sleep", label: "Schlaf", icon: "bedtime" },
  { view: "insights", label: "Erkenntnisse", icon: "psychology" },
  { view: "settings", label: "Einstellungen", icon: "settings" },
];

// Auf schmalen Bildschirmen (≤768px, siehe App.css) ist die Sidebar kein permanenter Spaltenteil
// mehr, sondern ein Drawer-Overlay - per Hamburger-Button in der TopBar geöffnet (mobileOpen-Prop,
// Zustand lebt in App.tsx, damit TopBar und Sidebar denselben Zustand teilen können), per Backdrop-
// Klick/Escape/Nav-Auswahl wieder geschlossen (onMobileClose). Der bestehende Einklapp-Zustand
// (collapsed/onCollapsedChange, Desktop-Icon-only) bleibt komplett unabhängig davon bestehen - die
// mobile CSS-Regel ignoriert `collapsed` und zeigt im Drawer immer volle Labels.
function Sidebar({
  view,
  onViewChange,
  collapsed,
  onCollapsedChange,
  mobileOpen,
  onMobileClose,
}: {
  view: View;
  onViewChange: (view: View) => void;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}) {
  function handleNavClick(next: View) {
    onViewChange(next);
    onMobileClose();
  }

  return (
    <>
      {mobileOpen && <div className="sidebar-backdrop" onClick={onMobileClose} />}
      <aside className={`sidebar${collapsed ? " collapsed" : ""}${mobileOpen ? " mobile-open" : ""}`}>
        <div className="sidebar-brand">
          <div className="sidebar-brand-mark">H</div>
          {/* Immer gerendert (nicht `{!collapsed && ...}`) - im mobilen Drawer soll das Label
              unabhängig vom (rein Desktop-relevanten) collapsed-Zustand sichtbar sein, das
              Sichtbar-/Verbergen selbst übernimmt CSS (siehe App.css). */}
          <span className="sidebar-brand-name">Health Dashboard</span>
          <button className="sidebar-mobile-close" title="Menü schließen" onClick={onMobileClose}>
            <Icon name="close" />
          </button>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.view}
              className={`sidebar-nav-item${view === item.view ? " active" : ""}`}
              title={collapsed ? item.label : undefined}
              onClick={() => handleNavClick(item.view)}
            >
              <span className="sidebar-nav-icon">
                <Icon name={item.icon} />
              </span>
              <span className="sidebar-nav-label">{item.label}</span>
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
    </>
  );
}

export default Sidebar;
