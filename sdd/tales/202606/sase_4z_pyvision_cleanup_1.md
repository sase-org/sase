---
create_time: 2026-06-19 12:33:27
status: done
prompt: sdd/prompts/202606/sase_4z_pyvision_cleanup_1.md
---
# Plan: Finish sase-4z Pyvision Cleanup

## Context

The `sase-4z` epic implementation has landed across the main Python/TUI repo, the sibling Rust core/LSP repo, and the
Neovim plugin. The remaining issue is post-epic cleanup: `Justfile` still carries a `sase-4z` pyvision allowance for the
public helper `clear_vcs_project_completion_cache`, and existing cleanup notes say that helper is test-only after the
feature work.

## Goal

Remove the temporary public API and pyvision epic allowance so the epic can be closed cleanly and `just pyvision` can
run without relying on open-epic exceptions.

## Steps

1. Make the VCS project completion cache-clear helper private, update module documentation/exports, and keep tests using
   the private reset helper.
2. Remove the `sase-4z(clear_vcs_project_completion_cache)` pyvision allowance from `Justfile`.
3. Run the focused VCS project completion Python tests and `just pyvision`.
4. If verification passes, close the epic bead `sase-4z`.
