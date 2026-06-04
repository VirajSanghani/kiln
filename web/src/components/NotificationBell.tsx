import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, ago } from "../api";

// Surfaces the server-side notifications (started / failed / ready_for_pickup) that KILN
// generates on requester-relevant events. Polls live; click an item to mark read + jump.
export default function NotificationBell() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);

  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get("/notifications"),
    refetchInterval: 15000,
  });
  const items: any[] = data ?? [];
  const unread = items.filter((n) => !n.read).length;

  const read = useMutation({
    mutationFn: (id: number) => api.post(`/notifications/${id}/read`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  function openItem(n: any) {
    if (!n.read) read.mutate(n.id);
    if (n.ticket_id) nav(`/tickets/${n.ticket_id}`);
    setOpen(false);
  }

  const kindClass: Record<string, string> = {
    failed: "sev-critical", ready_for_pickup: "sev-info", started: "sev-warn", on_hold: "sev-warn",
  };

  return (
    <div className="bell">
      <button className="bell-btn" aria-label={`Notifications (${unread} unread)`} onClick={() => setOpen((o) => !o)}>
        inbox
        {unread > 0 && <span className="bell-badge">{unread}</span>}
      </button>
      {open && (
        <>
          <div className="bell-scrim" onClick={() => setOpen(false)} />
          <div className="bell-panel" role="menu">
            <div className="bell-head">Notifications</div>
            {items.length === 0 && <div className="empty" style={{ padding: "16px" }}>nothing yet</div>}
            {items.map((n) => (
              <button key={n.id} className={`bell-item ${n.read ? "read" : ""}`} onClick={() => openItem(n)}>
                <span className={`bell-kind ${kindClass[n.kind] ?? ""}`}>{n.kind.replace(/_/g, " ")}</span>
                <span className="bell-msg">{n.message}</span>
                <span className="bell-time">{ago(n.created_at)}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
