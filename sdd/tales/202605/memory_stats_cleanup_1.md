---
create_time: 2026-05-22 23:46:25
status: done
---
# Memory Stats Cleanup Plan

## Context

The `sase-3z` epic work is implemented and all child beads are closed, but closing the epic surfaced one post-close
`just pyvision` issue: `MemoryStats` is still a public symbol in `src/sase/memory/inventory.py` even though it is only
used internally and imported by a focused test. The epic plan file also still needs the requested `status: done`
frontmatter update.

## Plan

1. Make the inventory stats dataclass private to the memory inventory module and update references so the public API
   still exposes stats values through `MemoryInventory.loaded_stats` and `MemoryFileEntry.stats`.
2. Remove the focused test's public import of the stats class and assert the returned stats fields instead.
3. Add `status: done` to `sdd/epics/202605/memory_command_1.md` frontmatter.
4. Run focused tests for memory inventory and memory CLI handling, then run the required repository checks after
   installing the workspace.
5. Close bead `sase-3z` as the final lifecycle step, verify it is closed, and run `just pyvision` after closure.
