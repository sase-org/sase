---
create_time: 2026-06-22 08:35:48
status: done
prompt: sdd/prompts/202606/fix_working_status_invariants.md
---
# Plan: Restore plan-child / root status invariants after `WORKING PLAN` / `WORKING TALE`

## Problem

The recent `WORKING PLAN` / `WORKING TALE` work (plan `sdd/tales/202606/working_plan_tale_statuses_1.md`) broke two
status invariants on the Agents tab for plan-chain agent families. On the `03e.cdx.f1` family (tale-approved plan with a
running coder), the rows currently read:

| Row                 | Current (wrong) | Desired             |
| ------------------- | --------------- | ------------------- |
| `03e.cdx.f1` (root) | `TALE APPROVED` | **`WORKING TALE`**  |
| `03e.cdx.f1--plan`  | `DONE`          | **`TALE APPROVED`** |
| `03e.cdx.f1--code`  | `WORKING TALE`  | `WORKING TALE` (ok) |

The two invariants that must hold:

1. **Plan child rows are sticky-approved.** Once a plan is approved, the `…--plan` (planner) child row shows
   `TALE APPROVED` / `PLAN APPROVED` and keeps that status forever after (through the coder run and after the workflow
   finishes).
2. **Root rows mirror their most-recently-run child verbatim.** The family root row always shows the exact status of its
   newest child. While the coder runs that child is `WORKING TALE`, so the root reads `WORKING TALE`; before the coder
   starts the newest child is the planner (`TALE APPROVED`); after the coder finishes it is the coder (`TALE DONE`).

## Root-cause diagnosis

Status display for these rows is computed entirely in Python presentation code (no `sase-core` involvement — the Rust
core only scans marker files such as `plan_approved` / `plan_action`).

### Invariant 2 (root must mirror verbatim) — two causes

- **Cause 2a — translation in the root-mirror loop.** In `src/sase/ace/tui/models/_agent_status_apply.py`, the
  agent-family root-mirroring loop sets
  `parent.status = WORKING_PLAN_STATUS_TO_APPROVED.get(newest.status, newest.status)`. That map translates the newest
  child's `WORKING TALE` / `WORKING PLAN` back into `TALE APPROVED` / `PLAN APPROVED` on the root. This line was changed
  from the original `parent.status = newest.status` by the `WORKING` commit specifically to keep the root on the
  approved label — which is exactly the behavior the user now wants reversed.

- **Cause 2b — optimistic approval override pins the root.** When a plan is approved, an in-memory override
  (`_agent_status_overrides[root.identity] = "TALE APPROVED" / "PLAN APPROVED"`) is set (`_notification_modals.py` /
  `_notification_status_overrides.py`) and re-applied on every load in `_loading_finalize.py`.
  `should_clear_loaded_agent_status_override` (`_loading_helpers.py`) only clears a non-`QUESTION`/`ANSWERED` override
  when the loaded status is in `DISMISSABLE_STATUSES` (terminal). So even after Cause 2a is fixed and the mirror
  computes `WORKING TALE`, this override re-pins the root to `TALE APPROVED` while the coder runs. The override must
  yield to the mirror once the coder is actually running.

### Invariant 1 (plan child must be sticky-approved) — pre-existing latent bug

The planner child's status is produced by `planner_child_status()` in `src/sase/ace/tui/models/_agent_status_family.py`
(used both by `sync_planner_child_from_parent` for the real `--plan` main agent step and by
`ensure_synthetic_planner_children` for synthetic planner rows). Its current logic returns `DONE` as soon as the family
has any follow-up child (the coder counts). It has no notion of "the plan was approved", so an approved planner row with
a running/finished coder reads `DONE` instead of `TALE APPROVED` / `PLAN APPROVED`. This predates the `WORKING` commit
but is the second half of the user's reported breakage.

Note: the original tale explicitly flagged this exact fork as an open question — "if instead the intent is for the
planner/root row itself to display `WORKING PLAN` / `WORKING TALE` … that is a small variant (swap which row carries
which label)". The user is now choosing that variant: sticky-approved lives on the **plan child**, and the **root**
mirrors verbatim.

## Design

Adopt one clean model: **the planner (`--plan`) row owns the sticky approved status; the root is a pure verbatim mirror
of its newest child.** Concretely:

- Gap before coder renders → newest child is the planner (`TALE APPROVED`) → root mirrors `TALE APPROVED`.
- Coder running → newest child is the coder (`WORKING TALE`) → root mirrors `WORKING TALE`.
- Coder finished → newest child is the coder (`TALE DONE`) → root mirrors `TALE DONE`; planner row stays
  `TALE APPROVED`.

This satisfies both invariants simultaneously and keeps the planner row as the stable "this plan was approved" anchor.

## Implementation

### Change A — Root mirrors the newest child verbatim

File: `src/sase/ace/tui/models/_agent_status_apply.py`

- In the agent-family root-mirror loop, replace
  `parent.status = WORKING_PLAN_STATUS_TO_APPROVED.get(newest.status, newest.status)` with
  `parent.status = newest.status`.
- Drop the now-unused `WORKING_PLAN_STATUS_TO_APPROVED` import.
- Update the loop comment: the root is a verbatim mirror; the sticky approved status now lives on the planner child.

### Change B — Approval override yields to the running coder on the root

File: `src/sase/ace/tui/actions/agents/_loading_helpers.py`

- In `should_clear_loaded_agent_status_override`, clear an approved-plan override once the freshly loaded row has
  already mirrored to a working status: if `override` ∈ `APPROVED_PLAN_STATUSES` and `agent.status` ∈
  `WORKING_PLAN_STATUSES`, return `True`. (Import both frozensets from `sase.agent.status_buckets`.)
