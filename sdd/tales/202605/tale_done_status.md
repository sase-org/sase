---
create_time: 2026-05-11 14:54:40
status: done
prompt: sdd/prompts/202605/tale_done_status.md
---
# Plan: Add `TALE DONE` agent status

## Goal

Introduce a new agent status, `TALE DONE`, that replaces `PLAN DONE` on a root plan workflow whose plan was approved as
a _tale_ (i.e. its earlier display status was `TALE APPROVED` / its `plan_action` is `"tale"`) and whose follow-up
children have all completed.

Today every approved-plan workflow whose follow-ups complete collapses to the generic `PLAN DONE`, regardless of which
approval path the user took. Other plan-action variants already get their own terminal display (`EPIC CREATED` after a
`.epic` follow-up). Tales — the most common "approve + run coder + commit plan to `sdd/tales/`" path — deserve their own
terminal label so the Agents tab and notifications can distinguish a finished tale from a finished generic plan.

## Product context

- The plan-action vocabulary the user sees is **Tale / Epic / Legend / Reject / Run** (see
  `src/sase/ace/tui/modals/approve_options_modal.py`). Tales are the default and write the plan to `sdd/tales/YYYYMM/`.
- During the active phase, tales already get their own display status `TALE APPROVED` (vs. `PLAN APPROVED` for generic
  approvals) — set in `_plan_enrichment_status()` and propagated to follow-up children in `apply_status_overrides()`.
- The terminal phase, however, currently has no tale-specific equivalent: a finished tale and a finished generic
  approval both read as `PLAN DONE`. This is asymmetric and makes Agents-tab status filters / status grouping less
  informative.
- Adding `TALE DONE` mirrors the existing terminal-state shape for epics (`EPIC CREATED`) and keeps the lifecycle pair
  coherent: `TALE APPROVED` → `TALE DONE` parallels `PLAN APPROVED` → `PLAN DONE`.

## Where the status transitions today

The current `DONE → PLAN DONE` rewrite lives in `src/sase/ace/tui/models/_agent_status_overrides.py` inside
`apply_status_overrides()` (the loop at the bottom of the file, currently lines ~222–232):

```python
for agent in agents:
    if (
        is_root_plan_workflow(agent)
        and agent.status == "DONE"
        and agent.raw_suffix in parents_with_followup
    ):
        completed_override = completed_followup_override.get(agent.raw_suffix)
        if completed_override == "EPIC CREATED":
            agent.status = "EPIC CREATED"
        else:
            agent.status = "PLAN DONE"
```

The same function already knows which root plan workflows were tales — `parent.plan_action == "tale"` (read from
`agent_meta.json` during enrichment) is exactly the condition used on lines ~161–165 to choose between `TALE APPROVED`
and `PLAN APPROVED` for the active follow-up override.

So the _trigger_ is already available; what is missing is the terminal branch.

## Design

Introduce `TALE DONE` as another `_TERMINAL_STATUSES` member with the same role in the lifecycle as `PLAN DONE`. The
decision point sits in the existing terminal override loop:

- If the root plan workflow's `plan_action == "tale"` (or its current status is `TALE APPROVED`, mirroring the dual
  condition used in the active-followup override for resilience), and no `.epic` overrode the completed follow-up to
  `EPIC CREATED`, set `TALE DONE` instead of `PLAN DONE`.
- All consumers that currently treat `PLAN DONE` as "post-plan handoff, finished" must also accept `TALE DONE`. The
  single source of truth for this category is the frozenset `_TERMINAL_STATUSES` in `src/sase/agent/status_buckets.py`;
  adding `TALE DONE` there is what propagates the "Done" status bucket, sort/anchor behavior, and dismissal
  classification across every consumer that reads from the frozenset.

`TALE DONE` is presentation-only and only ever materializes via `apply_status_overrides()` — the on-disk
`agent_meta.json` keeps storing the raw `DONE` status plus `plan_action: "tale"`. No new persisted field is required.

## Files to change

### Status enumeration / bucketing (single source of truth)

