const TOKEN_KEY = "kiln_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Opts = { method?: string; json?: unknown; body?: BodyInit };

async function req(path: string, opts: Opts = {}): Promise<any> {
  const headers = new Headers();
  const tok = getToken();
  if (tok) headers.set("Authorization", `Bearer ${tok}`);
  let body = opts.body;
  if (opts.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(opts.json);
  }
  const res = await fetch(`/api${path}`, { method: opts.method ?? "GET", headers, body });
  if (res.status === 204) return null;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, (data && data.detail) || res.statusText);
  return data;
}

export const api = {
  get: (p: string) => req(p),
  post: (p: string, json?: unknown) => req(p, { method: "POST", json }),
  postForm: (p: string, form: FormData) => req(p, { method: "POST", body: form }),
  login: (username: string, password: string) =>
    req("/auth/login", { method: "POST", json: { username, password } }),
};

// ---- small shared formatters ----
export const fmtTime = (s?: number | null) =>
  s == null ? "—" : `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;

export function ago(iso?: string | null): string {
  if (!iso) return "—";
  const h = (Date.now() - new Date(iso).getTime()) / 3.6e6;
  if (h < 1) return "<1h ago";
  if (h < 48) return `${Math.round(h)}h ago`;
  return `${Math.round(h / 24)}d ago`;
}
