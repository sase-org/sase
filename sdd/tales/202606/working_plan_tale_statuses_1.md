---
create_time: 2026-06-21 11:38:34
status: done
prompt: sdd/prompts/202606/working_plan_tale_statuses_1.md
---
# Plan: `WORKING PLAN` / `WORKING TALE` statuses for code agents

## Goal

Make the post-approval lifecycle on the Agents tab legible by splitting it across two rows with two distinct, sticky
statuses:

- **Plan/root agent** keeps a **sticky** `PLAN APPROVED` / `TALE APPROVED` status from the instant the plan is approved,
  all the way through the few-second gap before the coder renders and while the coder runs, until the workflow
  terminally finishes (`PLAN DONE` / `TALE DONE`). This mirrors how `ANSWERED` sticks after a question is answered.
- **Coder ("code") child agent** shows a **new** `WORKING PLAN` / `WORKING TALE` status while it actively implements the
  approved plan, instead of inheriting the planner's `PLAN APPROVED` / `TALE APPROVED` label.

And give all four statuses **distinct-but-similar colors** (today `PLAN APPROVED` and `TALE APPROVED` render in the
_same_ teal `#00D7AF`, so they are indistinguishable).

### Why

When a user approves a plan, the coder agent takes a few seconds to start and render. In that gap there is nothing
obviously "in progress," and even once the coder runs, the planner row and the coder row both read `PLAN APPROVED` in
identical teal — so the user cannot tell "the plan is approved and I'm waiting" from "the coder is actively working."
Splitting the lifecycle into a sticky approved-state on the planner and a distinct working-state on the coder, with
separable colors, makes the state of an approved plan unambiguous at a glance.

## Design decision (please confirm at review)

This plan implements the two-row model that the Q&A answers point to:

| Row                         | Status text                       | Meaning                                                                                                 |
| --------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Plan/root agent (`.plan`)   | `PLAN APPROVED` / `TALE APPROVED` | Plan approved; sticky from approval onward (the state the user watches for during the coder-start gap). |
| Coder child agent (`.code`) | `WORKING PLAN` / `WORKING TALE`   | Coder actively implementing the approved plan.                                                          |

Lifecycle on the planner/root row is unchanged in shape — `PLAN` → `PLAN APPROVED` / `TALE APPROVED` → `PLAN DONE` /
`TALE DONE` — but the approved state is made reliably sticky. The coder child's _running_ label changes from
`PLAN APPROVED` / `TALE APPROVED` to `WORKING PLAN` / `WORKING TALE`.

This satisfies all four answered requirements: the planner keeps a sticky approved status through the gap (Q1); the new
working text lives on the code agent (Q2 + the request title "WORKING TALE/PLAN statuses for 'code' agents"); both pairs
get distinct-but-similar colors (Q3).

## Scope / boundary

Agent status display is computed **entirely in Python presentation code** — the Rust core (`sase_core_rs`) only scans
marker files (`plan_approved`, `plan_action`, etc.) and never produces these display strings. So **no `sase-core`
changes are required**; all work is in this repo's TUI/presentation layer. (Per the Rust-core boundary rule, this stays
Python because there is no shared backend status enum to extend — status strings are derived locally from already-shared
marker fields.)

Status colors are hardcoded in the render sites (not in `default_config.yml`), so no config changes are needed either.

## Where the behavior lives today

- **Coder running label.** `active_approved_plan_handoff_status(parent, child)` in
  `src/sase/ace/tui/models/_agent_status_family.py` returns `TALE APPROVED` / `PLAN APPROVED` for a _running coder
  child_; it is applied in `src/sase/ace/tui/models/_agent_status_apply.py` (the "active family code handoff" loop) so
  the coder child shows the approved label.
- **Root mirroring.** Immediately after, `_agent_status_apply.py` mirrors each family root to its newest child verbatim
  (`parent.status = newest.status`). This is why both the planner and coder currently read `PLAN APPROVED`.
- **Optimistic sticky override on approval.** When the plan-approval notification is consumed,
  `src/sase/ace/tui/actions/agents/_notification_status_overrides.py` sets
  `_agent_status_overrides[root.identity] = "PLAN APPROVED" / "TALE APPROVED"`, persists a `plan_approved` marker, and
  the override is re-applied each load in `src/sase/ace/tui/actions/agents/_loading_finalize.py` until
  `should_clear_loaded_agent_status_override(...)` decides the fresh loader state has overtaken it. This is the existing
  `ANSWERED`-style sticky mechanism.
