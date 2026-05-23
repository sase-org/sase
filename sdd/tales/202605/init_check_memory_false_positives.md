---
create_time: 2026-05-23 10:42:11
status: done
prompt: sdd/prompts/202605/init_check_memory_false_positives.md
---
# Plan: Fix `sase init --check` Memory False Positives

## Problem

After `sase init memory` writes generated memory files, the project deploy path runs the configured precommit command
(`just fix`). In this repository, that formats Markdown with Prettier using `--prose-wrap=always --print-width=120`. The
read-only planner for `sase init --check` compares files against the raw generated Markdown instead of the formatted
bytes that remain on disk. That makes `memory/short/sase.md` and `memory/README.md` look stale immediately after the
initializer has already converged them.

The same command also lacks the requested `-c` alias for `--check`.

## Approach

1. Make generated memory Markdown deterministic in the same shape that the repo formatter leaves on disk.
   - Add a small local formatter for the generated memory Markdown surface, rather than invoking Prettier from check
     mode.
   - Keep code fences, headings, blank lines, and generated bullets stable.
   - Ensure generated Markdown files end with a newline.
2. Use the canonical formatted content for both planning and writing.
   - `sase init memory` writes the same bytes that `sase init --check` expects.
   - Project precommit formatting becomes idempotent instead of creating a second representation.
3. Add `-c` as a short alias for bare `sase init --check`.
   - Update parser tests to cover both `--check` and `-c`.
   - Update CLI/docs references where the option table currently lists only `--check`.
4. Add focused regression coverage.
   - Prove `plan_init_memory()` is empty immediately after `run_init_memory()` when a precommit-like Markdown format has
     been applied to generated memory files.
   - Verify generated memory README and project memory are already Prettier-compatible enough for the repo's check.
5. Verify.
   - Run focused init/parser tests first.
   - Run `just install` if needed, then `just check` because implementation files will change.

## Constraints

Do not edit repository memory files (`memory/...`) unless explicitly approved. The implementation should fix the
generator and check behavior without hand-editing generated memory content.
