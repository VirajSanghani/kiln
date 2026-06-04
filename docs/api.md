# KILN — REST API (Phase 4)

FastAPI app (`api/app`), JSON over HTTP. Auth is JWT bearer; two roles
(`operator | requester`). Code: `api/app/routers/`, `deps.py`, `security.py`,
`serialize.py`. OpenAPI docs are served at `/docs`.

## Auth (minimal, real, no SSO)
- `POST /api/auth/login` `{username, password}` → `{access_token, token_type, user}`.
  Passwords are bcrypt-hashed; tokens are HS256 JWT (`sub`, `role`, `exp`).
- `GET /api/auth/me` → the current user.
- Send `Authorization: Bearer <token>` on every other call.
- Demo creds (seed): operators `rk`/`rk-pw`, `sam`/`sam-pw`; requesters `ana`/`ana-pw`,
  `ben`/`ben-pw`.

### Roles
- **requester**: submit tickets, upload versions, see **their own** tickets/jobs, their
  notification inbox.
- **operator**: everything — schedule, builds, transitions, inventory, all tickets.
- Cross-role access is refused: `401` (no/!bad token), `403` (wrong role or not your
  ticket), `404` (missing), `409` (illegal transition / state conflict).

## Endpoints

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | public | get a token |
| GET | `/api/auth/me` | any | current user |
| POST | `/api/tickets` | any | submit ticket + upload first FileVersion (multipart) |
| GET | `/api/tickets` | any | list (requester: own; operator: all) |
| GET | `/api/tickets/{id}` | owner/op | ticket + version chain + jobs |
| POST | `/api/tickets/{id}/files` | owner/op | add a FileVersion (re-submit) |
| POST | `/api/jobs/{id}/queue` | owner/op | submitted → queued (enter scheduling) |
| GET | `/api/jobs/{id}` | owner/op | job (derived status) |
| POST | `/api/jobs/{id}/reject` `/fail` `/cancel` | operator | per-Job terminal override (G1 #1) |
| GET | `/api/schedule` | operator | capability buckets + Build proposals |
| POST | `/api/schedule/confirm` `{printer_id, job_ids, note?}` | operator | materialize + start a Build |
| GET | `/api/builds` · `/api/builds/{id}` | operator | builds (detail incl. stage timeline) |
| POST | `/api/builds/{id}/advance` `{to_stage, note?}` | operator | one recipe step (Done fires `on_done`) |
| POST | `/api/builds/{id}/hold` `/resume` `/fail` `/cancel` | operator | side-transitions |
| GET | `/api/materials` · `/api/materials/{id}` | operator | shelf (+ warnings) |
| POST | `/api/materials` | operator | create (initial stock = a restock txn) |
| POST | `/api/materials/{id}/restock` `/adjust` `{delta, note?}` | operator | event-sourced txn |
| GET | `/api/inventory/warnings` | operator | the full warning set |
| GET | `/api/notifications` | any | own inbox |
| POST | `/api/notifications/{id}/read` | owner | mark read |

## Tickets, files & slicer parsing
`POST /api/tickets` is multipart: `title`, `target_process` (FDM/SLA/SLS/MJF), `priority`,
`material_pref?`, `deadline?` (ISO), `bbox_x/y/z?`, optional `slicer_summary` text, and the
`file` upload. It creates the Ticket, stores the blob (sha256 + size, local volume / S3
seam), parses estimates, and creates one Job in `submitted`.

**Slicer parsing** (`app/slicer.py`, parse-only — we never slice in-app): detects and parses
PrusaSlicer / Cura / Bambu Studio gcode summaries, plus a structured manual paste
(`time: 1h 48m` / `material: 22 g`). It tries the explicit `slicer_summary` first, then the
file's own text. Output (`est_time_seconds`, `est_material_qty` + unit) is always labelled
**"slicer est."** and is ~10–20% off — never implied as measured. Unknown formats leave
estimates null (the upload still succeeds). Cura reports filament as length (`m`); without a
density in the summary it is recorded as-is (documented limitation).

Re-submitting (`/files`) appends the next `version_no` and points `current_file_version` at
it. The Job pins the version that actually printed (`Job.file_version_id`, R3).

## Transitions
Every transition endpoint wraps a `stage_engine` op and **owns the transaction** — one
commit persists the StageEvent + the recomputed column (+ any `on_done` inventory txn).
Illegal transitions return `409` with the message from the engine (e.g.
`"... printing -> qc. Allowed from printing: ['support_removal']"`). `POST
/api/schedule/confirm` is the propose→**dispose** step: it creates the Build, schedules the
chosen Jobs, starts it (engine entry event), sets the printer `printing`, and emits
`started` notifications. Nothing auto-starts — this is an explicit operator action.

## Notifications (in-app only; email is a documented seam)
Generated on requester-relevant events: `started` (on confirm), `failed` (on Build/Job
fail or QC reject), `ready_for_pickup` (on Build Done, per delivered Job).

## Errors
`401` unauthenticated · `403` wrong role / not your resource · `404` missing · `409`
illegal transition or state conflict · `413` upload over the size cap.
