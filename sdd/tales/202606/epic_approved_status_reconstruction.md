---
create_time: 2026-06-27 16:01:17
status: done
prompt: sdd/prompts/202606/epic_approved_status_reconstruction.md
---
# Plan: Reconstruct EPIC/LEGEND/COMMIT Approved-Handoff Statuses After TUI Restart

## Problem

In `sase ace`, an agent whose plan was approved with the **epic** action shows the correct `EPIC APPROVED` status during
the session, but reverts to `RUNNING` after the TUI is restarted. The status is wrong only after a restart; it is
correct while the approving session stays open.

The same defect affects the **legend** and **commit** approval actions: an active `.legend` / `.commit` follow-up should
reconstruct to `LEGEND APPROVED` / `PLAN COMMITTED` after restart, but instead reconstructs to `RUNNING`.

## Root Cause

Agent-family roots are _containers_: the TUI computes a root's displayed status by mirroring its newest logical child's
status. The status-override pass (`src/sase/ace/tui/models/_agent_status_apply.py`) runs, in order:

1. Active approved-plan handoff normalization — rewrites an actively-running follow-up child's raw `RUNNING` into the
   semantic handoff status, via `active_approved_plan_handoff_status(parent, child)`.
2. Completed handoff normalization — e.g. a completed `.epic` child becomes `EPIC CREATED`.
3. Root mirroring — the family root copies the newest child's (now normalized) status.

When a plan is approved as an epic, an active `.epic` follow-up child runs with raw status `RUNNING`. But
`active_approved_plan_handoff_status` (`src/sase/ace/tui/models/_agent_status_family.py`) only recognizes **coder**
follow-ups (`if not is_coder_agent(child): return None`). For an epic/legend/commit child it returns `None`, so the
child keeps `RUNNING`, and the root mirrors `RUNNING`.

**Why it is correct until restart:** when the plan is approved in-session, the TUI also stores an in-memory status
override (`_agent_status_overrides[identity] = "EPIC APPROVED"`). That dict is session-only state and is re-applied on
every refresh on top of the loader-derived status. On TUI restart the dict starts empty, so the displayed status falls
back to the loader-derived value (`RUNNING`). The loader is the source of truth across restarts, and it never
reconstructs the epic/legend/commit handoff status.

**This is a known, deliberately-deferred gap.** The coder-handoff reconstruction was added by an earlier change
("reconstruct approved handoff statuses") whose own design doc records the scoping decision under _Risk_:

> The main behavioral risk is accidentally relabeling active non-code work, such as epic or commit follow-ups. Keeping
> the helper constrained to the canonical coder suffix avoids changing those paths.

Consistent with that deferral, the existing regression tests for the active epic/commit cases carry docstrings
describing the _intended_ `EPIC APPROVED` / `PLAN COMMITTED` behavior but assert the current buggy `RUNNING` output (in
`tests/test_agent_loader_status_override_followups.py`):

- `test_apply_status_overrides_active_epic_child_sets_epic_approved` — docstring says "becomes EPIC APPROVED", asserts
  `RUNNING`.
- `test_apply_status_overrides_active_commit_child_sets_plan_committed` — docstring says "becomes PLAN COMMITTED",
  asserts `RUNNING`.

The `EPIC APPROVED`, `LEGEND APPROVED`, and `PLAN COMMITTED` statuses are already first-class everywhere else
(notification approval mapping, persisted-meta enrichment, agent-row rendering, the revive/round-trip paths, status
bucketing). The only missing piece is loader-side reconstruction of the _active_ handoff, which is what survives a
restart.

## Related Bug Found (in scope)

While tracing the status lifecycle, I found a second, independent defect in the path that handles plans approved
**externally** (e.g. via Telegram), in `src/sase/ace/tui/actions/agents/_notification_status_overrides.py`
(`_auto_dismiss_external_plan_response`).

A **commit** approval is written to the response file as
`{"action": "approve", "commit_plan": true, "run_coder": false}`. The external-dismiss path detects "tale" with the
ad-hoc test `commit_plan is True and run_coder is True` and otherwise falls back to `PLAN APPROVED`. It has no branch
for the commit case, so an externally-approved commit is:

