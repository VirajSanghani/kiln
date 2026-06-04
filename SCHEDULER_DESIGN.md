# KILN — Scheduler Design
### The centerpiece: how work gets ordered and assembled onto Builds
*This is the part a lab lead will probe. It is deliberately EXPLICIT POLICY, not an opaque
optimizer — because in a real lab, a defensible, legible policy beats a clever black box.*

---

## 1. Why this is its own document
Ordering print work is the genuinely hard, judgment-laden core of lab ops. A single "sort by
priority" line hides every real decision: which machine can even run this job, what happens when
a long job and a short job want the same printer, whether a "urgent" job interrupts a running
print, and whether to batch jobs to save material swaps. KILN makes each of these an explicit,
stated policy the operator can understand and trust.

## 2. The scheduler's job, precisely
Given: the set of **Queued** Jobs, the set of **Printers** (each with a process + capabilities +
current status + loaded material), and the material inventory — produce:
1. an **ordered queue per capability bucket**, and
2. proposed **Builds** (groupings of compatible Jobs) ready for an operator to confirm and start.
The scheduler **proposes**; the operator **disposes**. It never auto-starts a physical machine
(that would require telemetry we refuse to fake). It recommends; a human confirms.

## 3. Capability buckets (not one global queue)
A Job can only run where it physically can. The scheduler partitions the queue by **capability
match**, not just by process:
- Process match (an SLA job can't run on an FDM printer).
- Material capability (PA12-CF only on an enclosed printer; flexible TPU only on a direct-drive).
- Build-volume fit (part bbox ≤ printer build volume).
- Loaded-material match OR an explicit "swap acceptable" flag.
Result: each printer (or class of identical printers) has its own ordered sub-queue. A Job may be
eligible for several buckets; it appears in each until scheduled.

## 4. Ordering policy (within a bucket) — EXPLICIT and DEFENSIBLE
Jobs are ordered by a documented lexicographic key:
1. **Priority** (operator-set: Critical > High > Normal > Low).
2. **Deadline** (earlier first; jobs with no deadline sort after dated ones at equal priority).
3. **Age** (older submission first — fairness tie-break, prevents starvation).
4. **Stable tie-break:** Job id (deterministic, reproducible ordering).
This is a *policy*, not an optimization. It is legible: an operator can always answer "why is
this job next?" — which is worth more than a marginally higher throughput from an opaque solver.

### 4.1 Anti-starvation note
Strict priority can starve Low jobs forever. Mitigation: an **age boost** — a Job's effective
priority rises one tier after a configurable wait (e.g. 72h Queued). Documented, toggleable, and
visible in the UI ("boosted: waited 3 days"). Honest and simple.

## 5. No preemption (a running print is sacred)
A Build that is **Printing** is never interrupted by the scheduler, regardless of an incoming
Critical job. Reasons: aborting a multi-hour print wastes material + machine time and usually
can't be cleanly resumed. A Critical job instead jumps to the **front of the next-up queue** for
the first eligible printer. The only thing that stops a running print is a human (failure, manual
cancel). This is stated plainly as policy.

## 6. Build assembly (the batching lever)
When multiple Queued Jobs share a capability bucket AND are compatible, the scheduler can propose
grouping them onto one **Build**:
- **Compatibility:** same process, same (or swap-compatible) material, fit together within the
  build volume/plate area (simple bin-fit by bbox footprint — not a true 3D nester in v1; a
  first-fit-by-area heuristic, documented as such).
- **Batching toggle (operator-controlled):** OFF = strict order, one Job per Build (simplest,
  most fair). ON = group same-material Jobs to cut spool/resin swaps and fill chambers (higher
  throughput, especially SLS/MJF where you WANT a full powder bed). The tradeoff (fairness/latency
  vs. throughput/material efficiency) is written into the UI so the operator chooses knowingly.
- **SLS/MJF default:** batching leans ON — a half-empty powder bed wastes the run; nesting many
  parts is the economical norm. Stated as a per-process default the operator can override.

### 6.1 Honest limit on nesting
v1 does NOT do true 3D part nesting/orientation packing (that's a hard geometry problem and edges
into VARA's optimization territory). It does first-fit-by-footprint-area with a fill-% cap, and
SAYS so. A real 3D nester is a documented future seam.

## 7. Material awareness (informs, never blocks)
When proposing a Build, the scheduler computes projected consumption (sum of Jobs' slicer
estimates) and annotates: "fits stock" / "will run PETG short by 12g — flagged." It will still
propose and allow the Build — the operator may have a spool arriving, or will swap. Never a
hard block. Low-material printers are de-prioritized in proposals but not excluded.

## 8. What the operator sees
- Each printer/bucket with its ordered next-up list and the *reason* the top job is first.
- Proposed Builds (with their Jobs, projected material, fit %, any shortfall flag) to **Confirm
  & start** or **edit** (add/remove Jobs) or **dismiss**.
- A batching toggle per process with the tradeoff stated.
- Boosted/starved jobs clearly marked.

## 9. Testing the scheduler (Phase 3 gates)
- Capability partition: a Job lands only in buckets it can physically run in.
- Ordering: priority > deadline > age > id, with the age-boost firing at threshold.
- No-preemption: a Critical arrival never interrupts a Printing Build; it goes next-up.
- Build assembly: compatible Jobs group; incompatible (material/volume) do not; fill-% cap holds.
- Material annotation: shortfall is flagged but the Build is still proposable.
- Determinism: same inputs → same proposed order (the id tie-break guarantees it).

## 10. Why this design is the right answer for the role
It demonstrates operations judgment a robotics lab actually values: knowing that legibility beats
cleverness, that running prints are sacred, that batching is a real throughput lever with a real
fairness cost, and that the system should propose while a human disposes. It is honest about its
limits (no 3D nesting, no telemetry, estimates are slicer-grade) — which is exactly the engineering
maturity the whole portfolio is meant to show.
