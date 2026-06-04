import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Loading, PageHead, Panel } from "../ui";

export default function Materials() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["materials"], queryFn: () => api.get("/materials") });
  const [amt, setAmt] = useState<Record<number, string>>({});

  const restock = useMutation({
    mutationFn: ({ id, delta }: { id: number; delta: number }) => api.post(`/materials/${id}/restock`, { delta, note: "restock" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["materials"] }),
  });

  if (isLoading || !data) return <><PageHead title="Material shelf" /><Loading /></>;

  return (
    <>
      <PageHead title="Material shelf" sub="inventory informs, never blocks — warnings are advisory" />
      <Panel>
        <table>
          <thead>
            <tr><th>kind</th><th>spec / color</th><th>remaining</th><th>lot / opened</th><th>warnings</th><th>restock</th></tr>
          </thead>
          <tbody>
            {data.map((m: any) => (
              <tr key={m.id}>
                <td className="mono-sm">{m.kind}</td>
                <td>{m.spec}{m.color ? <span className="muted"> · {m.color}</span> : ""}</td>
                <td><b>{m.qty_remaining}{m.unit}</b>{m.reorder_threshold != null && <span className="mono-sm muted"> / reorder {m.reorder_threshold}</span>}</td>
                <td className="mono-sm">{m.lot ?? "—"}{m.opened_date ? ` · ${m.opened_date}` : ""}</td>
                <td>
                  {m.warnings.length === 0 ? <span className="muted">—</span> :
                    m.warnings.map((w: any, i: number) => (
                      <div key={i} className={`warn-line sev-${w.severity}`}>{w.message}</div>
                    ))}
                </td>
                <td>
                  <div className="row">
                    <input style={{ width: 64 }} placeholder="g/mL" value={amt[m.id] ?? ""}
                      onChange={(e) => setAmt({ ...amt, [m.id]: e.target.value })} />
                    <button className="btn btn-sm" disabled={restock.isPending || !amt[m.id]}
                      onClick={() => restock.mutate({ id: m.id, delta: Number(amt[m.id]) })}>+ add</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