- This preserves the pre-coder gap (loaded status `DONE`/`RUNNING` keeps the override as today) and the terminal clear
  (already handled by `DISMISSABLE_STATUSES`), while letting the mirrored `WORKING TALE` win during the coder run.
- Confirm where the approval override actually lands: trace `find_agent_for_notification` /
  `agent_matches_notification_identity`. If it targets the root, Change B is required; if it already targets the planner
  child, Change B is a harmless safeguard and the planner's marker-derived approved status stays consistent.

### Change C — Planner child is sticky-approved

File: `src/sase/ace/tui/models/_agent_status_family.py`

- Add a parent-level helper `approved_planner_status(parent, all_agents, children_by_parent) -> str | None`:
  - **Approved when** `parent.plan_action` ∈ `{"approve", "tale"}` **or** the parent has a coder follow-up child
    (`agent_family_role` == `code`). The coder-child signal makes the status stick after the coder finishes (the coder
    row always survives); the `plan_action` signal covers the gap before the coder is launched.
  - **Tale lineage when** `parent.plan_action == "tale"` **or** `parent.status` ∈ `{TALE_APPROVED_STATUS, "TALE DONE"}`
    **or** any coder child has `plan_action == "tale"` — mirroring the existing detection in `done_handoff_status` /
    `active_approved_plan_handoff_status`. Returns `TALE_APPROVED_STATUS`, else `PLAN_APPROVED_STATUS`; returns `None`
    when not approved.
  - Accept either `children_by_parent` or only `all_agents`, matching the existing `has_family_followup_child` signature
    handling, so it works from both `sync_planner_child_from_parent` (has `children_by_parent`) and
    `ensure_synthetic_planner_children` (has only `all_agents`).
- In `planner_child_status`, insert the approved check immediately after the active-state early returns
  (`STARTING/WAITING/RUNNING/FAILED/PLAN REJECTED` and `QUESTION/ANSWERED`) and **before** the
  `has_family_followup_child → DONE/ANSWERED` branch: if `approved_planner_status(...)` is non-`None`, return it.
- One change covers both the real `--plan` main agent step and synthetic planner rows. Epic/legend/commit plans are
  unaffected (their `plan_action` is outside `{approve, tale}` and they spawn no `code` child), so they keep current
  behavior.

### Verify-only (no code changes expected)

- **Rendering.** `_agent_list_render_agent.py`, `prompt_panel/_workflow_render.py`, and `zoom_panel_modal.py` already
  have explicit color branches for `TALE_APPROVED` / `PLAN_APPROVED` / `WORKING_PLAN` / `WORKING_TALE`, so the planner
  row (`TALE APPROVED`) and the root (`WORKING TALE`) already paint correctly.
- **Revive.** `_revive_artifacts.py` already maps `TALE_APPROVED_STATUS` / `WORKING_TALE_STATUS` →
  `plan_approved=True, plan_action="tale"`. Reviving the root from `WORKING TALE` reconstructs correct markers — confirm
  the round-trip still passes.

## Tests

- `tests/test_agent_loader_status_override_tale.py`:
  - Flip the active-code-child cases — with verbatim mirroring the root (`parent`) now reads `WORKING TALE` /
    `WORKING PLAN` (was `TALE APPROVED` / `PLAN APPROVED`); the code child stays `WORKING TALE` / `WORKING PLAN`.
  - Add a three-row case (root + real `--plan` main step + `--code` coder) asserting planner = `TALE APPROVED` (sticky),
    coder = `WORKING TALE`, root = `WORKING TALE`.
  - Add a post-completion case (coder `DONE`) asserting planner stays `TALE APPROVED` while root mirrors `TALE DONE`.
- New unit coverage for `should_clear_loaded_agent_status_override`: approved override + `WORKING TALE`/`WORKING PLAN`
  status → cleared; approved override + `DONE`/`RUNNING` → kept; approved override + terminal → cleared (regression
  guard).
- Update assertions in `tests/ace/tui/widgets/test_agent_list_runtime_compute.py`,
  `test_agent_list_runtime_rendering.py`, and `tests/ace/tui/models/test_agent_groups_grouping_mode_status.py` that
  encode the old root-on-approved behavior.
- Visual: regenerate `tests/ace/tui/visual/snapshots/png/agents_plan_handoff_status_colors_120x40.png` (and any other
  ACE agents snapshot that shows these rows) with `just test-visual --sase-update-visual-snapshots`; the root recolors
  `TALE APPROVED` → `WORKING TALE` and the planner row `DONE` → `TALE APPROVED`.
- `tests/test_agent_revive_meta.py` / `test_agent_revive_status.py`: confirm revive round-trips still pass with the root
  displayed as `WORKING TALE`.

## Validation

- `just install` then `just check` (ruff + mypy + fast tests) and `just test-visual`.
- Manual smoke in `sase ace`: approve a tale plan and a standard plan; confirm the planner row shows sticky
  `TALE APPROVED` / `PLAN APPROVED` (including during the coder-start gap and after the coder finishes), and the root
  mirrors its newest child (`WORKING TALE` / `WORKING PLAN` while coding, `TALE DONE` / `PLAN DONE` after), each in its
  own color.

## Scope / boundary

- Pure Python TUI presentation layer; **no `sase-core` / `sase_core_rs` changes** (status strings are derived locally
  from already-shared marker fields, per the Rust-core boundary rule and the original tale's scope note).

## Out of scope

- Epic / legend / commit planner statuses and colors (unchanged).
- Status color palettes (already distinct after the `WORKING` work).
- Restructuring the two-row vs three-row family model beyond the status assignments above.
