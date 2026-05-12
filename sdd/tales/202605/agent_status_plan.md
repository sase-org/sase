---
create_time: 2026-05-12 17:17:57
status: done
prompt: sdd/prompts/202605/agent_status_plan.md
---
# Plan: Rename Agents-tab PLANNING status to PLAN

## Goal

Rename the ACE Agents tab status currently shown and handled as `PLANNING` to `PLAN`, and update the active code, docs,
and tests so `PLAN` is the canonical status for “a submitted plan is waiting on user review.”

## Scope

- Treat `PLAN` as an agent status value, not as a generic replacement for every occurrence of the word “planning.”
- Leave existing distinct statuses unchanged:
  - `PLAN APPROVED`
  - `PLAN COMMITTED`
  - `PLAN DONE`
  - `PLAN REJECTED`
  - `TALE APPROVED` / `TALE DONE`
  - `EPIC APPROVED` / `EPIC CREATED`
- Leave unrelated `PLAN` concepts unchanged, including ChangeSpec `| PLAN:` drawers, commit `PLAN=` tags, timestamp
  display labels, and bead `IssueType.PLAN`.
- Do not modify memory files or historical SDD prompt/tale screenshots unless a test or active documentation path
  requires it.

## Implementation

1. Update canonical status production paths:
   - Plan metadata enrichment should emit `PLAN` instead of `PLANNING` when a submitted plan is awaiting manual review.
   - Workflow relationship overrides should set root plan workflows to `PLAN` in the no-follow-up / awaiting-review
     case.
   - Notification status overrides for unread `PlanApproval` notifications should set `PLAN`.

2. Update status consumers and UI behavior:
   - Agents row rendering should color `PLAN` with the current pink/magenta plan-review style.
   - Status bucketing and “asking/user-paused” helpers should classify `PLAN` the same way `PLANNING` is classified
     today.
   - Runtime suffix logic should keep using the latest plan submission time for `PLAN` rows and continue showing the
     user-paused marker.
   - Command availability, keybinding footer labels, revive/artifact handling, prompt/details panels, active-status
     sets, and loader active-status sets should recognize `PLAN`.

3. Update tests:
   - Replace tests that construct or assert `PLANNING` with `PLAN`.
   - Preserve semantics: `PLAN` remains in the Stopped bucket, remains user-paused, and continues to use the
     plan-submitted timestamp for runtime suffixes.
   - Update any command-palette / notification override / loader enrichment expectations.

4. Update active docs:
   - Change user-facing docs that describe the Agents-tab status from `PLANNING` to `PLAN`.
   - Keep references to general planning prose unchanged when they are not naming the status.

5. Verify:
   - Run focused status/rendering tests first.
   - Run `just install` if the workspace environment needs refresh, then run `just check` as required after repo
     changes.
   - Finish with `rg -n '\bPLANNING\b' src tests docs --glob '!**/*.png'` and inspect any remaining hits to ensure they
     are intentionally unrelated.

## Risks

- `PLAN` is already used elsewhere in SASE for commit drawers, plan metadata, and bead issue types. The edits need to
  stay status-context-specific rather than broad search-and-replace.
- Existing live ACE sessions may still have in-memory overrides containing `PLANNING`. This change targets current code
  paths and tests; if compatibility is needed for persisted external data, add a narrow status-normalization shim in the
  affected loader/render path instead of keeping `PLANNING` as an active status in docs or tests.
