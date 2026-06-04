import type { ReactNode } from "react";

// Map any KILN status string to a pill style.
const STATUS_STYLE: Record<string, string> = {
  done: "pill-ok",
  completed: "pill-ok",
  printing: "pill-active",
  failed: "pill-bad",
  qc_rejected: "pill-bad",
  cancelled: "pill-bad",
  on_hold: "pill-warn",
  running: "pill-active",
  submitted: "pill-neutral",
  queued: "pill-neutral",
  scheduled: "pill-neutral",
};

export function StatusPill({ status }: { status: string }) {
  const cls = STATUS_STYLE[status] ?? "pill-neutral";
  return (
    <span className={`pill ${cls}`}>
      <span className="dot" />
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function Panel({ title, right, children }: { title?: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      {title && (
        <div className="flex-between" style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>{title}</h2>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function PageHead({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {right}
    </div>
  );
}

export function Loading() {
  return <div className="empty">loading…</div>;
}

export function Skeleton({ h = 16, w = "100%", style }: { h?: number; w?: number | string; style?: any }) {
  return <div className="skel" style={{ height: h, width: w, ...style }} />;
}

export function SkeletonTiles({ n = 5 }: { n?: number }) {
  return (
    <div className="grid cols-2">
      {Array.from({ length: n }).map((_, i) => (
        <div className="metric" key={i}>
          <Skeleton h={10} w={90} />
          <Skeleton h={36} w={120} style={{ marginTop: 8 }} />
          <Skeleton h={12} w="70%" style={{ marginTop: 8 }} />
        </div>
      ))}
    </div>
  );
}

export function Toggle({ on, onClick, label }: { on: boolean; onClick: () => void; label: string }) {
  return (
    <span className="toggle" onClick={onClick} role="button">
      <span className={`track ${on ? "on" : ""}`}>
        <span className="knob" />
      </span>
      {label}
    </span>
  );
}
