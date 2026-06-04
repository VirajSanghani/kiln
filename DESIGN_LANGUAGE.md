# KILN — Design Language (machine-readable)
### "Quiet Utility" as explicit tokens the agent consumes — NOT prose to interpret
*This file exists because AI UI defaults to the statistical mean (shadcn-blue, Inter, rounded
card-in-card). A defined, machine-readable design language is the single biggest lever for
escaping that. Every dashboard/console surface is evaluated against THIS, not generic defaults.*

---

## 1. Design philosophy (the why, in one line)
**Quiet Utility** — an instrument, not an app. Restrained, precise, engineering-grade. The data
is the hero; chrome recedes. If a pixel doesn't carry information, remove it (Tufte data-ink).
Calm, legible, confident. Looks like a tool a serious lab would trust — closer to Linear/Vercel/
a lab instrument readout than to a consumer SaaS dashboard.

## 2. Color tokens (exact — do not improvise new colors)
```
--bg:        #1a1714   /* near-black warm base */
--panel:     #211d19   /* card/surface */
--panel-2:   #272219   /* raised/inset surface */
--line:      #39322a   /* hairline borders, dividers */
--ink:       #ece5da   /* primary text */
--stone:     #b8ada0   /* secondary text */
--stone-dim: #8a8073   /* tertiary text, labels, captions */
--amber:     #e0922f   /* SEMANTIC ONLY: active state, alert, the one accent */
--amber-dim: #a9701f   /* amber, recessed */
--green:     #7d9b6a   /* positive/healthy (success rate up, in-stock) */
--blue:      #6d8bab   /* neutral info / passive state */
--red:       #bf6b5a   /* failure / critical / shortfall */
```
**Color rules:**
- Amber is SEMANTIC, never decoration. It marks the active/important/alert thing on a screen.
  If everything is amber, nothing is. Most of the UI is stone/ink on near-black.
- Green/red/blue are STATUS colors only (trends, health, failure). Not theming.
- NO gradients anywhere. NO gradient text. NO color the data doesn't justify.

## 3. Typography (two families, opinionated)
```
Display / headings:  Fraunces (serif), weights 500–600. Section titles, the big metric numbers.
Data / UI / labels:  JetBrains Mono. All numbers, labels, table cells, captions, nav, badges.
```
**Type scale (8px-aligned, dashboard hierarchy):**
- Hero metric number: Fraunces 30–40px / 500
- Section title: Fraunces 22–26px / 600
- Card/metric label: JetBrains Mono 9.5–10.5px / uppercase / letter-spacing .14em / --stone-dim
- Body / table: JetBrains Mono 12–13px / --ink or --stone
- Caption / backing-query line: JetBrains Mono 10px / --stone-dim
**Rules:** never Inter or a system-default sans. Numbers are monospace (they align in columns and
read as instrument data). Labels are uppercase mono with tracking — the "instrument" tell.

## 4. Spacing & layout (8px grid)
- Spacing scale: multiples of 8 (4 allowed for tight inline). 8 / 16 / 24 / 32 / 48.
- Content blocks: ≥16–24px between groups. Section margins: generous (breathing room).
- White space is a feature: 20–40% negative space. Do not fill every pixel.
- Dashboard layout follows the F-pattern: **North-star metrics top-left / top band**
  (throughput, utilization, success rate), **trends in the middle**, **detail/tables at edges or
  below**. The golden triangle (top-left) holds the most important number.

## 5. Components
- **Cards:** 1px --line border, --panel fill, 3–4px radius (NOT pill-rounded), NO drop shadow,
  NO card-inside-card. Flat, bordered, calm.
- **Metric tile:** label (mono uppercase, dim) → big number (Fraunces) → context line
  (trend vs prior period / target) → backing-query caption (the ↳ honesty line).
- **Charts:** flat. NO 3D, NO shadows, NO dual-axis, NO gridline clutter. Minimal axes, direct
  labels where possible. A sparkline beats a chart-junk line chart. Sorted bars over pie.
- **Tables:** monospace, right-align numbers, hairline row separators (--line), generous row
  height, no zebra stripes unless density demands it.
- **Badges/pills:** small, mono, bordered or low-alpha fill. Status color carries meaning.

## 6. Motion
- Subtle and purposeful only. 120–200ms ease for state changes. NO bounce, NO elastic, NO
  spring, NO animate-everything. A value updating may fade; nothing should spring into view.

## 7. THE ANTI-SLOP BANNED LIST (these scream "AI made this" — forbidden)
- ✗ Purple/violet/cyan or Tailwind-blue gradients (or ANY gradient)
- ✗ Gradient or glowing text, especially on metrics
- ✗ Glassmorphism / frosted-blur panels
- ✗ Card-inside-card nesting; identical uniform card grids with no hierarchy
- ✗ Drop shadows on everything; heavy elevation
- ✗ Bounce / elastic / spring easing
- ✗ Inter, Roboto, or system-default sans as the type
- ✗ Everything pill-rounded (rounded-2xl on all the things)
- ✗ Emoji as icons; decorative stock icons that carry no info
- ✗ 3D charts, donut/pie with many slices, chartjunk, dual-axis
- ✗ Centered hero text with a big gradient CTA (consumer-landing-page energy)

## 8. The honesty-meets-design synergy (KILN-specific)
Good dashboard design says "a number alone answers nothing — frame it with comparison." KILN's
honesty rule says "every number traces to a real query." These REINFORCE: show each metric WITH
its trend-vs-prior-period (better design) AND its backing-query caption (honesty). The context
line and the ↳ query line together make each tile both more credible and more designed.

## 9. The reference vibe (name it, for the agent)
Linear's restraint. Vercel/Geist's mono-influenced precision. A Teenage Engineering device
readout. A lab instrument panel. Tufte's data-ink discipline. NOT: a generic SaaS admin template,
not a crypto dashboard, not a consumer fitness app.
