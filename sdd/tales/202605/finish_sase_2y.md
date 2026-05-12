---
create_time: 2026-05-11 21:54:20
status: done
prompt: sdd/prompts/202605/finish_sase_2y.md
---
# Finish sase-2y Verification Closeout

## Context

The `sase-2y` epic has shipped phase 1 through phase 4 commits, but phase 5 remains `in_progress` and has no bead-tagged
commit. Phase 6 is closed with notes claiming documentation and final verification, yet the current `docs/ace.md` does
not document the AXE sidebar taxonomy, dynamic no-wrap behavior, or controlled-output highlighting/fallback contract.

## Plan

1. Expand the AXE PNG snapshot suite with deterministic cases that visibly cover the missing phase 5 acceptance points:
   long labels forcing dynamic sidebar width, selected lumberjack/chop/background-command rows, controlled highlighted
   chop output, and a constrained-width no-wrap/ellipsis scenario.
2. Update `docs/ace.md` so the Axe tab section describes the row taxonomy, dynamic single-line sidebar sizing, and
   controlled-output highlighting with ANSI fallback for arbitrary command/script output.
3. Mark `sdd/epics/202605/axe_tab_visual_redesign.md` frontmatter `status` as `done` after the implementation is
   complete.
4. Run the focused visual update and verification commands for the new/changed AXE PNG snapshots, then run the focused
   AXE/bgcmd test set and the repository check required after code/docs changes.
5. Close remaining child bead `sase-2y.5`, close epic bead `sase-2y`, then run `just pyvision` after the epic is closed.
