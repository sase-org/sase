---
create_time: 2026-06-23 14:22:58
status: done
prompt: sdd/prompts/202606/reasoning_effort_pyvision_cleanup_2.md
---
# Reasoning Effort Pyvision Cleanup Plan

## Context

`just pyvision` after closing `sase-55` reported one remaining unused public symbol: `get_default_effort` in
`src/sase/llm_provider/config.py`. The function is now only an implementation detail of `resolve_effective_effort`, so
the public surface should be collapsed before the epic is closed.

## Plan

1. Rename `get_default_effort` to a private helper and update internal references.
2. Update tests and docs that refer to the public helper name.
3. Run focused tests for default-effort resolution and provider invocation.
4. Run `just pyvision` after the cleanup.
5. Update the epic plan frontmatter to `status: done`.
6. Run the required repo check after file changes.
7. Close `sase-55`.
