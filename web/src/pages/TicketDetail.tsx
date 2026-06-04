import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, fmtTime } from "../api";
import { Loading, PageHead, Panel, StatusPill } from "../ui";

export default function TicketDetail() {
  const { id } = useParams();
  const { data: t, isLoading } = useQuery({ queryKey: ["ticket", id], queryFn: () => api.get(`/tickets/${id}`) });
  if (isLoading || !t) return <><PageHead title="Ticket" /><Loading /></>;

  return (
    <>
      <PageHead title={t.title} sub={`T-${t.id} · ${t.target_process} · ${t.priority}${t.deadline ? ` · due ${t.deadline}` : ""}`}
        right={<StatusPill status={t.status} />} />

      <Panel title="File versions" right={<span className="mono-sm">which version printed is pinned per job</span>}>
        <table>
          <thead><tr><th>v</th><th>file</th><th>slicer est.</th><th>material</th><th>bbox</th><th></th></tr></thead>
          <tbody>
            {t.file_versions.map((fv: any) => (
              <tr key={fv.id}>
                <td>{fv.version_no}{fv.id === t.current_file_version_id && <span className="badge-est" style={{ marginLeft: 6 }}>current</span>}</td>
                <td className="mono-sm">{fv.filename}</td>
                <td>{fmtTime(fv.est_time_seconds)} {fv.estimate_label && <span className="badge-est">{fv.estimate_label}</span>}</td>
                <td className="mono-sm">{fv.est_material_qty != null ? `${fv.est_material_qty}${fv.est_material_unit ?? ""} (${fv.slicer_name})` : "—"}</td>
                <td className="mono-sm">{fv.bbox ? fv.bbox.join("×") : "—"}</td>
                <td className="mono-sm">{fv.checksum?.slice(0, 8)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Jobs">
        <table>
          <thead><tr><th>Job</th><th>Status</th><th>Build</th><th>QC</th></tr></thead>
          <tbody>
            {t.jobs.map((j: any) => (
              <tr key={j.id}>
                <td>#{j.id}</td>
                <td><StatusPill status={j.status} /></td>
                <td>{j.build_id ? <Link to={`/builds/${j.build_id}`}>Build #{j.build_id}</Link> : <span className="muted">{j.queue_state}</span>}</td>
                <td className="mono-sm">{j.qc_outcome ?? "—"}{j.fail_reason ? ` · ${j.fail_reason}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
