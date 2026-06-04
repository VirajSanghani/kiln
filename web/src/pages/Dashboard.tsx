import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ago } from "../api";
import { PageHead, SkeletonTiles } from "../ui";

// The hero surface. EVERY figure comes from /api/dashboard, derived from a real query.
// Each tile: LABEL → big Fraunces NUMBER → CONTEXT (real trend vs prior period / target /
// split) → ↳ backing-query caption. Sparse data shows real sparse numbers or "needs more
// data" — never a placeholder.

function Trend({ delta, unit = "", goodWhenUp = true }: { delta: number; unit?: string; goodWhenUp?: boolean }) {
  if (delta === 0) return <span className="trend-flat">→ no change</span>;
  const up = delta > 0;
  const good = up === goodWhenUp;
  const cls = good ? "trend-up" : "trend-down";
  const arrow = up ? "▲" : "▼";
  return <span className={cls}>{arrow} {up ? "+" : ""}{Math.round(delta * 100) / 100}{unit}</span>;
}

export default function Dashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"], queryFn: () => api.get("/dashboard"), refetchInterval: 12000,
  });
  const { data: feed } = useQuery({
    queryKey: ["activity"], queryFn: () => api.get("/activity"), refetchInterval: 12000,
  });
  if (isLoading || !data) return <><PageHead title="Ops dashboard" /><SkeletonTiles n={6} /></>;

  const { throughput: t, fleet: f, success: s, queue_wait: q, burn: b } = data;
  const maxDay = Math.max(1, ...t.by_day.map((d: any) => d.count));
  const maxBurn = Math.max(1, ...b.by_material.map((m: any) => m.consumed));
  const gen = data.generated_at?.slice(11, 16);

  return (
    <>
      <PageHead title="Ops dashboard"
        sub="every figure derives from a query over real event data — no placeholders"
        right={<span className="hint">updated {gen} UTC</span>} />

      {/* top band — golden triangle: throughput hero top-left */}
      <div className="dash-band">
        <section className={`metric hero ${t.needs_more_data ? "sparse" : ""}`} aria-label="Throughput">
          <div className="label">Throughput · {t.window_days}d</div>
          {t.needs_more_data ? <div className="num">needs more data</div> : (
            <>
              <div className="num">{t.completed_in_window}<span className="unit">builds</span></div>
              <div className="spark" aria-hidden="true">
                {t.by_day.map((d: any) => (
                  <i key={d.date} className={d.count ? "on" : ""}
                     style={{ height: `${(d.count / maxDay) * 100}%` }} title={`${d.date}: ${d.count}`} />
                ))}
              </div>
              <div className="ctx"><Trend delta={t.delta} /> vs prior {t.window_days}d ({t.prior_window}) · {t.completed_total} all-time</div>
            </>
          )}
          <div className="q">↳ {t.query}</div>
        </section>

        <section className={`metric sup ${f.needs_more_data ? "sparse" : ""}`} aria-label="Fleet utilization">
          <div className="label">Fleet utilization</div>
          <div className="num">{f.utilization_pct ?? "—"}<span className="unit">%</span></div>
          <div className="barwrap" aria-hidden="true">
            {f.printing > 0 && <i className="seg-printing" style={{ flex: f.printing }} />}
            {f.occupied > 0 && <i className="seg-occupied" style={{ flex: f.occupied }} />}
            {f.available > 0 && <i className="seg-available" style={{ flex: f.available }} />}
            {f.down > 0 && <i className="seg-down" style={{ flex: f.down }} />}
          </div>
          <div className="ctx">{f.in_use} of {f.total} machines in use · <span className="muted">{f.available} available</span></div>
          <div className="q">↳ {f.query}</div>
        </section>

        <section className={`metric sup ${s.needs_more_data ? "sparse" : ""}`} aria-label="Success rate">
          <div className="label">Success rate</div>
          {s.needs_more_data ? <div className="num">needs more data</div> : (
            <>
              <div className="num">{s.rate_pct}<span className="unit">%</span></div>
              <div className="ctx">
                {s.rate_pct >= s.target_pct
                  ? <span className="trend-up">▲ at/above</span>
                  : <span className="trend-down">▼ below</span>} target {s.target_pct}%
                <br />{s.delivered} delivered · {s.failed} failed · {s.rejected} QC-rejected
              </div>
            </>
          )}
          <div className="q">↳ {s.query}</div>
        </section>
      </div>

      {/* secondary row — tertiary metrics */}
      <div className="dash-row">
        <section className={`metric ${q.needs_more_data ? "sparse" : ""}`} aria-label="Average queue wait">
          <div className="label">Avg queue wait</div>
          {q.needs_more_data ? <div className="num">needs more data</div> : (
            <>
              <div className="num">{q.avg_hours}<span className="unit">h</span></div>
              <div className="ctx">
                across {q.sample} jobs ·{" "}
                {q.prior_sample > 0 && q.window_avg != null
                  ? <><Trend delta={(q.window_avg - q.prior_avg)} unit="h" goodWhenUp={false} /> vs prior {data.throughput.window_days}d</>
                  : <span className="trend-flat">no prior-period data</span>}
              </div>
            </>
          )}
          <div className="q">↳ {q.query}</div>
        </section>

        <section className="metric" aria-label="Material burn">
          <div className="label">Material burn · {data.throughput.window_days}d</div>
          {b.needs_more_data ? <div className="num sparse" style={{ fontSize: 17 }}>needs more data</div> : (
            <table style={{ marginTop: 2 }}>
              <tbody>
                {b.by_material.map((m: any) => (
                  <tr key={m.spec}>
                    <td style={{ width: 90, border: "none", padding: "5px 0" }}>{m.spec}</td>
                    <td style={{ border: "none", padding: "5px 8px" }}>
                      <span className="hbar" style={{ width: `${(m.consumed / maxBurn) * 100}%` }} />
                    </td>
                    <td className="r" style={{ border: "none", padding: "5px 0" }}>{m.consumed}{m.unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {b.projected_est.length > 0 && (
            <div className="ctx">in-flight projection <span className="badge-est">est.</span>{" "}
              {b.projected_est.map((p: any) => `${p.spec} ${p.qty}`).join(" · ")}</div>
          )}
          <div className="q">↳ {b.query}</div>
        </section>
      </div>

      {/* live activity — the append-only StageEvent log, the truth-of-record */}
      <section className="panel" style={{ marginTop: 16 }} aria-label="Recent activity">
        <div className="flex-between" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0, fontSize: 15 }}>Recent activity</h2>
          <span className="hint">live · from the StageEvent log</span>
        </div>
        {!feed || feed.length === 0 ? <div className="empty">no activity yet</div> : (
          <div className="feed">
            {feed.map((e: any, i: number) => (
              <div className="feed-row" key={i}>
                <span className="feed-time">{ago(e.at)}</span>
                <span className="feed-actor">{e.actor}</span>
                <span className="feed-label">
                  {e.build_id
                    ? <Link to={`/builds/${e.build_id}`}>{e.label}</Link>
                    : e.label}
                  {e.note && <span className="muted"> — {e.note}</span>}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
