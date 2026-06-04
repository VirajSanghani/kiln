import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Loading, PageHead } from "../ui";

// The hero. EVERY figure here comes from /api/dashboard, which derives it from a real
// query over real data. Each tile prints the backing query (traceability). A metric that
// can't be computed shows "needs more data" — never a placeholder number.

function Metric({ label, sparse, children, query }: any) {
  return (
    <div className={`metric ${sparse ? "sparse" : ""}`}>
      <div className="label">{label}</div>
      {sparse ? <div className="value">needs more data</div> : children}
      <div className="query">↳ {query}</div>
    </div>
  );
}

export default function Dashboard() {
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get("/dashboard") });
  if (isLoading || !data) return <><PageHead title="Ops dashboard" /><Loading /></>;

  const { throughput: t, fleet: f, success: s, queue_wait: q, burn: b } = data;
  const maxDay = Math.max(1, ...t.by_day.map((d: any) => d.count));

  return (
    <>
      <PageHead title="Ops dashboard" sub="every figure derives from a query over real event data — no placeholders" />

      <div className="grid cols-3" style={{ marginBottom: 16 }}>
        <Metric label={`Throughput · ${t.window_days}d`} sparse={t.needs_more_data} query={t.query}>
          <div className="value">{t.completed_in_window}<span className="unit">builds</span></div>
          <div className="sub">{t.completed_total} completed all-time</div>
          <div className="spark">
            {t.by_day.map((d: any) => (
              <div key={d.date} className={d.count ? "has" : ""}
                   style={{ height: `${(d.count / maxDay) * 100}%` }} title={`${d.date}: ${d.count}`} />
            ))}
          </div>
        </Metric>

        <Metric label="Fleet utilization" sparse={f.needs_more_data} query={f.query}>
          <div className="value">{f.utilization_pct ?? "—"}<span className="unit">%</span></div>
          <div className="bar">
            {f.printing > 0 && <span className="seg-printing" style={{ flex: f.printing }} />}
            {f.occupied > 0 && <span className="seg-occupied" style={{ flex: f.occupied }} />}
            {f.available > 0 && <span className="seg-available" style={{ flex: f.available }} />}
            {f.down > 0 && <span className="seg-down" style={{ flex: f.down }} />}
          </div>
          <div className="legend">
            <span><i className="seg-printing" /> printing {f.printing}</span>
            <span><i className="seg-occupied" /> occupied {f.occupied}</span>
            <span><i className="seg-available" /> available {f.available}</span>
            {f.down > 0 && <span><i className="seg-down" /> down {f.down}</span>}
          </div>
        </Metric>

        <Metric label="Success rate" sparse={s.needs_more_data} query={s.query}>
          <div className="value">{s.rate_pct ?? "—"}<span className="unit">%</span></div>
          <div className="sub">{s.delivered} delivered · {s.failed} failed · {s.rejected} QC-rejected
            {s.cancelled ? ` · ${s.cancelled} cancelled` : ""}</div>
        </Metric>
      </div>

      <div className="grid cols-2">
        <Metric label="Avg queue wait" sparse={q.needs_more_data} query={q.query}>
          <div className="value">{q.avg_hours ?? "—"}<span className="unit">h</span></div>
          <div className="sub">across {q.sample} job(s) that reached printing</div>
        </Metric>

        <div className="metric">
          <div className="label">Material burn</div>
          {b.needs_more_data ? (
            <div className="value sparse" style={{ fontSize: 18 }}>needs more data</div>
          ) : (
            <table style={{ marginTop: 4 }}>
              <tbody>
                {b.by_material.map((m: any) => (
                  <tr key={m.spec}>
                    <td>{m.spec}</td>
                    <td style={{ textAlign: "right" }}><b>{m.consumed}{m.unit}</b> consumed</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {b.projected_est.length > 0 && (
            <div className="sub">
              in-flight projection <span className="badge-est">est.</span>{" "}
              {b.projected_est.map((p: any) => `${p.spec} ${p.qty}`).join(" · ")}
            </div>
          )}
          <div className="query">↳ {b.query}</div>
        </div>
      </div>
    </>
  );
}
