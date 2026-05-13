---
create_time: 2026-05-13 14:03:13
status: done
prompt: sdd/prompts/202605/sase_3a_remaining_pyvision_cleanup.md
---
# Plan: Finish sase-3a Pyvision Cleanup Verification

## Context

Verification of `sase-3a` found all child phase beads closed, but `just pyvision` still fails without epic suppressions
because several newly-private helpers are referenced directly from tests outside their defining modules. The epic
suppression list in `Justfile` also still contains stale `sase-3a(...)` entries, so the epic is not ready to close.

## Steps

1. Replace direct test imports/usages of newly-private helpers with tests that exercise the corresponding public
   behavior:
   - agent launch facade path construction
   - QA prompt formatting through public QA markdown builders
   - wait-directive detection through public directive extraction
   - TUI idle state through public activity APIs
   - bead mutation through public facade functions
   - git query parsing through public git-query facade behavior
2. Remove the stale `sase-3a(...)` `--epic-symbol` suppressions from `Justfile` once pyvision no longer needs them.
3. Run focused tests for the updated files, then run `just pyvision`.
4. Update `sdd/epics/202605/pyvision_test_only_public_symbols_cleanup.md` frontmatter to `status: done`.
5. Close the epic bead with `sase bead close sase-3a`.
6. After the epic is closed, run `just pyvision` again to confirm no now-unsuppressed unused code remains.