- shown as `PLAN APPROVED` instead of `PLAN COMMITTED`, and
- persisted as `plan_action="approve"` instead of `"commit"` (so it is _also_ wrong after restart, and can overwrite the
  correct metadata written by the canonical approval path).

The canonical, correct action mapping already exists in `src/sase/plan_approval_actions.py` (`_persisted_plan_action`),
which maps `run_coder == False → "commit"`, `commit_plan == True → "tale"`, else `"approve"`, and passes epic/legend
through. The fix is to make the external-dismiss path reuse this canonical mapping rather than re-deriving it ad hoc, so
epic/legend/approve/tale stay correct and commit is fixed.

## Intended Behavior

- An active `.epic` follow-up of an approved plan-family root displays as `EPIC APPROVED` (root and child), surviving a
  TUI restart.
- An active `.legend` follow-up displays as `LEGEND APPROVED`.
- An active `.commit` follow-up displays as `PLAN COMMITTED`.
- The existing coder handoff (`WORKING PLAN` / `WORKING TALE`) is unchanged.
- Higher-priority states keep precedence: a real blocked `QUESTION`, failures, and completed handoffs (`EPIC CREATED`,
  `PLAN DONE`, `TALE DONE`) are unaffected — the new normalization, like the coder one, only rewrites children whose raw
  status is `RUNNING`, and runs before the completed and root-mirroring passes.
- A plan approved externally with the commit action displays as `PLAN COMMITTED` and persists `plan_action="commit"`,
  matching the in-TUI approval path.

### Out of scope (deliberate boundary)

Completed `.legend` and `.commit` follow-ups continue to read as their existing terminal status (`DONE`). Unlike `.epic`
(which has the dedicated `EPIC CREATED` terminal) and `.code` (`PLAN DONE` / `TALE DONE`), there is no defined
`LEGEND CREATED` / committed-terminal status in the product, and no test or spec calls for one. Introducing new terminal
statuses is a separate product decision and is not part of this fix.

## Implementation Strategy

### Part 1 — Primary fix: reconstruct active epic/legend/commit handoff status

1. In `src/sase/ace/tui/models/_agent_status_family.py`, extend `active_approved_plan_handoff_status(parent, child)` so
   that, after the existing `child.parent_workflow or child.status != "RUNNING"` guard, it branches on the child's
   family role:
   - role `epic` → `EPIC APPROVED`
   - role `legend` → `LEGEND APPROVED`
   - role `commit` → `PLAN COMMITTED`
   - role `code` → existing `WORKING TALE` / `WORKING PLAN` logic (unchanged)
   - anything else → `None`

   Use the existing `agent_family_role(child)` helper (already imported in this module) so dotted (`.epic`) and
   canonical/explicit roles are both handled. Keep the `RUNNING`-only guard so blocked questions and completed rows are
   never relabeled. Update the function docstring to say it covers all approved-plan handoffs, not just code.

   The single call site (`_agent_status_apply.py`, the active-handoff loop that iterates all non-workflow children of
   root plan workflows) already passes every follow-up child through this helper, so no orchestration change is required
   — the new return values flow into root mirroring automatically.

2. Prefer named status references over bare string literals where the surrounding module already uses them.
   `EPIC APPROVED` / `LEGEND APPROVED` / `PLAN COMMITTED` are currently bare literals across the codebase; to reduce
   duplication/typo risk, optionally introduce module-level constants in `src/sase/agent/status_buckets.py` (alongside
   `PLAN_APPROVED_STATUS` etc.) and reference them from the helper. This is a cleanliness step, not required for
   correctness; keep literals if it would broaden the diff unnecessarily.

### Part 2 — Related fix: external-approval commit mislabel

3. In `src/sase/plan_approval_actions.py`, expose the existing canonical action mapping as a public function (e.g. a
   thin `persisted_plan_action(response_json)` wrapper around the current private `_persisted_plan_action`) so other
   modules can reuse it without depending on a private symbol.

