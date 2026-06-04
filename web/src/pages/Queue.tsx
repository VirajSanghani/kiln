import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Empty, Loading, PageHead, Panel, StatusPill, Toggle } from "../ui";

const PROCESSES = ["FDM", "SLA", "SLS", "MJF"] as const;

export default function Queue() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [batch, setBatch] = useState<Record<string, boolean> | null>(null);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  const jobsQ = useQuery({ queryKey: ["jobs"], queryFn: () => api.get("/jobs") });
  const params = batch
    ? "?" + PROCESSES.map((p) => `${p.toLowerCase()}=${batch[p]}`).join("&")
    : "";
  const schedQ = useQuery({ queryKey: ["schedule", params], queryFn: () => api.get("/schedule" + params) });

  const queueJob = useMutation({
    mutationFn: (id: number) => api.post(`/jobs/${id}/queue`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); qc.invalidateQueries({ queryKey: ["schedule"] }); },
  });
  const confirm = useMutation({
    mutationFn: (v: { printer_id: number; job_ids: number[] }) => api.post("/schedule/confirm", v),
    onSuccess: (build) => nav(`/builds/${build.id}`),
  });

  if (jobsQ.isLoading || schedQ.isLoading || !jobsQ.data || !schedQ.data) {
    return <><PageHead title="Queue & Schedule" /><Loading /></>;
  }

  const jobs = jobsQ.data;
  const sched = schedQ.data;
  const effBatch = batch ?? sched.batching;
  const byState = (s: string) => jobs.filter((j: any) => j.status === s);

  return (
    <>
      <PageHead title="Queue & Schedule"
        sub="the scheduler proposes; you dispose — nothing auto-starts a machine" />

      {/* triage lanes */}
      <Panel title="Triage">
        <div className="lanes">
          <Lane title="Needs triage" hint="submitted — not yet in the queue">
            {byState("submitted").length === 0 && <Empty>nothing waiting</Empty>}
            {byState("submitted").map((j: any) => (
              <div className="card" key={j.id}>
                <div className="flex-between">
                  <span className="t">{j.ticket_title}</span>
                  <StatusPill status={j.status} />
                </div>
                <div className="mono-sm">{j.target_process} · {j.material_pref ?? "—"} · {j.priority} · {j.requester}</div>
                <button className="btn btn-sm btn-primary" style={{ marginTop: 6 }}
                  disabled={queueJob.isPending}
                  onClick={() => queueJob.mutate(j.id)}>Queue</button>
              </div>
            ))}
          </Lane>
          <Lane title="Queued" hint="awaiting a Build">
            {byState("queued").length === 0 && <Empty>queue empty</Empty>}
            {byState("queued").map((j: any) => (
              <div className="card" key={j.id}>
                <div className="flex-between"><span className="t">{j.ticket_title}</span><StatusPill status={j.status} /></div>
                <div className="mono-sm">{j.target_process} · {j.material_pref ?? "—"} · {j.priority}</div>
              </div>
            ))}
          </Lane>
          <Lane title="Scheduled" hint="placed on a Build">
            {byState("scheduled").length === 0 && <Empty>none</Empty>}
            {byState("scheduled").map((j: any) => (
              <div className="card" key={j.id}>
                <div className="flex-between"><span className="t">{j.ticket_title}</span><StatusPill status={j.status} /></div>
                <div className="mono-sm">
                  {j.target_process} · {j.build_id ? <Link to={`/builds/${j.build_id}`}>Build #{j.build_id}</Link> : "—"}
                </div>
              </div>
            ))}
          </Lane>
        </div>
      </Panel>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        {/* capability buckets */}
        <Panel title="Capability buckets" right={<span className="mono-sm">ordered next-up per printer</span>}>
          <div className="stack">
            {sched.buckets.map((bk: any) => (
              <div key={bk.printer_id}>
                <div className="flex-between">
                  <b>{bk.printer_name}</b>
                  <span className="row">
                    <span className="mono-sm">{bk.process}</span>
                    <StatusPill status={bk.busy ? (bk.printer_status === "printing" ? "printing" : "running") : "queued"} />
                  </span>
                </div>
                {bk.preemption_note && <div className="warn-line sev-warn">{bk.preemption_note}</div>}
                {bk.next_up.length === 0 ? <div className="mono-sm muted">— no eligible jobs</div> : (
                  <table>
                    <tbody>
                      {bk.next_up.map((r: any, i: number) => (
                        <tr key={r.job_id}>
                          <td className="muted" style={{ width: 18 }}>{i + 1}</td>
                          <td>{r.title}{r.needs_swap && <> <span className="badge-est">swap</span></>}</td>
                          <td>{r.boosted ? <span className="pill pill-boost">boosted</span> : <span className="mono-sm">{r.priority}</span>}</td>
                          <td className="mono-sm">{r.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </div>
        </Panel>

        {/* proposals */}
        <Panel title="Proposed builds"
          right={<span className="row">{PROCESSES.map((p) => (
            <Toggle key={p} label={p} on={!!effBatch[p]}
              onClick={() => setBatch({ ...effBatch, [p]: !effBatch[p] })} />
          ))}</span>}>
          <div className="hint" style={{ marginBottom: 10 }}>
            batching ON = group same-material jobs (throughput ↑, fairness ↓). SLS/MJF default ON. Fill cap {Math.round(sched.fill_cap_pct * 100)}%.
          </div>
          {sched.proposals.filter((p: any) => !dismissed.has(p.printer_id)).length === 0 && (
            <Empty>no proposals — all eligible printers are busy or the queue is empty</Empty>
          )}
          <div className="stack">
            {sched.proposals.filter((p: any) => !dismissed.has(p.printer_id)).map((p: any) => (
              <div className="card" key={p.printer_id}>
                <div className="flex-between">
                  <b>{p.printer_name}</b>
                  <span className="mono-sm">{p.process} · {p.material_spec ?? "—"}</span>
                </div>
                <div className="mono-sm">
                  {p.parts} part(s) · fill {Math.round(p.fill_pct * 100)}%/{Math.round(p.fill_cap_pct * 100)}%
                  {p.needs_swap && <span className="badge-est" style={{ marginLeft: 6 }}>needs swap</span>}
                </div>
                <div className={"warn-line " + (p.material.fits ? "sev-info" : "sev-warn")}>
                  {p.material.note} <span className="badge-est">est.</span>
                </div>
                <div className="row" style={{ marginTop: 8 }}>
                  <button className="btn btn-sm btn-primary" disabled={confirm.isPending}
                    onClick={() => confirm.mutate({ printer_id: p.printer_id, job_ids: p.job_ids })}>
                    Confirm &amp; start
                  </button>
                  <button className="btn btn-sm btn-ghost"
                    onClick={() => setDismissed(new Set([...dismissed, p.printer_id]))}>dismiss</button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}

function Lane({ title, hint, children }: any) {
  return (
    <div className="lane">
      <h3>{title}</h3>
      <div className="mono-sm muted" style={{ marginBottom: 8 }}>{hint}</div>
      {children}
    </div>
  );
}
