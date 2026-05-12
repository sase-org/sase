---
create_time: 2026-05-12 18:26:18
status: wip
prompt: sdd/prompts/202605/sase_37_completion.md
---
# sase-37 Completion Plan

## Context

Verification found that the `sase-37` epic is still open and child bead `sase-37.1` is still in progress. Later child
beads are closed and their commit notes point to archive index, query, CLI, modal, lifecycle, and facade work that
exists in the current codebase. The remaining gap is Phase 0: TUI revive still calls `remove_bundle_by_identity`, which
destructively deletes preserved archive bundles after artifacts are restored.

## Plan

1. Replace destructive TUI revive bundle cleanup with the existing `mark_bundles_revived_by_suffixes` helper for both
   single-agent and batch revive flows.
2. Keep dismissed set removal, alias cleanup, artifact restoration, logging, reload, and selection behavior unchanged.
3. Update revive tests to assert preserved archive marking instead of bundle deletion, including parent/child suffix
   coverage for single and batch revive.
4. Run focused revive tests, then run the repository check suite after ensuring the workspace is installed.
5. Close child bead `sase-37.1`, then close epic bead `sase-37`.
6. Run `just pyvision` after closing the epic bead.
7. Update `sdd/epics/202605/agent_archive_query.md` frontmatter `status` to `done`.
