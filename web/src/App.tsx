import { useQuery } from "@tanstack/react-query";
import { fetchReadiness } from "./api";

export default function App() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["health"],
    queryFn: fetchReadiness,
    refetchInterval: 5000,
  });

  const apiOk = !isError && !!data;
  const dbConnected = data?.db === "connected";

  return (
    <div className="shell">
      <header className="masthead">
        <div className="wordmark">KILN</div>
        <div className="subtitle">print-lab operations · skeleton</div>
      </header>

      <main className="card">
        <h1>Stack check</h1>
        <p className="lede">React shell → API → Postgres, verified end to end.</p>

        <div className="status-grid">
          <StatusRow
            label="Web shell"
            ok={true}
            detail="vite + react + tanstack query"
          />
          <StatusRow
            label="API"
            ok={apiOk}
            detail={
              isLoading
                ? "contacting…"
                : isError
                  ? "unreachable"
                  : `${data?.service} v${data?.version}`
            }
          />
          <StatusRow
            label="Database"
            ok={dbConnected}
            detail={isLoading ? "—" : (data?.db ?? "unknown")}
          />
        </div>

        {data?.time && <p className="ts">last checked {data.time}</p>}
      </main>

      <footer className="footnote">
        Phase 0 — skeleton only. No data model yet.
      </footer>
    </div>
  );
}

function StatusRow({
  label,
  ok,
  detail,
}: {
  label: string;
  ok: boolean;
  detail: string;
}) {
  return (
    <div className="status-row">
      <span className={`dot ${ok ? "dot-ok" : "dot-bad"}`} />
      <span className="status-label">{label}</span>
      <span className="status-detail">{detail}</span>
    </div>
  );
}
