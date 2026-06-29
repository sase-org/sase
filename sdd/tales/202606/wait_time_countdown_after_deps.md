---
create_time: 2026-06-29 09:23:12
status: done
prompt: sdd/prompts/202606/wait_time_countdown_after_deps.md
---
# Plan: `%wait` relative-time countdown must start only after agent dependencies complete

## Problem / product context

When a `%wait` is configured with both **agent-name dependencies** and a **relative `time=` duration** (e.g.
`%wait:other_agent %wait(time=30m)`, or the equivalent `#fork:other_agent #t:30m`, which expands to `%wait(time=30m)`),
the relative duration's countdown begins the moment the agent enters the `WAITING` state — _before_ the agents it
depends on have completed.

The intended behavior: the relative-time countdown should not begin until **all** of the waited-for agents have
completed. A 30m relative wait should mean "wait for the dependencies, then wait 30 more minutes".

The screenshot symptom: an agent waiting for `other_agent` (still `WAITING`) plus `30m` shows `+ 30m (29m13s left)` —
the duration is already ticking down from the wait's start even though the dependency has not finished.

This affects two relative-time entry points, which both fold into the same `wait_duration` value:

- `%wait(time=<duration>)` used in the same directive as agent names, and
- a separate `%wait(time=<duration>)` directive alongside a `%wait:<agent>` directive.
- `#t:<duration>` (expands to `%wait(time=<duration>)`).

**Out of scope (intentionally unchanged):** absolute-time waits (`%wait(time=1430)` / `#t:1430`, stored as
`wait_until`). An absolute wall-clock target is meaningful regardless of dependency state, so its countdown continues to
run while dependencies are pending. The user's report is specifically about the _relative_ time case. The directive
layer already forbids combining a relative duration and an absolute time in one wait, so the two never coexist.

## Root cause

The relative duration is modeled as a **floor measured from the start of the wait**, and the TUI anchors the duration
countdown at the wait's start time. Concretely:

1. **Execution.** In the dependency-wait code path, the agent polls for the dependency-ready signal while accumulating
   total elapsed wait time, then "tops up" only the remainder of the duration beyond that elapsed time. So the duration
   is counted from the _start_ of the wait (overlapping the dependency wait), not from the moment dependencies finish.
   If dependencies take longer than the duration, no extra time is added at all.

2. **Display.** Both the details panel and the agent-row renderer compute the duration countdown as
   `start_time + wait_duration - now`. Because `start_time` is the moment the agent began waiting, the countdown ticks
   immediately, regardless of whether the dependencies have completed.

The pieces involved:

- Directive parsing folds `time=<relative>` into a single `wait_duration` (seconds); agent names go into the wait list.
  (No change needed here — parsing is correct.)
- The runner passes `wait_names` + `duration` into the pre-run wait helper.
- The wait helper writes the wait marker, polls for the dependency-ready signal (written by the dependency-resolution
  chop when all named dependencies have completed), then applies the time floor.
- The TUI enriches agents from the wait marker into `waiting_for` / `wait_duration` / `wait_until` fields and renders
  the countdown.

## Design of the fix

Keep the **dependency-resolution signal as the single source of truth for "deps are done"**, and make the relative
duration begin counting from that point. Reuse the already-correct absolute-time (`wait_until`) machinery instead of
inventing a new persisted field, so no new wire/marker schema field is required.

### A. Execution: count the duration from dependency completion

In the dependency-wait code path of the pre-run wait helper, after the dependency-ready signal is observed (all named
dependencies complete):

- If a relative `duration` is set (and positive): compute an absolute deadline of `now + duration` at that moment,
  persist it into the wait marker as `wait_until`, and sleep until that deadline using the existing absolute-time wait
  loop.
- This replaces today's "floor from start" logic (`remaining = duration - elapsed`) with "full duration after
  dependencies finish". It also unifies the duration-floor and absolute-time-floor blocks into one post-dependency floor
  (they are mutually exclusive at the directive layer).
- Persisting the derived deadline into the wait marker is what lets the TUI show a countdown that only starts once
  dependencies finish (see B). The marker rewrite refreshes the artifact index like the other marker mutations in this
  path.
