---
create_time: 2026-04-24 14:20:46
status: done
prompt: sdd/prompts/202604/epic_created_status.md
---
# Plan: Add "EPIC CREATED" Agent Status for Completed Epic-Creation Follow-ups

## Problem

In the `sase ace` TUI "Agents" tab today, the `.plan` agent status machine for the epic-approval flow is:

1. `.plan` agent running → `PLANNING`
2. `.plan` agent `DONE`, user clicks **E** (Epic) button → `.epic` follow-up child spawned
3. While `.epic` child is active → parent workflow shows `EPIC APPROVED` (_user approved epic creation_)
4. `.epic` child completes (`DONE`) → parent workflow flips to `PLAN DONE`

The terminal label `PLAN DONE` loses useful signal: the user can no longer distinguish, at a glance, between a workflow
whose plan merely finished versus one whose `.epic` follow-up actually **created a sase beads epic**.

Commit `e335dc3b` renamed the prior "EPIC CREATED" string to `EPIC APPROVED` precisely so the name reflects _user
approval_, not _bead creation_. That rename freed up the string "EPIC CREATED" to now mean what its words plainly say:
the epic bead has been successfully created.

## Goal

Introduce a new distinct `EPIC CREATED` status that the workflow container displays once its `.epic` follow-up child
completes successfully. Keep `EPIC APPROVED` for the in-progress phase (user approved → child still running).

Semantic model after this change:

| Condition                                     | Workflow status                        |
| --------------------------------------------- | -------------------------------------- |
| `.epic` child still running                   | `EPIC APPROVED`                        |
| `.epic` child completed successfully (`DONE`) | `EPIC CREATED` ★                       |
| `.epic` child `FAILED`                        | `PLAN DONE`                            |
| `.commit` child completed                     | `PLAN DONE` (unchanged — out of scope) |

★ new

## Root Cause / Where the Change Lives

`src/sase/ace/tui/models/agent_loader.py` — `_apply_status_overrides()`:

- Lines 215–273 pick an override for parents with _active_ follow-up children and produce `EPIC APPROVED` /
  `PLAN COMMITTED` / `PLAN APPROVED`.
- Lines 279–286 sweep parents whose follow-ups have all finished and flip them to `PLAN DONE`.

The second sweep is the one that currently collapses any completed follow-up into the generic `PLAN DONE`. It does not
inspect the completed child's `role_suffix`, so a completed `.epic` child is indistinguishable from any other completed
follow-up.

## Design

Add a parallel tracker that records, per-parent, whether the **most-recent completed follow-up child** has
`role_suffix == ".epic"`. When the post-sweep loop decides the parent's terminal label, prefer `EPIC CREATED` for that
case over the default `PLAN DONE`.

### Algorithm

During the existing ordered-iteration over children (already sorted by start time, oldest → newest, so newest-wins
semantics are preserved):

- If child is `.epic` **and** child status is in `completed_statuses` ⇒ remember
  `epic_completed_override[parent_ts] = "EPIC CREATED"`.
- If any _later_ child (epic or not) is completed with a different role_suffix, that newer completion wins (last-writer-
  wins, matching the active-followup tie-breaker for consistency). A completed `.code` or `.commit` after a completed
  `.epic` would fall back to `PLAN DONE` — this is a degenerate real-world case but we behave predictably.

In the post-sweep at lines 279–286, change the hard-coded `PLAN DONE` assignment to consult the override:

```python
if agent.raw_suffix in epic_completed_override:
    agent.status = "EPIC CREATED"
else:
    agent.status = "PLAN DONE"
```

### Scope restriction to `.epic`

The user asked specifically about the epic flow. We **do not** introduce a parallel "COMMIT DONE" status for `.commit`
follow-ups; the `PLAN COMMITTED` state already captures the meaningful action (a plan was committed) and the user did
not request further granularity there. If that turns out to be desired later, the same pattern generalizes cleanly.

