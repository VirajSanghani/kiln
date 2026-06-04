import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Empty, Loading, PageHead, Panel, StatusPill } from "../ui";

// The one minimal requester surface: submit a print + see my jobs' status.
export default function Submit() {
  const qc = useQueryClient();
  const [form, setForm] = useState({ title: "", target_process: "FDM", material_pref: "", priority: "normal", deadline: "" });
  const [file, setFile] = useState<File | null>(null);
  const [summary, setSummary] = useState("");
  const [msg, setMsg] = useState("");

  const jobsQ = useQuery({ queryKey: ["myjobs"], queryFn: () => api.get("/jobs") });

  const submit = useMutation({
    mutationFn: async () => {
      const fd = new FormData();
      fd.append("title", form.title);
      fd.append("target_process", form.target_process);
      fd.append("priority", form.priority);
      if (form.material_pref) fd.append("material_pref", form.material_pref);
      if (form.deadline) fd.append("deadline", form.deadline);
      if (summary) fd.append("slicer_summary", summary);
      fd.append("file", file ?? new Blob([""]), file?.name ?? "model.stl");
      return api.postForm("/tickets", fd);
    },
    onSuccess: (t) => {
      setMsg(`Submitted “${t.title}” — an operator will triage it into the queue.`);
      setForm({ title: "", target_process: "FDM", material_pref: "", priority: "normal", deadline: "" });
      setFile(null); setSummary("");
      qc.invalidateQueries({ queryKey: ["myjobs"] });
    },
  });

  return (
    <>
      <PageHead title="Submit a print" sub="upload a model, we’ll parse the slicer estimate" />
      <div className="grid cols-2">
        <Panel title="New request">
          <form onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
            <div className="field"><label>title</label>
              <input value={form.title} required onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
            <div className="row">
              <div className="field" style={{ flex: 1 }}><label>process</label>
                <select value={form.target_process} onChange={(e) => setForm({ ...form, target_process: e.target.value })}>
                  {["FDM", "SLA", "SLS", "MJF"].map((p) => <option key={p}>{p}</option>)}
                </select></div>
              <div className="field" style={{ flex: 1 }}><label>priority</label>
                <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                  {["critical", "high", "normal", "low"].map((p) => <option key={p}>{p}</option>)}
                </select></div>
            </div>
            <div className="row">
              <div className="field" style={{ flex: 1 }}><label>material pref</label>
                <input value={form.material_pref} placeholder="PETG" onChange={(e) => setForm({ ...form, material_pref: e.target.value })} /></div>
              <div className="field" style={{ flex: 1 }}><label>deadline</label>
                <input type="date" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} /></div>
            </div>
            <div className="field"><label>model file (STL / gcode)</label>
              <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
            <div className="field"><label>slicer summary (optional — paste to parse time/material)</label>
              <textarea rows={3} value={summary} placeholder="; estimated printing time (normal mode) = 1h 48m&#10;; filament used [g] = 22"
                onChange={(e) => setSummary(e.target.value)} /></div>
            <button className="btn btn-primary" disabled={submit.isPending}>{submit.isPending ? "…" : "Submit"}</button>
            {msg && <div className="hint" style={{ marginTop: 10, color: "var(--green)" }}>{msg}</div>}
            {submit.isError && <div className="error" style={{ marginTop: 10 }}>{(submit.error as any)?.message}</div>}
          </form>
        </Panel>

        <Panel title="My jobs">
          {jobsQ.isLoading ? <Loading /> : (jobsQ.data?.length ?? 0) === 0 ? <Empty>no jobs yet</Empty> : (
            <table>
              <thead><tr><th>title</th><th>process</th><th>status</th></tr></thead>
              <tbody>
                {jobsQ.data.map((j: any) => (
                  <tr key={j.id}>
                    <td>{j.ticket_title}</td>
                    <td className="mono-sm">{j.target_process}</td>
                    <td><StatusPill status={j.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </>
  );
}
