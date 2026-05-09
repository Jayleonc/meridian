import { NavLink, Outlet } from "react-router-dom";
import { auth } from "../api/client";
import { useApp } from "../context/AppContext";
import { useInvestigation, getStepIcon } from "../context/InvestigationContext";
import CommandPalette from "./CommandPalette";

const NAV = [
  { to: "/", icon: "\u25A3", label: "概览" },
  { to: "/chat", icon: "\u25CC", label: "Agent" },
  { group: "观测" },
  { to: "/atlas", icon: "\u2B22", label: "Atlas", svc: "atlas" as const },
  { to: "/probe", icon: "\u25CE", label: "Probe", svc: "probe" as const },
  { to: "/lens", icon: "\u25C8", label: "Lens", svc: "lens" as const },
  { group: "平台" },
  { to: "/nexus", icon: "\u25A6", label: "Nexus" },
];

export default function Layout() {
  const { health, demoMode, sidebarOpen, toggleSidebar, toasts, dismissToast } = useApp();
  const inv = useInvestigation();
  const visibleNav = NAV.filter((item) => {
    if (!demoMode) return true;
    if ("group" in item) return false;
    return item.to === "/" || item.to === "/chat";
  });

  async function handleLogout() {
    try {
      await auth.logout();
    } finally {
      window.location.assign("/login");
    }
  }

  return (
    <>
      <div className={`app-shell ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="grid-bg" />

        {/* ── Sidebar ── */}
        <aside className="sidebar">
          <div className="sidebar-brand" onClick={toggleSidebar}>
            <div className="brand-mark">M</div>
            <span className="brand-text">MERIDIAN</span>
          </div>

          <nav className="sidebar-nav">
            {visibleNav.map((item, i) =>
              "group" in item ? (
                <div key={i} className="nav-group-label">{item.group}</div>
              ) : (
                <NavLink
                  key={item.to}
                  to={item.to!}
                  end={item.to === "/"}
                  className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                >
                  <span className="nav-icon">{item.icon}</span>
                  <span className="nav-label">{item.label}</span>
                  {item.svc && <span className={`nav-health ${health[item.svc]}`} />}
                </NavLink>
              )
            )}
          </nav>

          <div className="sidebar-bottom">
            <button className="sidebar-logout" type="button" onClick={handleLogout}>
              <span className="nav-icon">{"\u21AA"}</span>
              <span className="nav-label">退出</span>
            </button>
            <div className="sidebar-kbd">{"\u2318"}K 命令面板</div>
          </div>
        </aside>

        {/* ── Main content ── */}
        <main className="main-area">
          <Outlet />
        </main>

        {/* ── Investigation bar ── */}
        {inv.steps.length > 0 && (
          <div className="investigation-bar">
            {inv.steps.map((step, i) => (
              <span key={i} style={{ display: "contents" }}>
                {i > 0 && <span className="inv-arrow">{"\u2192"}</span>}
                <span className="inv-step" onClick={() => inv.goTo(i)}>
                  <span className="inv-icon">{getStepIcon(step.type)}</span>
                  <span className="inv-label">{step.label}</span>
                </span>
              </span>
            ))}
            <span className="inv-clear" onClick={inv.clear}>{"\u2715"} 清除</span>
          </div>
        )}
      </div>

      {/* ── Toasts ── */}
      <div className="toast-container">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`toast toast-${t.type}`}
            onClick={() => dismissToast(t.id)}
          >
            {t.message}
          </div>
        ))}
      </div>

      <CommandPalette />
    </>
  );
}
