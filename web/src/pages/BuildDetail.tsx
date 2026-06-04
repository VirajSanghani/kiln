import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useToast } from "../toast";
import { Loading, PageHead, Panel, StatusPill } from "../ui";

export default function BuildDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const { data: b, isLoading } = useQuery({ queryKey: ["build", id], queryFn: () => api.get(`/builds/${id}`) });

  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: any }) => api.post(`/builds/${id}/${path}`, body),
    onSuccess: (_d, v) => { qc.invalidateQueries({ queryKey: ["build", id] }); toast.push(`Build ${v.path === "advance" ? `→ ${v.body.to_stage.replace(/_/g, " ")}` : v.path}`); },
    onError: (e: any) => toast.push(e?.message ?? "transition failed", "bad"),
  });
  const rejectJob = useMutation({
    mutationFn: (jobId: number) => api.post(`/jobs/${jobId}/reject`, { note: "rejected at QC" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["build", id] }); toast.push("Part rejected at QC", "info"); },
    onError: (e: any) => toast.push(e?.message ?? "could not reject", "bad"),
  });

  if (isLoading || !b) return <><PageHead title="Build" /><Loading /></>;

  const stageIndex = b.recipe.findIndex((s: any) => s.name === b.current_stage);
  const cur = b.recipe[stageIndex];
  const allowed: string[] = b.status === "running" ? cur?.allowed_next ?? [] : [];
  const terminal = ["completed", "failed", "cancelled"].includes(b.status);
  const evByStage: Record<string, any> = {};
  for (const e of b.timeline) evByStage[e.to] = e;

  return (
    <>
      <PageHead title={`Build #${b.id}`}
        sub={`${b.printer_name} · ${b.process} · ${b.material_spec ?? "—"}`}
        right={<StatusPill status={b.effective_state} />} />

      <Panel title="Stage timeline">
        <div className="timeline">
          {b.recipe.map((s: any, i: number) => {
            const done = i < stageIndex || b.status === "completed";
            const isCur = i === stageIndex && !["completed"].includes(b.status);
            const ev = evByStage[s.name];
            return (
              <div className="tl-stage" key={s.name}>
                <div className="tl-node">
                  <span className={`tl-dot ${done ? "done" : ""} ${isCur ? "current" : ""}`} />
                  <span className="tl-name">{s.label}</span>
                  {i < b.recipe.length - 1 && <span className="tl-arrow">→</span>}
                </div>
                <span className={`tl-type ${s.type}`}>{s.type}{s.occupies_machine ? " · on-machine" : ""}</span>
                {ev && <span className="tl-meta">{ev.actor ?? "—"} · {ev.at?.slice(5, 16).replace("T", " ")}</span>}
              </div>
            );
          })}
        </div>

        {!terminal && (
          <div className="row" style={{ marginTop: 8 }}>
            {allowed.map((to) => (
              <button key={to} className="btn btn-primary btn-sm" disabled={act.isPending}
                onClick={() => act.mutate({ path: "advance", body: { to_stage: to } })}>
                advance → {to.replace(/_/g, " ")}
              </button>
            ))}
            {b.status === "running" && <button className="btn btn-sm" onClick={() => act.mutate({ path: "hold" })}>hold</button>}
            {b.status === "on_hold" && <button className="btn btn-sm btn-primary" onClick={() => act.mutate({ path: "resume" })}>resume</button>}
            {!terminal && <button className="btn btn-sm btn-danger" onClick={() => act.mutate({ path: "fail", body: { reason: "operator marked failed" } })}>fail</button>}
            {!terminal && <button className="btn btn-sm btn-ghost" onClick={() => act.mutate({ path: "cancel" })}>cancel</button>}
          </div>
        )}
        {act.isError && <div className="error" style={{ marginTop: 8 }}>{(act.error as any)?.message}</div>}
      </Panel>

      <Panel title="Jobs on this build">
        <table>
          <thead><tr><th>Job</th><th>Ticket</th><th>Status</th><th>QC</th><th>Allocated</th><th></th></tr></thead>
          <tbody>
            {b.jobs.map((j: any) => (
              <tr key={j.id}>
                <td>#{j.id}</td>
                <td><Link to={`/tickets/${j.ticket_id}`}>T-{j.ticket_id}</Link></td>
                <td><StatusPill status={j.status} /></td>
                <td className="mono-sm">{j.qc_outcome ?? "—"}</td>
                <td className="mono-sm">{j.allocated_qty != null ? `${j.allocated_qty}${j.allocated_unit ?? ""}` : "—"}</td>
                <td>
                  {!j.terminal_status && (
                    <button className="btn btn-sm btn-danger" onClick={() => rejectJob.mutate(j.id)}>reject (QC)</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="hint" style={{ marginTop: 8 }}>
          Rejecting one part overrides only that job (G1); the build carries on for the rest.
        </div>
      </Panel>
    </>
  );
}
