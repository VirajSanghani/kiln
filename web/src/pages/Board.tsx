import { useMemo, useState } from "react";
import {
  DndContext, DragOverlay, PointerSensor, TouchSensor, KeyboardSensor,
  useDraggable, useDroppable, useSensor, useSensors,
  type DragEndEvent, type DragStartEvent,
} from "@dnd-kit/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useToast } from "../toast";
import { PageHead, Skeleton, StatusPill } from "../ui";

const POST = new Set(["support_removal", "drain", "wash", "cure", "cooldown", "depowder", "dye", "qc"]);
const ATTN = new Set(["failed", "qc_rejected", "on_hold", "cancelled"]);

const COLUMNS = [
  { key: "triage", title: "Needs triage", hint: "drag → Queued" },
  { key: "queued", title: "Queued", hint: "awaiting a Build" },
  { key: "scheduled", title: "Scheduled", hint: "on a Build" },
  { key: "printing", title: "Printing", hint: "on the machine" },
  { key: "post", title: "Post-process", hint: "off-machine" },
  { key: "done", title: "Done", hint: "delivered" },
  { key: "attention", title: "Attention", hint: "failed · held · rejected" },
] as const;

function colOf(status: string): string {
  if (status === "submitted") return "triage";
  if (status === "queued") return "queued";
  if (status === "scheduled") return "scheduled";
  if (status === "printing") return "printing";
  if (status === "done") return "done";
  if (ATTN.has(status)) return "attention";
  if (POST.has(status)) return "post";
  return "queued";
}

function age(iso?: string | null) {
  if (!iso) return "";
  const h = (Date.now() - new Date(iso).getTime()) / 3.6e6;
  return h < 24 ? `${Math.max(1, Math.round(h))}h` : `${Math.round(h / 24)}d`;
}

function deadlineTag(d?: string | null) {
  if (!d) return null;
  const days = Math.ceil((new Date(d).getTime() - Date.now()) / 8.64e7);
  if (days < 0) return <span className="dl dl-over">overdue</span>;
  if (days <= 2) return <span className="dl dl-soon">due {days}d</span>;
  return <span className="dl">due {d.slice(5)}</span>;
}

function Card({ job, draggable, onQueue }: { job: any; draggable: boolean; onQueue?: (id: number) => void }) {
  const nav = useNavigate();
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `job-${job.id}`, data: { col: colOf(job.status) }, disabled: !draggable,
  });
  return (
    <div
      ref={setNodeRef}
      className={`kc prio-${job.priority} ${draggable ? "drag" : ""} ${isDragging ? "dragging" : ""}`}
      {...(draggable ? { ...listeners, ...attributes } : {})}
    >
      <div className="kc-top">
        <span className="kc-title">{job.ticket_title}</span>
        <span className="kc-proc">{job.target_process}</span>
      </div>
      <div className="kc-meta">
        {job.material_pref ?? "—"} · {job.requester} · {age(job.queued_at ?? job.created_at)}
        {deadlineTag(job.deadline)}
      </div>
      <div className="kc-foot">
        <StatusPill status={job.status} />
        <span className="kc-links">
          {draggable && onQueue && (
            <button className="lnk lnk-go" onMouseDown={(e) => e.stopPropagation()} onClick={() => onQueue(job.id)}>queue →</button>
          )}
          <button className="lnk" onMouseDown={(e) => e.stopPropagation()} onClick={() => nav(`/tickets/${job.ticket_id}`)}>ticket</button>
          {job.build_id && <button className="lnk" onMouseDown={(e) => e.stopPropagation()} onClick={() => nav(`/builds/${job.build_id}`)}>build #{job.build_id}</button>}
        </span>
      </div>
    </div>
  );
}

function Column({ col, jobs, onQueue }: { col: any; jobs: any[]; onQueue: (id: number) => void }) {
  const { setNodeRef, isOver } = useDroppable({ id: col.key });
  return (
    <div ref={setNodeRef} className={`kcol ${isOver ? "over" : ""}`}>
      <div className="kcol-head">
        <span className="kcol-title">{col.title}</span>
        <span className="kcol-count">{jobs.length}</span>
      </div>
      <div className="kcol-hint">{col.hint}</div>
      <div className="kcol-body">
        {jobs.map((j) => <Card key={j.id} job={j} draggable={col.key === "triage"} onQueue={onQueue} />)}
      </div>
    </div>
  );
}

export default function Board() {
  const qc = useQueryClient();
  const toast = useToast();
  const [dragId, setDragId] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["jobs"], queryFn: () => api.get("/jobs"), refetchInterval: 8000,
  });
  const jobs: any[] = data ?? [];

  const queueJob = useMutation({
    mutationFn: (id: number) => api.post(`/jobs/${id}/queue`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["jobs"] }); toast.push("Triaged into the queue"); },
    onError: (e: any) => toast.push(e?.message ?? "could not queue", "bad"),
  });

  const byCol = useMemo(() => {
    const m: Record<string, any[]> = Object.fromEntries(COLUMNS.map((c) => [c.key, []]));
    for (const j of jobs) m[colOf(j.status)].push(j);
    return m;
  }, [jobs]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 6 } }),
    useSensor(KeyboardSensor),
  );

  function onStart(e: DragStartEvent) {
    setDragId(Number(String(e.active.id).replace("job-", "")));
  }
  function onEnd(e: DragEndEvent) {
    setDragId(null);
    const from = (e.active.data.current as any)?.col;
    const to = e.over?.id as string | undefined;
    if (!to || to === from) return;
    const id = Number(String(e.active.id).replace("job-", ""));
    if (from === "triage" && to === "queued") {
      queueJob.mutate(id);
    } else {
      toast.push("Stages advance at the Build level — open the Build to advance the plate", "info");
    }
  }

  const dragJob = jobs.find((j) => j.id === dragId);

  return (
    <>
      <PageHead title="Board"
        sub="live job flow — drag a triage card into Queued; everything else reflects real Build state" />
      {isLoading ? (
        <div className="kboard">{COLUMNS.map((c) => (
          <div className="kcol" key={c.key}><div className="kcol-head"><span className="kcol-title">{c.title}</span></div>
            <Skeleton h={64} style={{ marginTop: 10 }} /></div>
        ))}</div>
      ) : (
        <DndContext sensors={sensors} onDragStart={onStart} onDragEnd={onEnd}>
          <div className="kboard">
            {COLUMNS.map((c) => <Column key={c.key} col={c} jobs={byCol[c.key]} onQueue={(id) => queueJob.mutate(id)} />)}
          </div>
          <DragOverlay dropAnimation={null}>
            {dragJob ? (
              <div className={`kc prio-${dragJob.priority} drag dragging`}>
                <div className="kc-top">
                  <span className="kc-title">{dragJob.ticket_title}</span>
                  <span className="kc-proc">{dragJob.target_process}</span>
                </div>
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      )}
    </>
  );
}