4. In `src/sase/ace/tui/actions/agents/_notification_status_overrides.py`, rewrite the action→status/persist logic
   inside `_auto_dismiss_external_plan_response` to:
   - compute the canonical action via the new public mapping,
   - derive the display-status override from that action using the shared status mapping (`plan_enrichment_status`
     already maps `commit → PLAN COMMITTED`, `epic → EPIC APPROVED`, `legend → LEGEND APPROVED`, `tale → TALE APPROVED`,
     `approve → PLAN APPROVED`),
   - persist that same canonical action via `persist_plan_approved`,
   - keep the non-approval (reject/feedback) fallthrough as the existing `RUNNING` override.

   This removes the ad-hoc `is_tale` heuristic, fixes commit, and keeps the other actions behaving as today.

### Part 3 — Tests

5. In `tests/test_agent_loader_status_override_followups.py`, align the existing contradictory tests with the corrected
   behavior and add the missing leg:
   - `..._active_epic_child_sets_epic_approved` → assert parent **and** child status `EPIC APPROVED`.
   - `..._active_commit_child_sets_plan_committed` → assert parent **and** child status `PLAN COMMITTED`.
   - `..._epic_and_code_active_newest_wins` → the newest child is the active `.epic`, so the root now mirrors
     `EPIC APPROVED` (update the `RUNNING` assertion; the "newest wins" intent is preserved).
   - Add a new test for an active `.legend` child → `LEGEND APPROVED` (parent and child).
   - Confirm the unchanged expectations still hold: completed `.epic` → `EPIC CREATED`, failed `.epic` → parent stays
     its failure/terminal status, completed `.code` after `.epic` → `PLAN DONE`, and the coder `WORKING PLAN` /
     `WORKING TALE` cases in `tests/test_agent_loader_status_override_tale.py`.

6. In `tests/ace/tui/test_agent_notification_status_overrides.py` (existing harness for
   `_auto_dismiss_external_plan_response`), add coverage that a commit-shaped external response (`action="approve"`,
   `commit_plan=True`, `run_coder=False`) produces a `PLAN COMMITTED` override and persists `plan_action="commit"`, and
   that epic/legend/approve/tale responses still produce their existing statuses.

### Part 4 — Verification

7. Run the focused suites first: `tests/test_agent_loader_status_override_followups.py`,
   `tests/test_agent_loader_status_override_tale.py`, `tests/test_agent_loader_status_override_times.py`,
   `tests/ace/tui/test_agent_notification_status_overrides.py`, plus the meta-enrichment plan-status test
   (`tests/test_enrich_agent_plan_meta.py`).

8. Then run the full repository check required by the workspace instructions (install first because workspaces are
   ephemeral, then lint + type-check + tests): `just install` followed by `just check`.

## Notes / Boundaries

- The fix stays entirely in Python TUI status-derivation code, matching the precedent set by the original coder-handoff
  reconstruction (which also touched only Python). The Rust core wire already carries the raw `plan_approved` /
  `plan_action` fields; only the Python display-status derivation needs to change, so no `sase-core` change is required.
- No new agent statuses are introduced — `EPIC APPROVED`, `LEGEND APPROVED`, and `PLAN COMMITTED` already exist and are
  handled by rendering, bucketing, dismissal, and revive. This change only makes the loader reconstruct them for the
  active-handoff window.
- The in-memory override system needs no change: when the loader now also produces the approved status, the override
  agrees with it; when the handoff completes (`EPIC CREATED`, dismissable), the existing override-clearing logic already
  drops the stale override.

## Risk

- Main risk is relabeling active non-handoff work. Mitigated by gating on `child.status == "RUNNING"` and on the
  specific family roles (`epic` / `legend` / `commit` / `code`), and by running the normalization before the
  completed-handoff and root-mirroring passes so `QUESTION`, failures, and completed terminals retain precedence.
- Part 2 changes a path that is harder to exercise end-to-end (external/Telegram approval). It is isolated behind the
  canonical action mapping already used by the in-TUI approval path and covered by the new unit test, keeping the
  behavior change minimal and reviewable. It can be landed independently of Part 1 if a smaller change is preferred.
