---
create_time: 2026-07-06 14:08:31
status: done
prompt: sdd/prompts/202607/root_agent_status_mirror.md
---
# Root agent entry status must mirror active/waiting child agent rows

## Problem

In the same screenshot that exposed the `%wait` countdown bug (queued family child `b--launch` behind parent `b`), the
root agent entry shows `DONE` while its child row shows `WAITING`. The root entry of an agent family/workflow group
should summarize what the group is actually doing:

1. If any child agent row is **running** — where "running" means any status that indicates an in-flight agent process,
   not just the literal `RUNNING` status — the root must show the status of the **most recently launched** running
   child.
2. Otherwise, if any child agent row is `WAITING`, the root must show the status of the **least recently launched**
   `WAITING` child (the next one due to run), **including its wait countdown** when the `%wait` directive's `time`
   keyword argument was used (same display the child row shows: static `+5m` hint while agent dependencies are pending,
   live countdown once the runner writes `wait_until`).
3. Only when there are no running and no `WAITING` child rows does today's behavior apply.

## Root cause

All root/child status reconciliation happens in `apply_status_overrides`
(`src/sase/ace/tui/models/_agent_status_apply.py`). Two gaps:

1. **Plain-agent family roots never mirror children at all.** The final "roots mirror the newest logical child" block is
   gated on `is_root_plan_workflow(parent)`. A plain agent root (e.g. `b`, launched via `sase run`, no
   `workflow_name`/`agent_family_role` meta) that later gains a family child via `%n(b, launch)` is skipped entirely, so
   the root keeps its own terminal status (`DONE`) while the queued child sits `WAITING` under it.
2. **The mirroring rule is "newest child verbatim", not activity-aware.** Even for plan-workflow roots,
   `max(children, key=child_launch_time)` can pick a terminal or paused child over an older sibling that is still
   running, and can pick the newest of several `WAITING` children instead of the next one due to run.

There is also a display gap: root rows have no way to render a wait countdown. The Agents-tab renderer
(`src/sase/ace/tui/widgets/_agent_list_render_agent.py`, `WAITING` branch), the shared helpers
(`src/sase/ace/tui/models/agent_time.py::wait_remaining_seconds` / `wait_countdown_ticks`), and the render cache key
(`src/sase/ace/tui/widgets/_agent_list_render_cache.py`) all read the row's _own_ `wait_until` / `wait_duration` /
`waiting_for` fields, which are empty on the root.

## Fix plan

### Phase 1 — shared "active status" semantics

Add to `src/sase/agent/status_buckets.py` an explicit frozenset (plus a small predicate) for statuses that indicate an
in-flight agent process, e.g. `ACTIVE_AGENT_STATUSES`: `STARTING`, `RUNNING`, `RETRYING`, `ANSWERED`, `WORKING PLAN`,
`WORKING TALE`, `EPIC APPROVED`, `LEGEND APPROVED`, `PLAN COMMITTED`.

Rationale for membership:

- `WORKING PLAN`/`WORKING TALE` and `EPIC APPROVED`/`LEGEND APPROVED`/`PLAN COMMITTED` are display statuses that
  `active_approved_plan_handoff_status` assigns only to children whose underlying status is `RUNNING`.
- The sticky `PLAN APPROVED`/`TALE APPROVED` planner statuses are deliberately **excluded**: they live on _finished_
  planner rows after handoff (their status bucket reads "Running" for query purposes, but the row's process is done).
  Including them would regress roots to `PLAN APPROVED` after the coder finishes with `PLAN DONE`.
- Paused-for-input statuses (`PLAN`, `QUESTION`, `WAITING INPUT`) and the literal `WAITING` are not "running".

This cannot reuse `status_bucket_for_values(...) == "Running"` because that bucket is a query-semantics catch-all (it
includes sticky approved statuses and unknown statuses).

### Phase 2 — activity-aware root mirroring in `apply_status_overrides`

Rework the final root-mirroring block in `src/sase/ace/tui/models/_agent_status_apply.py`:

1. **Widen the set of roots considered.** Iterate every `parent_by_suffix` root that has qualifying agent-child rows
   (the same `is_family_child` membership used today: family members plus main workflow agent steps) — not just
   `is_root_plan_workflow` roots. This brings plain-agent family roots (the observed bug) into the pass.
2. **Selection precedence** (replacing "newest child verbatim"):
   - _Running rule_: among qualifying children with an active status (Phase 1 set), pick the most recently launched
     (`child_launch_time`) and mirror its status verbatim (plus the same `custom_role_label` / `custom_role_done_label`
     / `copy_missing_display_metadata` copies the current code performs).
   - _Waiting rule_: otherwise, among children with status `WAITING`, pick the least recently launched; set the root's
     status to `WAITING` and record that child as the root's wait-display source (Phase 3).
   - _Fallback_: otherwise keep today's behavior exactly — plan-workflow roots mirror the newest child verbatim; other
     roots keep their own status. This keeps the existing planner-family semantics (root shows `PLAN`, `QUESTION`,
     `PLAN DONE`, `FEEDBACK`, sticky approvals, …) untouched whenever nothing is running or queued.
3. **The root's own run participates for plain-agent roots.** A plain agent root is itself a run (there is no synthetic
   child mirroring it, unlike plan-workflow roots). Treat the root's own status/launch time as one more candidate so:
   - parent `b` still `RUNNING` + queued `WAITING` child → root stays `RUNNING` (most recent running row);
   - parent `b` itself `WAITING` on its own `%wait` → root keeps its native countdown (no mirroring needed);
   - parent `b` `DONE` + queued child → waiting rule fires → root shows `WAITING` (the reported bug). For plan-workflow
     roots the root's own pre-mirroring status is workflow plumbing, not a run, and must _not_ be a candidate (every run
     phase already has a child row, including the synthetic planner child).