- **Plan-marker enrichment.** `plan_enrichment_status(...)` in
  `src/sase/ace/tui/models/_loaders/_meta_enrichment_common.py` maps the persisted `plan_approved` + `plan_action`
  markers to `PLAN APPROVED` / `TALE APPROVED` on reload.
- **Rendering + colors (3 sites).**
  - `src/sase/ace/tui/widgets/_agent_list_render_agent.py` (the Agents-tab rows; both approved statuses currently
    `bold #00D7AF`).
  - `src/sase/ace/tui/widgets/prompt_panel/_workflow_render.py` (detail panel; `#00D7AF`).
  - `src/sase/ace/tui/modals/zoom_panel_modal.py` (zoom modal; both `bold #FFD787`).
- **Classification sets** that group `PLAN APPROVED` / `TALE APPROVED` as "active in-progress" for various behaviors
  (see the audit list below).

## Implementation plan

### 1. Introduce the new status strings on the coder child

- In `_agent_status_family.py`, change `active_approved_plan_handoff_status(...)` so a _running coder child_ resolves to
  `WORKING TALE` (tale lineage) / `WORKING PLAN` (otherwise) instead of `TALE APPROVED` / `PLAN APPROVED`. The
  tale-vs-plan detection (parent/child `plan_action == "tale"` or parent status in the TALE set) is unchanged.

### 2. Keep the planner/root row at the approved status

- In the root-mirroring loop in `_agent_status_apply.py`, when the newest child's status is `WORKING PLAN` /
  `WORKING TALE`, set the **root** to `PLAN APPROVED` / `TALE APPROVED` rather than mirroring the working label
  verbatim. (A small status-translation map for the mirror step, applied only at the root.) This keeps the planner row
  reading the sticky approved status while the coder child reads the working status.
- The existing optimistic override on the root stays `PLAN APPROVED` / `TALE APPROVED` (no change to
  `_notification_status_overrides.py` / `_notification_modals.py`), so the gap before the coder renders is already
  covered and now provably consistent with the post-render mirror result. Verify
  `should_clear_loaded_agent_status_override(...)` still clears the root override correctly when the handoff completes
  (root → `PLAN DONE` / `TALE DONE`); the working statuses are never used as overrides.

### 3. Colors — distinct but similar (all three render sites)

Recommended palette (a learnable 2×2: `PLAN`=green-leaning, `TALE`=cyan-leaning; `APPROVED`=bright, `WORKING`=one step
deeper). Final hexes are easily adjustable at review.

Agents-tab list (`_agent_list_render_agent.py`) and workflow panel (`_workflow_render.py`):

| Status          | Hex       | Note                                          |
| --------------- | --------- | --------------------------------------------- |
| `PLAN APPROVED` | `#00D7AF` | unchanged teal (green-leaning)                |
| `TALE APPROVED` | `#00D7D7` | turquoise/cyan sibling — distinct but similar |
| `WORKING PLAN`  | `#00AF87` | deeper teal, sibling of `PLAN APPROVED`       |
| `WORKING TALE`  | `#00AFAF` | deeper cyan, sibling of `TALE APPROVED`       |

Zoom modal (`zoom_panel_modal.py`) keeps its gold family but splits each pair the same way, e.g. `PLAN APPROVED`
`#FFD787`, `TALE APPROVED` `#FFD7AF`, `WORKING PLAN` `#FFAF87`, `WORKING TALE` `#FFAFAF`.

None of the proposed hexes collide with existing palette entries (RUNNING `#FFD700`, ANSWERED `#5FD7FF`, EPIC `#5FD7AF`,
DONE `#5FD75F`, PLAN `#FF87AF`, LEGEND `#D7AFFF`, WAITING `#AF87FF`, STOPPED `#8787AF`, STARTING `#87D7FF`).

Add explicit render branches for `WORKING PLAN` / `WORKING TALE` in all three sites (otherwise they fall through to the
`dim` default). Split the `PLAN APPROVED` / `TALE APPROVED` branches so each gets its own color.

### 4. Register the new statuses in the "active status" classification sets

`WORKING PLAN` / `WORKING TALE` are the coder's running state, so wherever `PLAN APPROVED` / `TALE APPROVED` is treated
as "actively in progress" for a coder row, the new statuses must behave the same. Audit each site below and add the new
statuses where the semantics apply to the running coder row (most do); leave planner-only sites keyed on the approved
statuses:

- `src/sase/agent/status_buckets.py` — `status_bucket_for_values` "Running" set (add). Re-evaluate
  `_NEEDS_INPUT_STATUSES`: today the coder-running `PLAN APPROVED`/`TALE APPROVED` are members; decide whether the
  working coder row should still match `needs:input` (recommend preserving prior behavior by adding the working
  statuses).
