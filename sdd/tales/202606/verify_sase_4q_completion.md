---
create_time: 2026-06-16 12:05:54
status: done
prompt: sdd/prompts/202606/verify_sase_4q_completion.md
---
# Verify and Complete Prompt Stash Epic `sase-4q`

## Context

The `sase-4q` prompt-stash epic has four closed child phase beads and feature commits in both the Python/TUI repo and
the `sase-core` sibling repo. Source review confirmed the main feature is implemented: Rust-backed prompt-stash
persistence, Python wire/facade types, prompt-bar stash capture, top-bar count indicator, restore picker, pop/load
semantics, focus-time badge refresh, and visual coverage.

One completion cleanup item remains: `Justfile` still whitelists `rewrite_prompt_stash` with
`--epic-symbol 'sase-4q(...)'`, and the Python facade's `rewrite_prompt_stash` wrapper is only used by tests. This is
temporary epic-open scaffolding and should not survive closing the epic.

## Plan

1. Remove the unused Python `rewrite_prompt_stash` facade wrapper and its `__all__` export.
2. Remove the Python facade test that exists only to exercise that unused wrapper; Rust core keeps the real
   `rewrite_prompt_stash` operation and its integration coverage.
3. Remove the stale `sase-4q` pyvision epic-symbol whitelist and associated temporary comment from `Justfile`.
4. Run focused verification for prompt-stash unit/widget/modal/visual behavior and `just pyvision` without the
   whitelist.
5. Close epic bead `sase-4q`.
6. After closing the epic, run `just pyvision`, run the required repo checks for the file changes, and update the epic
   plan frontmatter status to `done`.