1. `src/sase/agent/status_buckets.py`
   - Add `"TALE DONE"` to `_TERMINAL_STATUSES`.
   - Update the explanatory comment on lines 41–44 ("`PLAN DONE`, `PLAN REJECTED`, and `EPIC CREATED` are post-plan
     handoff states…") to include `TALE DONE`.

### TUI status override (where the new status is produced)

2. `src/sase/ace/tui/models/_agent_status_overrides.py`
   - In the terminal override loop, branch on `agent.plan_action == "tale"` (or `agent.status` already coerced to
     `TALE APPROVED`) to produce `TALE DONE` in place of `PLAN DONE` when no `.epic` follow-up wins.
   - Update the docstring header on line ~52 to document the new transition:
     `DONE -> TALE DONE: tale plan workflow where all follow-ups completed`.

### Runtime anchor / planner-phase semantics

3. `src/sase/ace/tui/models/agent_time.py`
   - Add `"TALE DONE"` to `_PLAN_RUNTIME_TERMINAL_STATUSES` (line 12) so runtime anchoring matches `PLAN DONE`.
   - Add `agent.status == "TALE DONE"` alongside the `PLAN DONE` check in `_is_planner_phase_row()` (line 120) so the
     row's runtime ends at plan-submission time, exactly as it does for `PLAN DONE`.

### Row rendering / colors

4. `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
   - Add a rendering branch for `TALE DONE`. **Decision point:** use the same green as `PLAN DONE` (`#5FD75F`) —
     simplest, and matches the "all follow-ups done, generic-success" feel of `PLAN DONE`. The alternative is to reuse
     `TALE APPROVED`'s teal (`#00D7AF`) for consistency with the active phase, but that color is already strongly
     associated with "approved and running." Recommend the green to preserve "done = green" everywhere.

### Dismissal + revive paths (TUI)

5. `src/sase/ace/tui/actions/agents/_loading_helpers.py`
   - Add `"TALE DONE"` to `DISMISSABLE_STATUSES`.

6. `src/sase/ace/tui/actions/agents/_revive_artifacts.py`
   - Add `"TALE DONE"` next to `"PLAN DONE"` in both `_canonicalize_workflow_marker_status()` and
     `_canonicalize_step_marker_status()` (so it maps to `"completed"`).
   - Add `"TALE DONE"` to the `is_plan_like_status` set inside `_build_agent_meta_data()` so revived tale workflows
     still write `plan: True` into `agent_meta.json`.

7. `src/sase/ace/tui/actions/agents/_wait_resume.py`
   - The `PLAN DONE` branch at line 230 (used to resume the coder follow-up's chat) should also fire for `TALE DONE`.
     Either widen the condition to a frozenset of post-handoff statuses, or duplicate the branch — recommend the
     frozenset for symmetry with other consumers.

### Rust core (shared cleanup planner)

8. `../sase-core/crates/sase_core/src/agent_cleanup/planner.rs`
   - Add `"TALE DONE"` to the `DISMISSABLE_STATUSES` constant (line ~34) so the core cleanup planner agrees with the
     Python TUI side. Per the rust-core boundary rule in `memory/short/rust_core_backend_boundary.md`, dismissal
     classification is shared backend logic and must live in core.

9. `src/sase/core/agent_cleanup_wire.py`
   - Add `"TALE DONE"` to the mirror `DISMISSABLE_STATUSES` constant in the Python wire module so the two sides stay in
     sync.

## Tests

10. `tests/test_agent_loader_status_override_followups.py`
    - Add a `test_root_plan_workflow_tale_done_when_followups_completed` test mirroring the existing `PLAN DONE` cases
      (e.g. the one near line 271): build a DONE root `.plan` whose `plan_action == "tale"` and a DONE non-`.epic`
      follow-up; assert the override yields `TALE DONE`.
    - Add a regression test that a DONE `.plan` with `plan_action == "tale"` _plus_ a newest-completed `.epic` follow-up
      still yields `EPIC CREATED` (epic still wins, matching the existing precedence).
    - Add a regression test that a DONE `.plan` with no `plan_action` (or `plan_action != "tale"`) still yields
      `PLAN DONE` (i.e. we did not regress the generic path).

11. `tests/ace/tui/models/test_agent_groups_grouping_mode_status.py`
    - Add an assertion analogous to the existing `PLAN DONE → "Done"` case so the new status is covered by status-bucket
      grouping.

12. `tests/ace/tui/models/test_agent_panel_index.py`
    - Extend the local `_DISMISSABLE` set used in tests to include `"TALE DONE"`.

13. `tests/test_agent_revive.py`, `tests/test_agent_model_bundle.py`
    - Add `TALE DONE` to the parameterized canonicalization cases (currently include `("PLAN DONE", "completed")`).
    - Add a round-trip test fixture for a revived tale workflow whose status is `TALE DONE`.

14. Sibling Rust crate (`../sase-core`)
    - Extend the test that covers `DISMISSABLE_STATUSES` (if present) to include `TALE DONE`; otherwise add one.

## Decision points to flag during implementation

- **Color choice for `TALE DONE`**: green (recommended, matches `PLAN DONE`) vs. a tale-themed variant. Easy to change
  later.
- **Trigger condition**: use `agent.plan_action == "tale"` only, or also fall back to `agent.status == "TALE APPROVED"`?
  The active-followup override at lines 161–165 uses both. Recommend matching that pattern for resilience (a workflow
  whose meta was hand-edited but whose status is already `TALE APPROVED` should still finish as `TALE DONE`).
- **PNG snapshot updates**: `tests/ace/tui/visual/test_ace_png_snapshots.py` includes a fixture with
  `status="PLAN DONE"`. No new fixture is strictly required for `TALE DONE`, but consider adding one so the new
  color/style is locked in via the visual baseline.
- **Documentation**: `docs/ace.md` references `PLAN DONE`; update it to mention `TALE DONE` alongside the other terminal
  statuses.

## Non-goals

- No change to on-disk state. `agent_meta.json` continues to encode the lifecycle via `plan_action` + `plan_approved` +
  raw `DONE`; the new label is computed at TUI display time.
- No change to the plan-approval modal or to how tales are written into `sdd/tales/`. This is strictly a
  terminal-display addition.
- No new notification type. Existing follow-up-completion notifications already cover the moment a tale finishes;
  renaming the surfaced status is enough.