- `src/sase/ace/tui/models/agent_time.py` — `_SEGMENTED_FOLLOWUP_RUNTIME_STATUSES` (this set is specifically the coder
  follow-up runtime; the working statuses belong here — confirm against its usage whether to also keep the approved ones
  for the root).
- `src/sase/ace/tui/actions/_event_refresh.py` — active-refresh status list (add, so coder rows keep refreshing).
- `src/sase/ace/tui/actions/agents/_loading_helpers.py` — `_QUESTION_OVERRIDE_PROGRESS_STATUSES` (add).
- `src/sase/ace/tui/models/_loaders/_workflow_loaders.py` — active workflow statuses (add).
- `src/sase/ace/tui/commands/availability.py` — command availability set (add).
- `src/sase/ace/tui/widgets/agent_detail.py` — detail panel active set (add).
- `src/sase/ace/tui/widgets/_keybinding_bindings.py` — conditional keybinding set (add).
- `src/sase/ace/tui/widgets/file_panel/_diff.py` — active-diff status set (add).
- `src/sase/integrations/_mobile_agent_summary.py` — mobile "active" summary set (add).
- `src/sase/ace/tui/actions/agents/_approve.py` — approve-availability set (review/add).
- `src/sase/ace/tui/actions/proposal_rebase.py` — rebase-availability set (review/add).
- `src/sase/ace/tui/models/_dedup.py` — status-merge preference (the working statuses are non-`RUNNING`, so the existing
  "prefer non-RUNNING" merge keeps them; update the comment / verify the merge ordering).
- `src/sase/ace/tui/actions/agents/_revive_artifacts.py` — when reviving from a displayed status, map `WORKING TALE` →
  `plan_action="tale"` and `WORKING PLAN` / `WORKING TALE` → `plan_approved=True`, paralleling the existing
  `PLAN APPROVED` / `TALE APPROVED` handling, so a revived coder row reconstructs correct markers.

(The `_notification_modals.py` / `_notification_status_overrides.py` approval paths set the **root** status and
intentionally stay `PLAN APPROVED` / `TALE APPROVED` — no change.)

A single source-of-truth constant (e.g. a `WORKING_PLAN_STATUSES` / approved-status frozenset in `status_buckets.py` or
a shared status module) is preferable to scattering new literals; where a shared set already exists, extend it rather
than duplicating.

### 5. Tests

- Unit: `active_approved_plan_handoff_status` returns the working statuses for a running coder child (plan and tale
  lineages); the root-mirror translation yields `PLAN APPROVED` / `TALE APPROVED` on the root while the child shows
  `WORKING PLAN` / `WORKING TALE`.
- Unit: `status_bucket_for_values` buckets the working statuses as "Running"; updated classification sets include them.
- Existing status-override tests (`tests/test_agent_loader_status_override_*.py`) still pass — the gap behavior (sticky
  `PLAN APPROVED` / `TALE APPROVED` on the root before the coder renders) is unchanged; add a case asserting the root
  stays approved while the coder child reads working.
- Revive: a coder row displayed as `WORKING TALE` round-trips to `plan_action="tale"` / `plan_approved=True`.
- Visual: extend the ACE PNG snapshot suite (`tests/ace/tui/visual/test_ace_png_snapshots_agents.py`) with rows in each
  of the four statuses to lock in the distinct colors; regenerate goldens with `--sase-update-visual-snapshots`.

### 6. Validation

- `just install` then `just check` (lint + mypy + tests), plus `just test-visual` for the PNG snapshots.
- Manual smoke in `sase ace`: approve a standard plan and a tale plan, confirm the root shows sticky `PLAN APPROVED` /
  `TALE APPROVED` (including during the coder-start gap) and the revealed coder child shows `WORKING PLAN` /
  `WORKING TALE`, each in its own color.

## Out of scope

- Epic/legend approved statuses and their colors (unchanged).
- Any Rust core / `sase_core_rs` changes (status strings are Python-only).
- Renaming or re-coloring unrelated statuses.

## Open question for the reviewer

The two-row mapping (planner = sticky `PLAN APPROVED` / `TALE APPROVED`; coder = new `WORKING PLAN` / `WORKING TALE`) is
the reading that satisfies every answered requirement, but if instead the intent is for the **planner/root row itself**
to display `WORKING PLAN` / `WORKING TALE` during the coder-start gap, that is a small variant (swap which row carries
which label in steps 1–2) — flag it and I'll adjust.
