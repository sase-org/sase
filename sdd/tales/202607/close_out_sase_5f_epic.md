---
create_time: 2026-07-06 01:43:17
status: wip
---
# Plan: Close Out Epic sase-5f (Dynamic Agent Families v1)

## Product Context

Epic `sase-5f` ("Dynamic Agent Families v1", plan file `sdd/epics/202607/dynamic_agent_families_v1.md`) has all five
phase beads closed with their commits merged to `master`. A code-level audit of each phase against the epic plan's
acceptance criteria found the implementation complete across all phases, but **Phases 3 and 4 shipped without several
tests their acceptance criteria explicitly required**. This plan adds the missing coverage, performs small cleanups
discovered during the audit, and then closes the epic.

Audit results driving this plan:

- **Phase 1, 2, 5:** fully complete (implementation + tests + docs). No action needed.
- **Phase 3 (`%n(parent, suffix)` attach, commit `7b357a097`):** implementation complete (grammar, strict validation,
  Rust-delegated parent resolution via `resolve_agent_family_parent` in `sase-core`, prep-time enforcement, collision
  handling, metadata write, `SASE_PLAN` rule). Missing acceptance tests:
  - Resolution error paths: absent parent, dismissed parent (message names the revive path), ambiguous parent (message
    lists candidates). Only the running-parent path is tested today.
  - Newest-match-wins and project-scoping resolution behavior.
  - The explicit v1→v2 compatibility test: a `%n`-attached member's metadata is field-indistinguishable from a
    runner-created follow-up (`create_followup_artifacts`), resolves via the existing family lookup
    (`src/sase/agent/names/_lookup.py`), and classifies as a family-member child row in the TUI model.
  - Reserved-suffix role mapping exercised through the attach path (`plan`, `q`, `code`, `epic`, `legend`, `commit` →
    built-in roles; custom word → generic role with the word recorded).
  - `SASE_PLAN` rule branch: only `code`-role members whose parent family has a committed/archived plan get `SASE_PLAN`.
- **Phase 4 (queued children, commit `dfd9f50f0`):** implementation complete (identity-keyed waits, family-aware
  terminal detection, cancel-to-STOPPED path with notification). Wait-resolution unit coverage is thorough, but the
  acceptance-required integration test is absent:
  - queue → parent completes → child proceeds past the wait barrier.
  - queue → parent fails → child finalizes as STOPPED **and a notification is recorded** — the cancel-path notification
    (`_finalize_cancelled_wait` → `notify_workflow_complete` in `src/sase/axe/run_agent_runner.py`) currently has zero
    test coverage.
- **Cleanup:** `_resolution_error_message` in `src/sase/agent/family_attach.py` retains a `kind == "running"` error
  branch that became unreachable when Phase 4 started accepting running parents. Verify it is unreachable and remove it.
- **Already resolved in the working tree (keep):** the five managed provider shims (`AGENTS.md`, `CLAUDE.md`,
  `GEMINI.md`, `OPENCODE.md`, `QWEN.md`) were stale relative to the user-approved glossary rewording in
  `memory/glossary.md` (commit `a2e8c8e93`), which made `just check` fail at `sase validate`. They have been refreshed
  via `sase init memory -C`; the diff is exactly the approved "Agent Family" `--`-separator rewording. This was the
  Phase 5 glossary-reconciliation follow-through the phase agent correctly left pending user approval.

## Steps

1. **Phase 3 resolution error-path + scoping tests** (`tests/test_dynamic_agent_family_attach.py`): absent parent,
   dismissed parent (revive path named), ambiguous parent (candidates listed), newest-match-wins with multiple
   same-named candidates, and project scoping. Drive them through the same seam the existing running-parent test uses so
   the Rust classifier binding is exercised, not mocked.

2. **Phase 3 v1→v2 metadata-parity test**: build a terminal parent's artifacts, run the `%n` attach prep, and assert the
   resulting member metadata carries the same family fields (`agent_family`, `agent_family_role`, `role_suffix`,
   `parent_timestamp`, inherited project/workspace fields) that `create_followup_artifacts` writes for a runner
   follow-up; assert the member resolves via `find_agent_family` and classifies as a family-member child in the TUI
   agent model.

3. **Phase 3 role-mapping + `SASE_PLAN` tests**: reserved suffixes map to built-in roles and custom suffixes to the
   generic role through the attach path; `SASE_PLAN` is set only for `code`-role members whose parent family has a
   committed/archived plan (both the set and not-set branches).

4. **Phase 4 integration tests**: (a) queued child with an identity-keyed wait on a running parent proceeds once the
   parent completes; (b) when the parent fails, the child finalizes as STOPPED with `queue_cancelled` recorded and a
   notification is sent via the existing sender seam (assert `notify_workflow_complete` fires with the queue-cancel
   notes). Exercise `_finalize_cancelled_wait` through the runner path rather than calling it directly, faking the
   sender.

5. **Dead-code cleanup**: confirm the `kind == "running"` branch of `_resolution_error_message` is unreachable and
   remove it (adjusting any exhaustiveness handling as needed).

6. **Validation**: run the full `just check` and ensure it is green end-to-end (the managed-shim refresh already fixed
   the `sase validate` failure that blocked Phase 5's run).

7. **Close the epic bead**: `sase bead close sase-5f`.

8. **Post-close unused-code sweep**: run `just pyvision` after the bead is closed (epic-open suppressions lift) and
   remove any newly flagged unused symbols left behind by the epic.

9. **Mark the epic plan done**: set `status: done` in the frontmatter of
   `sdd/epics/202607/dynamic_agent_families_v1.md`.

## Non-Goals

- No behavior changes to the family-attach, wait, or notification implementations beyond the dead-branch removal — the
  audit found the shipped behavior correct; this plan is coverage and closeout.
- No edits to canonical memory files; the shim refresh only syncs generated files with the already-approved canonical
  glossary.
- No new `sase-core` (Rust) changes; the existing `resolve_agent_family_parent` binding is exercised as-is.
