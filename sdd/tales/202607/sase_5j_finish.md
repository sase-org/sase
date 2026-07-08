---
create_time: 2026-07-08 02:46:34
status: done
prompt: sdd/prompts/202607/sase_5j_finish.md
---
# Plan: Finish sase-5j — close remaining gaps in the Separate-SDD-Repo epic

## Context

Epic `sase-5j` ("Separate SDD Repository — Provider-Level Opt-In for VCS Workflows") landed six phases across the `sase`
and `sase-github` repos. A completion audit of every phase against the epic plan
(`sdd/epics/202607/sdd_separate_repo.md`) and the landed commits confirms the production behavior is implemented and
both repos' `just check` suites are green. However, two phases have small, concrete gaps in explicitly-enumerated scope
sub-items that prior phase agents marked complete but did not finish:

- **Phase 2 (materialization framework), scope item 4 — explicit-config guard.** The `SddMaterializationError` message
  produced by `_store_not_materialized_message()` names the expected companion repo but does **not** point the user at
  `sase sdd migrate`, which the plan requires ("message names the expected repo and points at `sase sdd migrate`"). At
  Phase 2 time that command did not yet exist; it now does (delivered in Phase 4), so the message can and should
  reference it.
- **Phase 4 (migration + doctor), scope item 4 — tests.** The plan enumerates test deliverables that are missing: an
  idempotent migrate re-run test, a `--remove-in-tree` commit-isolation test (the removal commit must contain only the
  `sdd/` tree), and a doctor "check matrix" — currently only 3 of the doctor storage codes are covered by tests;
  `companion-diverged`, `duplicate-companion-remote`, and `record-ignored-by-config` have none.

One additional item was audited and found acceptable as-is (see "Audited, no change" below), so it is documented rather
than changed.

All other scope items across Phases 1, 3, 5, and 6 were verified fully complete.

## Goals

Close the enumerated Phase 2 and Phase 4 scope gaps with equivalent-quality, low-risk changes, keep both repos green,
then close the epic bead and record the epic plan as done.

## Design / Work Items

### 1. Phase 2 — make the not-materialized error actionable

- Update `_store_not_materialized_message()` (in the SDD store module) so the message points the user at
  `sase sdd migrate` (e.g. "... run `sase sdd migrate` to create or connect the companion repository ...") while still
  naming the expected repo. Keep it a single, clear, actionable sentence.
- Update the existing unit assertion that pins the old wording so it asserts the new, `sase sdd migrate`-referencing
  text.

### 2. Phase 4 — fill the migrate test gaps

Add to the migrate test suite:

- **Idempotent re-run:** running `sase sdd migrate` a second time on an already-migrated project succeeds (no error,
  config/record remain coherent, no duplicate/erroneous state).
- **`--remove-in-tree` commit isolation:** after an in-tree → separate-repo migration with `--remove-in-tree`, the
  commit that removes the tracked `sdd/` tree from the code repo contains **only** the `sdd/` removal and nothing else
  (assert the removal commit's changed paths are confined to `sdd/`).

Follow the existing conventions in the migrate test module (fixtures, `gh`/provider mocking).

### 3. Phase 4 — complete the doctor check matrix

Add doctor tests covering the currently-untested SDD storage diagnostic codes:

- `companion-diverged` (ahead/behind the companion remote; must stay offline-tolerant).
- `duplicate-companion-remote` (two projects claiming the same companion repo).
- `record-ignored-by-config` (a materialized record present but config forces a different mode).

Mirror the structure of the existing doctor config-sdd tests.

### 4. Audited, no change (documented decision)

The Phase 2 explicit-config guard is surfaced loudly on the synchronous, user-initiated paths (`sase sdd init`,
`sase sdd migrate`, and bead initialization). The two remaining SDD write paths — the TUI plan-archive action and the
axe plan-accept flow — deliberately catch the error non-fatally. Audit finding: in the misconfigured
`separate_repo`-without-repo case the materialize call raises before any file write, so no SDD files are written to the
wrong location (the plan's strongest prohibition, "never a silent fall-back to in-tree or local writes", is not
violated); only a warning is logged and the action is skipped. These handlers must remain non-fatal (the TUI event loop
must never crash; the axe exec flow must continue), so they are intentionally left unchanged. No code change; recorded
here as the decision.

## Validation

- Run `just install` then `just check` in the `sase` repo; must be green (includes the new tests).
- The `sase-github` repo is unaffected by this plan (no changes there); its suite was already verified green against the
  local `sase` checkout via `SASE_CORE_PATH`.

## Final steps

1. `just check` green in `sase`.
2. Close the epic bead: `sase bead close sase-5j`.
3. After closing the epic, run `just pyvision` to confirm no now-unused code was left behind (some symbols are allowed
   to be unused only while the epic is open).
4. Set `status: done` in the frontmatter of the epic plan file `sdd/epics/202607/sdd_separate_repo.md`.

## Non-goals

- No changes to the non-fatal TUI/axe write-path exception handling (see "Audited, no change").
- No new production behavior beyond the error-message wording; the epic's feature scope is already implemented.
- No `sase-github` changes.
