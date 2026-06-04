import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import { Loading } from "./ui";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Queue from "./pages/Queue";
import BuildDetail from "./pages/BuildDetail";
import TicketDetail from "./pages/TicketDetail";
import Fleet from "./pages/Fleet";
import Materials from "./pages/Materials";
import Submit from "./pages/Submit";

const OP_NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/queue", label: "Queue & Schedule" },
  { to: "/fleet", label: "Fleet" },
  { to: "/materials", label: "Material shelf" },
];

function Shell() {
  const { user, logout } = useAuth();
  const isOp = user?.role === "operator";
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">KILN</div>
        <div className="brand-sub">print-lab operations</div>
        <nav className="nav">
          {isOp
            ? OP_NAV.map((n) => (
                <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
                  {n.label}
                </NavLink>
              ))
            : (
              <NavLink to="/submit" className={({ isActive }) => (isActive ? "active" : "")}>
                Submit a print
              </NavLink>
            )}
        </nav>
        <div className="nav-foot">
          {user?.display_name} · {user?.role}
          <div>
            <button className="btn btn-sm btn-ghost" onClick={logout}>sign out</button>
          </div>
        </div>
      </aside>
      <main className="main">
        <Routes>
          {isOp ? (
            <>
              <Route path="/" element={<Dashboard />} />
              <Route path="/queue" element={<Queue />} />
              <Route path="/fleet" element={<Fleet />} />
              <Route path="/materials" element={<Materials />} />
              <Route path="/builds/:id" element={<BuildDetail />} />
              <Route path="/tickets/:id" element={<TicketDetail />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </>
          ) : (
            <>
              <Route path="/submit" element={<Submit />} />
              <Route path="/tickets/:id" element={<TicketDetail />} />
              <Route path="*" element={<Navigate to="/submit" replace />} />
            </>
          )}
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="login-wrap"><Loading /></div>;
  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: loc }} />} />
      </Routes>
    );
  }
  return <Shell />;
}
