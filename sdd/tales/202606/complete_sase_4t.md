---
create_time: 2026-06-17 16:28:59
status: done
prompt: sdd/prompts/202606/complete_sase_4t.md
---
# Plan: Complete verification fixes for sase-4t

## Context

Verification of the closed child beads and commits for `sase-4t` found that the main backend, UI, keymap, help, and
visual work exists, but a few edge cases do not fully satisfy the epic's Phase 3 acceptance language:

- partial multi-prompt and partial fan-out failure toasts are durable-log backed but still omit the shared `,L` hint;
- repeat name-collision failures persist a record but still return the raw collision message without the shared `,L`
  hint;
- bulk per-changespec item failures for missing project files or workspace allocation errors only increment a failure
  counter and do not write explicit `bulk` launch-failure records.

## Steps

1. Patch the remaining failure-message gaps so partial multi-prompt, partial fan-out, and repeat name-collision failures
   use the shared Log panel hint.
2. Add explicit `log_launch_failure(kind="bulk", ...)` calls for bulk item-level missing-project-file and
   workspace-allocation failures, preserving the existing bulk summary behavior.
3. Add focused tests that cover those edge cases and assert both user-facing messages and persisted log records.
4. Run focused tests for launch-failure logging and related fan-out behavior, then run the required broader checks for
   any modified files.
5. Close the `sase-4t` epic bead as the final workflow step after verification passes.
