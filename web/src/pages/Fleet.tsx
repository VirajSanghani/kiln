import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Loading, PageHead, StatusPill } from "../ui";

export default function Fleet() {
  const { data, isLoading } = useQuery({ queryKey: ["printers"], queryFn: () => api.get("/printers") });
  if (isLoading || !data) return <><PageHead title="Fleet" /><Loading /></>;

  return (
    <>
      <PageHead title="Fleet" sub="printer status is human-updated — no machine telemetry" />
      <div className="grid cols-auto">
        {data.map((p: any) => (
          <div className="panel" key={p.id}>
            <div className="flex-between">
              <h2 style={{ fontSize: 15 }}>{p.name}</h2>
              <StatusPill status={p.status} />
            </div>
            <div className="mono-sm" style={{ marginTop: 6 }}>{p.process} · {p.build_volume.join("×")} mm</div>
            <div className="mono-sm">loaded: {p.loaded_material ?? "—"}</div>
            {p.running_build_id ? (
              <div className="mono-sm" style={{ marginTop: 6 }}>
                running <Link to={`/builds/${p.running_build_id}`}>Build #{p.running_build_id}</Link> @ {p.running_stage}
              </div>
            ) : <div className="mono-sm muted" style={{ marginTop: 6 }}>idle</div>}
            {p.capabilities && Object.keys(p.capabilities).length > 0 && (
              <div className="mono-sm muted" style={{ marginTop: 6 }}>
                {Object.entries(p.capabilities).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join("/") : v}`).join(" · ")}
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
