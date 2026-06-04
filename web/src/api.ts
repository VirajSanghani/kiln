export type Health = {
  status: string;
  service: string;
  version: string;
  db: string;
  time: string;
};

// Hits the readiness endpoint through the vite /api proxy. Returns JSON even on a
// 503 (db unreachable) so the UI can show the honest degraded state.
export async function fetchReadiness(): Promise<Health> {
  const res = await fetch("/api/health/ready");
  return res.json();
}