Sequential workflow semantics make the waiting rule safe for workflow roots: while any non-agent step (bash/python) is
executing, no qualifying agent child is `WAITING` at a barrier, and the fallback preserves the workflow's own status.

### Phase 3 — root wait-countdown display without polluting model fields

Copying `wait_until`/`wait_duration`/`waiting_for` onto the root `Agent` would leak into non-display consumers that read
those fields off the selected row (revive metadata in `src/sase/ace/tui/actions/agents/_revive_artifacts.py`, the
wait-edit modal defaults and optimistic updates in `src/sase/ace/tui/actions/agents/_wait_resume.py`, dedup merge in
`src/sase/ace/tui/models/_dedup.py`). Instead:

1. Add a runtime-only, non-persisted link on `Agent` (alongside `runtime_children` / `followup_agents`), e.g.
   `wait_display_source: Agent | None`. `apply_status_overrides` clears it at the start of each pass and sets it when
   the waiting rule selects a child. It is display-plumbing only: excluded from repro serialization
   (`src/sase/ace/tui/repro/`), dedup merge, and the wait-edit/revive flows, which keep operating on each row's own
   fields.
2. Add a tiny resolver in `src/sase/ace/tui/models/agent_time.py` (e.g. `wait_display_agent(agent)` returning
   `agent.wait_display_source or agent`) and route the countdown surfaces through it:
   - `wait_remaining_seconds` and `wait_countdown_ticks` evaluate the effective agent's `wait_until` / `wait_duration` /
     `waiting_for` / `start_time`, so the root inherits the approved countdown semantics from the previous fix (no
     fabricated countdown while agent dependencies are pending; ticking only when a real timer runs).
   - The renderer's `WAITING` branch in `src/sase/ace/tui/widgets/_agent_list_render_agent.py` reads the effective
     agent's wait fields for the static `+<duration>` hint and the `until <time>` label.
   - `wait_dependencies_satisfied` (used by `src/sase/ace/tui/widgets/_agent_list_build.py` to compute
     `wait_deps_satisfied` per row) evaluates the effective agent's `waiting_for` so the root's badge/countdown gating
     matches the child row's.
   - The detail header (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py`) resolves the same effective
     agent so a selected root shows the identical wait line as its mirrored child.
3. **Render-cache correctness** (`src/sase/ace/tui/widgets/_agent_list_render_cache.py`): the cache key's `wait_until` /
   `wait_duration` / `waiting_for` / `wait_deps_satisfied` components must come from the effective agent, otherwise the
   root row goes stale when the child transitions from the static `+5m` hint to a live countdown. Tick scheduling needs
   no new machinery: `row_runtime_or_wait_ticks` already recurses into `runtime_children`, and with
   `wait_countdown_ticks` resolving the effective agent, the root ticks exactly when its displayed countdown ticks and
   stays static otherwise (per the TUI perf rule against per-second invalidation of static rows).

## Tests

- `apply_status_overrides` unit coverage (new file or extend
  `tests/test_agent_loader_status_override_followup_roots.py`):
  - Plain-agent root `DONE` + queued `WAITING` family child → root `WAITING`, wait-display source set (the reported
    bug).
  - Plain-agent root `DONE` + one `RUNNING` child + one `WAITING` child → root `RUNNING` (running beats waiting).
  - Two running children → root mirrors the most recently launched one.
  - Two `WAITING` children, none running → root mirrors the least recently launched one.
  - Plain-agent root still `RUNNING` + queued `WAITING` child → root stays `RUNNING`.
  - Plain-agent root `DONE` + only terminal children → root keeps `DONE` (fallback, no behavior change).
  - Plan-family regression guard: sticky `PLAN APPROVED` planner + `PLAN DONE` coder → root `PLAN DONE` (sticky
    approvals are not "running").
  - Existing plan-root mirroring tests stay green unchanged (fallback preserves them).
- `agent_time` unit tests: `wait_remaining_seconds` / `wait_countdown_ticks` on a root with a wait-display source mirror
  the child in all three approved states (pending deps + duration → `None`/no tick; `wait_until` set → countdown/tick;
  duration-only child → start-anchored countdown).
- Row-render tests (extend the existing `WAITING` row coverage): a root mirroring a waiting child renders `WAITING +5m`
  statically while the child's deps are pending, switches to the live countdown once the child's `wait_until` exists,
  and the render-cache key changes across that transition.
- Detail-header test: selected root with a wait-display source renders the same wait line as the child.

## Notes

- **Rust core boundary**: root-status mirroring and countdown rendering are Agents-tab presentation logic that already
  lives in this repo's Python (`apply_status_overrides`, `agent_time`, list renderer). No `sase-core` wire/API changes.
- **TUI perf**: no new refresh paths; the change rides the existing render-cache key + tick predicates. The only new
  per-refresh work is one linear scan over each root's children inside the existing `apply_status_overrides` pass.
- Status-bucket _counts_ (banner tallies, queries) intentionally follow the new root status (a root summarizing a
  waiting group counts as Waiting, not Done) — this is the point of the fix.
- The `wait_deps_satisfied` heuristic remains display-only and optimistic, as pinned in the previous fix; this change
  only redirects which row's fields feed it for root entries.