- Preserve the existing zero-duration fast path (no rewrite, no sleep) so current behavior/tests for an
  immediately-satisfiable wait are unchanged.
- Preserve all kill-handling, completion-recording, and marker-cleanup behavior already present in this path. The
  dependency-only and duration-only (no agent names) paths are left unchanged.

Net effect: a relative duration alongside agent dependencies waits for **all** dependencies first, then waits the
**full** duration.

### B. Display: do not show a live relative-time countdown while dependencies are pending

In both the details-panel header and the agent-row renderer, gate the relative-duration countdown so it renders only
when there is no pending agent dependency — i.e. show the live `(… left)` / `(…)` countdown for a relative duration only
when the waited-for-agents list is empty.

- While dependencies are still pending, the wait marker has agent dependencies and a relative `wait_duration` but no
  `wait_until`; the panel still shows the static `+ <duration>` label (so the user sees the planned duration) but **no**
  ticking countdown.
- Once dependencies finish, the execution layer has written `wait_until` (the post-dependency deadline) into the marker;
  the existing `wait_until` countdown path then renders the correct countdown that started at dependency completion.
  (The `wait_until` branch already takes precedence over the duration branch in both renderers, so no double-rendering.)
- A pure relative-duration wait with no agent dependencies is unchanged: it still shows a live countdown immediately,
  which is correct because there is nothing to wait on first.

This keeps the two display surfaces consistent by deriving "has the countdown started?" from backend marker state rather
than re-deriving dependency status per surface.

## Files in scope

- Execution: the pre-run dependency/time wait helper in the `axe` runner (the function that writes the wait marker,
  polls for the ready signal, and applies the time floor).
- Display: the prompt-panel header builder and the agent-row renderer (the two places that compute the relative-duration
  countdown).
- Tests under the existing wait/enrichment/render test suites (see below).
- Docstring of the wait helper, updated to describe the new "duration starts after dependencies complete" semantics.

## Test plan

- **Execution (wait helper):**
  - When dependencies are satisfied and a positive relative duration is set, the wait marker is rewritten to include a
    `wait_until` deadline before cleanup, and the agent sleeps for the full duration _after_ the ready signal (not
    floored by dependency-wait elapsed time). Drive determinism by controlling the clock, the ready-signal polling, and
    `sleep`.
  - When dependencies take longer than the duration, the full duration is still observed afterward (the core semantic
    change) — i.e. the duration is not consumed by the dependency wait.
  - The existing zero-duration / immediately-ready cases still take the fast path with no extra marker rewrite (preserve
    current index-update expectations).
  - Existing kill / completion-recording / cleanup tests continue to pass.
- **Display:**
  - An agent with pending agent dependencies + a relative `wait_duration` and no `wait_until` renders the static
    `+ <duration>` label but **no** live countdown — in both the details header and the agent row.
  - The same agent, once `wait_until` is present (post-dependency), renders the countdown via the absolute-time path.
  - A pure relative-duration wait (no dependencies) still renders a live countdown (regression guard).
- **Parsing (unchanged) regression:** confirm `%wait:<agent> %wait(time=30m)`, `%wait(time=30m) %wait:<agent>`, and
  `#t:30m` + `#fork`/`%wait:<agent>` all still produce `wait_names=[…]` + `wait_duration` as before.

## Backend-boundary note

The wait execution and the TUI countdown currently live in this repo's Python code; the agent-scan wire is a documented
Python/Rust boundary contract. This fix deliberately reuses the existing `wait_until` / `wait_duration` /
waited-for-agents marker fields and adds **no** new wire field, so it requires no change to the sibling Rust core. The
new semantics ("relative duration begins at dependency completion") should be preserved if/when this wait/scan logic is
migrated to the Rust core.

## Risks / edge cases

- Multiple agent dependencies: the ready signal is written only when _all_ named dependencies complete, so the duration
  correctly starts after the last one — no change needed beyond A.
- Live wait-editing from the TUI rewrites the wait marker directly; it remains compatible because the display gating
  keys off marker fields and the chop continues to drive the ready signal. (No behavior change intended for that path in
  this plan.)
- The derived deadline is computed at the moment the ready signal is observed (within one poll interval of actual
  dependency completion); the sub-poll-interval skew is negligible and consistent with existing absolute-time waits.
