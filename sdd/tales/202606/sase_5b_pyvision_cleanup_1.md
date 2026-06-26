---
create_time: 2026-06-26 17:45:15
status: done
prompt: sdd/prompts/202606/sase_5b_pyvision_cleanup_1.md
---
# Plan: Finish sase-5b Pyvision Cleanup

## Goal

Finish the post-close validation cleanup for `sase-5b` by removing the remaining unused public API reported by
`just pyvision`, while preserving the inlined short-term memory behavior that the epic implemented.

## Steps

1. Make the memory-title extraction helper private or otherwise remove it from the public module surface, updating any
   direct tests/imports to use the intended internal name.
2. Re-run the focused inline-memory tests and `just pyvision` to verify the unused public symbol is gone.
3. Re-run the memory initialization checks for the SASE repo and bob-cli to ensure generated instruction files remain
   clean and idempotent.
4. Mark the original epic plan frontmatter as `status: done` and run the required repository validation.
5. Close `sase-5b` as the final bead step, or confirm it remains closed if it was already closed before this cleanup.