### Only on success

`EPIC CREATED` fires on `DONE` but not on `FAILED`. A failed `.epic` child means the bead was _not_ created, so
`PLAN DONE` (or, naturally, the child's `FAILED` status visible on its own row) remains the honest label.

### Why derive from `role_suffix` of the completed child (not `plan_action` on the parent meta)

Same rationale as the prior `fix_epic_created_workflow_status` plan:

1. `role_suffix` is already the authoritative signal used throughout `_apply_status_overrides`.
2. Avoids an extra file-read inside the loader hot path.
3. Parallels the existing active-child path (which already switches on `role_suffix`), keeping the logic symmetric and
   easy to reason about.

## Places That Need Updates

### Core status-transition logic (the functional change)

- **`src/sase/ace/tui/models/agent_loader.py`** — `_apply_status_overrides()`
  - Track completed `.epic` children in a new `epic_completed_override` map during the ordered iteration.
  - Update the `DONE → PLAN DONE` sweep (lines 279–286) to prefer `EPIC CREATED` when the override applies.

### Status registration — canonicalization / revive round-trip

Every set that treats terminal plan-like statuses as `completed` must also accept `EPIC CREATED`, so dismissing and
reviving a workflow in this state round-trips through disk correctly:

- **`src/sase/ace/tui/actions/agents/_revive.py`**
  - `_canonicalize_workflow_marker_status` (lines 373–385): add `"EPIC CREATED"` to the `→ "completed"` branch.
  - `_canonicalize_step_marker_status` (lines 387–400): same.
  - `_restore_agent_meta` `is_plan_like_status` set (lines 573–580): add `"EPIC CREATED"` so the `plan` flag is
    preserved across dismiss/revive.
  - Leave the `plan_approved` / `plan_action` persistence block (lines 583–588) **unchanged**: `EPIC CREATED` is a
    derived status coming from the _child's_ completion, not a user-visible approval action on the parent's
    `agent_meta.json`. The next loader pass will re-derive `EPIC CREATED` from the child artifacts once the agent is
    revived.

- **`src/sase/ace/tui/models/_loaders/_artifact_loaders.py`**
  - `enrich_agent_from_meta()` (lines 169–181): no change needed — this reads `plan_action` off the parent's
    `agent_meta.json` and maps to `EPIC APPROVED`. `EPIC CREATED` is derived later by `_apply_status_overrides()` once
    the completed child is visible.

### Dismissible-status lists

A workflow displaying `EPIC CREATED` is terminal and should be dismissible just like `PLAN DONE`:

- **`src/sase/ace/tui/actions/agents/_loading_helpers.py`** — `DISMISSABLE_STATUSES` (lines 14–20): add `EPIC CREATED`.
- **`src/sase/ace/tui/widgets/agent_list.py`** — `_DISMISSIBLE_STATUSES` (lines 39–43): add `EPIC CREATED`.

### Styling (optional but recommended)

`EPIC APPROVED` and `PLAN COMMITTED` currently fall through to the default "dim" style in `agent_list.py` and to the
fallback `#D7D7FF` in `_workflow_display.py`. Two options:

1. **Minimal**: leave `EPIC CREATED` styled by the same fallback. Acceptable for a first pass.
2. **Explicit styling**: give `EPIC CREATED` a distinctive color (a brighter/terminal-feel green to distinguish it from
   the active `EPIC APPROVED`). Suggest `#5FD7AF` (sea-green) in `_workflow_display.py` and a matching `bold #5FD7AF`
   branch in `agent_list.py`.

Recommendation: go with option **2** so the user actually gets the visual differentiation that motivated the status
split. Worth a single-line branch in each file.

### Comments and docstrings

- `_apply_status_overrides` docstring (agent_loader.py lines 157–164): add a bullet for `DONE → EPIC CREATED`.
- The `Pick override status…` comment inside the loop (around line 233): expand to mention the completed-child case too.
- `_artifact_loaders.py` comment at line 169 ("Set PLANNING / PLAN APPROVED / PLAN COMMITTED / EPIC APPROVED status")
  does not need updating (it's about the active-plan statuses, not the terminal derived ones).

### Help / skill documentation

- **`src/sase/xprompts/skills/sase_agents_status.md`** (if it enumerates statuses): add `EPIC CREATED` alongside
  `EPIC APPROVED` and describe the transition.

## Testing

Add to `tests/test_agent_loader.py`:

1. `test_apply_status_overrides_completed_epic_child_sets_epic_created` — single `.epic` child in `DONE` state with
   parent `.plan` also `DONE` ⇒ parent becomes `EPIC CREATED`. (Replaces today's assertion that it becomes `PLAN DONE`;
   the current test `test_apply_status_overrides_completed_epic_child_does_not_set_epic_approved` must be updated — its
   assertion changes from `PLAN DONE` to `EPIC CREATED`, and its name/docstring should be renamed accordingly.)
2. `test_apply_status_overrides_failed_epic_child_stays_plan_done` — `.epic` child in `FAILED` state ⇒ parent stays at
   `PLAN DONE` (not `EPIC CREATED`).
3. `test_apply_status_overrides_active_epic_child_still_sets_epic_approved` — regression guard: with an _active_ `.epic`
   child, the parent still goes to `EPIC APPROVED` (existing
   `test_apply_status_overrides_active_epic_child_sets_epic_approved` covers this — leave it alone).
4. `test_apply_status_overrides_epic_then_code_completed_latest_wins` — if a `.code` child completed after the `.epic`
   child, parent uses `PLAN DONE` (last-writer-wins with non-epic suffix).

Add to `tests/test_agent_revive.py`:

5. `("EPIC CREATED", "completed")` case in the parametrized canonicalization test around line 155–165 (it currently
   lists `EPIC APPROVED`, `PLAN COMMITTED`, `PLAN DONE`).

Manual verification:

- In `sase ace`, run a plan-to-epic flow end-to-end, wait for the `.epic` child to finish, and confirm the workflow row
  flips from `EPIC APPROVED` (while child is running) to `EPIC CREATED` (once child is `DONE`).
- Dismiss the workflow with `X`, revive with `R`, confirm it re-appears with `EPIC CREATED` still correctly displayed
  (round-trip through `_revive.py`).

## Scope & Risk

- **Functional diff is ~10 lines** in `agent_loader.py`, plus single-line additions in ~5 other files for status-set
  registration and styling, plus test updates.
- No new schema fields, no migrations, no persisted status string on disk (the status is always re-derived from the
  child agent's presence/state on load).
- Risk is bounded to the workflow status-override logic and well-covered by the new + existing tests.
- Downstream consumers that currently match on `PLAN DONE` (e.g. revive canonicalization, dismissible lists) are all
  updated in this change. A codebase-wide grep for `"PLAN DONE"` during implementation will confirm no additional
  matcher sites exist.

## Non-goals

- Not changing how `.commit` follow-ups present their terminal label. `PLAN COMMITTED` is already distinct and the user
  did not request a separate post-completion state for that branch.
- Not changing any axe-side dispatch, the notification modals, or `persist_plan_approved()`. The parent's
  `plan_action="epic"` metadata continues to drive the `EPIC APPROVED` active-state display unchanged.
- Not touching historical plans/specs that reference the old meaning of "EPIC CREATED".

## Open Question

Should `EPIC CREATED` keep the terminal-ness that `PLAN DONE` has (i.e. be auto-dismissible by bulk "dismiss completed"
actions)? Current recommendation: **yes** — it is a success terminal just like `PLAN DONE`, and omitting it from the
dismissable set would surprise users who routinely mass-dismiss finished work. Plan adds it to both
`DISMISSABLE_STATUSES` and `_DISMISSIBLE_STATUSES`.
