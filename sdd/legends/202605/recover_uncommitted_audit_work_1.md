---
create_time: 2026-05-10 11:03:55
status: wip
prompt: sdd/prompts/202605/recover_uncommitted_audit_work_1.md
---
# Plan: Recover Uncommitted Audit Work

## Context

Two audit transcripts were reviewed:

- `~/.sase/chats/202605/sase-ace_run-260510_103620.md`
- `~/.sase/chats/202605/sase-ace_run-260510_103619.md`

Both audits found that several May 9 implementation agents reported success but their implementation commits did not
land. Current read-only inventory confirms the active `sase_102` checkout is clean, while recoverable work still exists
in sibling workspaces, stashes, `../sase-core`, and `~/.local/share/chezmoi`.

The recovery should be split into independent epics because the work spans several domains and repositories:

- SASE Python/TUI behavior in this repo.
- Rust backend/editor behavior in `../sase-core`.
- Personal config automation in `~/.local/share/chezmoi`.
- Bead metadata and generated skill synchronization.
- Audit-only dirty work that must be triaged without mixing it into historical recovery.

## Current Inventory

Known sources of recoverable work:

- `sase_100 stash@{15}`: all-directives-visible TUI completion fix.
- `sase_100 stash@{14}`: `%tag/%t` to `%group/%g` plus `%time/%t` directive work.
- `sase_100 stash@{5}`, `stash@{6}`, `stash@{7}`: bead model routing Python work in several overlapping states.
- `../sase-core`: dirty Rust work for directive metadata and bead model routing.
- `~/.local/share/chezmoi`: dirty Athena config work for refresh-docs daemon polish, recent bug/improvement audits, and
  `%g` migration.
- `sase_104`: small audit-improvement fixes for `%alt` detection and commit CLI test isolation.
- `sase_0`: dirty `sdd/beads/issues.jsonl`; mostly bead-state churn and formatting noise, but it should be reviewed
  before any bead reconciliation.

Recently identified work that should not be folded into this historical recovery without explicit triage:

- `sase_100` currently contains newer artifacts-for-marked-agents implementation work tied to
  `sdd/tales/202605/artifacts_for_marked_agents.md`.
- The prior audit's `sase_100` axe/lumberjack fallback fix appears to have since landed as
  `010115ff fix: stop axe workspace-plugin launch failures from flooding errors`.

## Recovery Principles

1. Preserve all uncommitted sources before applying them.
   - Create patches or branches for each stash/dirty repo before resolving conflicts.
   - Do not drop or rewrite sibling workspace edits until their content has either landed or been explicitly rejected.

2. Keep domains separated.
   - Do not mix Python directive work, Rust core changes, chezmoi config, bead model routing, and unrelated audit fixes
     in one implementation stream.
   - Each epic should have phases that can be handled by distinct agent instances with clear file ownership.

3. Prefer the committed SDD plans as the source of truth.
   - Existing plans under `sdd/tales/202605/` and `sdd/epics/202605/` describe the intended behavior.
   - Stashes and dirty work are implementation evidence, not automatically authoritative.

4. Respect the Rust core boundary.
   - Shared directive metadata, launch fanout parsing, bead storage, bead mutation, and work-plan model propagation must
     be completed in `../sase-core` when the behavior is shared across frontends.

5. Verify per repository.
   - SASE repo changes require `just install` followed by `just check`.
   - Rust core changes require its Rust test/check path.
   - Chezmoi changes require its `just check` and, if accepted, `chezmoi apply --force`.

## Epic 0: Recovery Snapshot And Workstream Setup

Goal: make recovery reversible and prevent unrelated dirty work from being accidentally merged.

Phases:

1. Capture exact patches for all relevant stashes and dirty repos:
   - `sase_100 stash@{15}`, `stash@{14}`, `stash@{5}`, `stash@{6}`, `stash@{7}`.
   - `../sase-core` dirty diff.
   - `~/.local/share/chezmoi` dirty diff.
   - `sase_104` dirty diff.
   - `sase_0` bead diff.
2. Classify each patch as recover, superseded, or unrelated.
3. Create a recovery matrix that maps every audit item to an epic, source patch, target repo, and verification command.
4. Quarantine unrelated current work, especially `sase_100` artifacts-for-marked-agents, so later agents do not confuse
   it with May 9 recovery.

Exit criteria:

- Every audit-identified item has an owner epic.
- Every dirty/stashed source has a saved patch or branch.
- No implementation behavior has changed yet.

## Epic 1: Small SASE TUI Recovery

Goal: recover the two small SASE-only UI fixes that were planned and reportedly implemented but not committed.

Scope:

- `sdd/tales/202605/plan_review_approve_keymap.md`
- `sdd/tales/202605/all_directives_visible.md`
- `sase_100 stash@{15}` for the directive completion panel fix.
- Reconstruct plan approval keymap changes from the committed plan and/or transcript, since no obvious stash remains.

Phases:

1. Implement plan approval modal keymaps:
   - `a` means Approve.
   - `t` means Tale.
   - Footer/help text and focused tests match the new mapping.
2. Recover all-directives-visible:
   - Directive completion shows all directive candidates without overflowing or hiding rows.
   - Other completion kinds keep existing scrolling limits.
3. Run focused TUI/widget tests.
4. Run `just install` if needed and `just check`.

Exit criteria:

- The two user-visible TUI regressions are fixed in this repo.
- No cross-repo changes are required for this epic.

## Epic 2: Directive Syntax Migration

Goal: finish the coupled directive grammar migration so Python, Rust, docs, completion, launch fanout, and local config
agree.

This epic deliberately combines `group_directive_rename` and `time_directive` because `%t` moves from tag/group usage to
time usage. Landing either half alone would create an inconsistent user surface.

Scope:

- `sdd/tales/202605/group_directive_rename.md`
- `sdd/tales/202605/time_directive.md`
- `sase_100 stash@{14}`
- Dirty `../sase-core/crates/sase_core/src/editor/directive.rs`
- Dirty `../sase-core/crates/sase_core/src/agent_launch/mod.rs`
- Chezmoi `%t` to `%g` config/script/test changes.

Phases:

1. Python parser and launch behavior:
   - Add `%time/%t` for duration and absolute wall-clock waits.
   - Keep `%wait/%w` for agent/workflow dependencies only.
   - Rename user-facing tag directive to `%group/%g` while preserving internal `PromptDirectives.tag`.
   - Split semantic wait detection from deferred-start detection so `%time` defers workspace allocation without becoming
     a previous-agent dependency.
2. Python completion, docs, prompt generation, and tests:
   - Completion exposes `%group/%g` and `%time/%t`.
   - Generated bead/legend/epic prompts use `%group`.
   - Docs and active examples stop advertising old `%tag/%t` aliases, except where intentionally describing history.
3. Rust core parity:
   - Editor directive metadata exposes `%group/%g` and `%time/%t`.
   - Launch fanout canonicalization treats `%t` as time and `%g` as group.
   - Rust tests prove `%time` does not become a bare previous-agent wait.
4. Chezmoi migration:
   - Update Athena config and helper scripts from `%t:<tag>` to `%g:<group>`.
   - Preserve unrelated non-SASE `%t` placeholders.
5. Cross-repo verification:
   - Python targeted directive tests, launch/fanout tests, and `just check`.
   - Rust core targeted tests and full Rust check path.
   - Chezmoi `just check`.
   - Final cross-repo search for stale `%tag`, `%t:`, `%group`, and `%g:` references.

Exit criteria:

- `%group/%g` is the grouping directive everywhere.
- `%time/%t` is the time-wait directive everywhere.
- `%wait/%w` no longer accepts time values.
- Python/Rust/editor docs agree.

## Epic 3: Bead Model Routing Completion

Goal: complete first-class bead `model` metadata and make `sase bead work` honor it for phase agents and land agents.

Scope:

- `sdd/epics/202605/bead_model_routing.md`
- `sdd/tales/202605/complete_bead_model_routing.md`
- `sase_100 stash@{5}`, `stash@{6}`, `stash@{7}`
- Dirty Rust core bead files.
- Generated `/sase_beads` skill workflow, which means the generated-skills memory must be followed.

Phases:

1. Storage and wire model:
   - Add `model` to Python bead records, JSONL, legacy DB helpers, Rust wire conversion, and mobile projections.
   - Add matching Rust storage, wire, mutation, schema, and validation support.
   - Reject newline/control-character injection in stored model values.
2. CLI and display:
   - Add `-m/--model` to `sase bead create` and `sase bead update`.
   - Show model metadata where useful.
   - Add parser/CRUD/show tests.
3. Epic and legend work rendering:
   - Phase beads route phase work agents via `%model`.
   - Epic/legend plan beads route final land agents via `%model`.
   - Intermediate legend planning agents remain unchanged.
4. Prompt and skill synchronization:
   - Update built-in bead automation prompts if needed.
   - Update `src/sase/xprompts/skills/sase_beads.md`.
   - Regenerate generated skills with the established workflow.
5. Verification and bead reconciliation:
   - Run targeted bead tests in Python and Rust.
   - Run `just install` and `just check`.
   - Reconcile `sdd/beads/issues.jsonl`: only close or update `sase-2o` and children after implementation is actually
     present in the target repo, and avoid importing unrelated formatting churn from `sase_0`.

