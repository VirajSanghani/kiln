import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [username, setU] = useState("rk");
  const [password, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const u = await login(username, password);
      nav(u.role === "operator" ? "/" : "/submit", { replace: true });
    } catch {
      setErr("invalid username or password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="panel login-card stack" onSubmit={submit}>
        <div>
          <div className="brand">KILN</div>
          <div className="hint">print-lab operations — sign in</div>
        </div>
        <div className="field">
          <label>username</label>
          <input value={username} onChange={(e) => setU(e.target.value)} autoFocus />
        </div>
        <div className="field">
          <label>password</label>
          <input type="password" value={password} onChange={(e) => setP(e.target.value)} />
        </div>
        {err && <div className="error">{err}</div>}
        <button className="btn btn-primary" disabled={busy}>{busy ? "…" : "Sign in"}</button>
        <div className="hint">demo: operator <b>rk</b>/rk-pw · requester <b>ana</b>/ana-pw</div>
      </form>
    </div>
  );
}