Exit criteria:

- Bead model metadata persists, displays, and mutates correctly.
- `sase bead work` renders `%model` exactly for configured phase and land agents.
- Generated skill content is synchronized.
- Bead status reflects actual landed implementation.

## Epic 4: Chezmoi Automation Recovery

Goal: finish and validate the Athena config automation that was left dirty in chezmoi.

Scope:

- `sdd/tales/202605/refresh_docs_polish_daemon_agents.md`
- `sdd/epics/202605/lumberjack_quality_chops.md`
- Dirty `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
- Dirty `~/.local/share/chezmoi/home/bin/executable_sase_chop_gh_actions_fix`
- Dirty `~/.local/share/chezmoi/tests/bash/gh_actions_fix_chop_test.sh`

Phases:

1. Refresh-docs daemon polish:
   - Replace synchronous docs agent workflow step with daemon multi-prompt launch.
   - Launch update and polish agents.
   - Ensure polish waits for and resumes the update agent.
   - Keep marker update semantics tied to successful handoff.
2. Recent audit workflows:
   - Add `audit_recent_bugs` and `audit_recent_improvements`.
   - Preserve SHA/timestamp marker fallback and first-run behavior.
   - Embed `#pr` in launched prompts.
   - Use distinct marker files.
3. Lumberjack wiring:
   - Add scheduled bug/improvement chops with conservative cadence and 50-commit threshold.
   - Keep refresh-docs chops unchanged except for the intended `%g` migration.
4. Validation and application:
   - YAML parse.
   - `sase xprompt explain refresh_docs`, `audit_recent_bugs`, and `audit_recent_improvements`.
   - Chezmoi `just check`.
   - `chezmoi apply --force` only after validation passes.
5. Bead status cleanup for `sase-2n`:
   - Close or update `sase-2n` phase beads only after config implementation and validation are complete.
   - Avoid trusting the prior verifier claim unless the persisted bead store confirms it.

Exit criteria:

- The config launches the intended daemon workflows.
- Bug and improvement audits are threshold-gated and PR-wrapped.
- Live chezmoi-managed config is applied after checks.
- `sase-2n` status matches reality.

## Epic 5: Audit Improvement Fixes

Goal: evaluate and land the small May 10 audit-improvement fixes if they are still valid.

Scope:

- Dirty `sase_104` changes:
  - `%alt` detection regression fix in `src/sase/xprompt/_directive_alt.py`.
  - Commit CLI env isolation tests.
  - Single-model punctuation-prefixed `%alt` fanout test.

Phases:

1. Validate the bug report:
   - Reproduce the `%alt` punctuation regression on current master.
   - Reproduce or explain the commit CLI env contamination issue.
2. Land the minimal fixes if still applicable:
   - Use the existing `_ALT_DIRECTIVE_RE` helper consistently.
   - Keep commit CLI tests isolated from local commit-method environment variables.
3. Run targeted directive and commit CLI tests.
4. Run `just install` if needed and `just check`.

Exit criteria:

- Valid audit fixes are landed with focused tests.
- Superseded or invalid fixes are documented and not applied.

## Epic 6: Final Integration, Checks, And Cleanup

Goal: ensure all recovered work is coherent across repos and no stale recovery artifacts remain.

Phases:

1. Cross-repo status audit:
   - `sase_102`, sibling dirty workspaces, `../sase-core`, and `~/.local/share/chezmoi`.
   - Confirm no useful stash or dirty diff remains unaccounted for.
2. Full verification:
   - SASE `just check`.
   - Rust core full check path.
   - Chezmoi `just check`.
   - Directive and bead cross-repo search checks.
3. Documentation and state reconciliation:
   - Mark relevant SDD tales/epics done only after implementation and verification.
   - Update bead statuses and notes with landed commit IDs where appropriate.
4. Recovery cleanup:
   - Keep saved patches until all work is committed.
   - Drop temporary branches/stashes only after explicit confirmation that their content landed or was intentionally
     rejected.

Exit criteria:

- All audit-identified uncommitted work is either completed and verified, or explicitly rejected with rationale.
- The active repos no longer contain untriaged dirty recovery diffs.
- SDD and bead metadata match the actual implementation state.

## Suggested Execution Order

1. Epic 0: snapshot and classify.
2. Epic 1: small SASE TUI recovery.
3. Epic 2: directive syntax migration.
4. Epic 3: bead model routing.
5. Epic 4: chezmoi automation recovery.
6. Epic 5: audit improvement fixes.
7. Epic 6: final integration and cleanup.

This order lands low-risk SASE-only fixes first, then resolves the `%t` directive conflict before any generated prompts
or configs depend on directive spelling, then tackles bead model routing and automation work with the shared semantics
already stable.
