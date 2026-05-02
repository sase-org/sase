---
create_time: 2026-04-15 13:17:08
status: done
prompt: sdd/prompts/202604/rewind_bang_suffix.md
---

# Plan: Support `!` suffix for rewind (`R`) keymap on CLs tab

## Problem

The `R` (rewind) keymap on the CLs tab currently always performs the full VCS workflow: claim workspace, checkout
branch, reverse-apply diffs, amend commit, then update the ChangeSpec. There's no way to do "bookkeeping only" — just
updating the ChangeSpec as if the rewind was already performed manually.

The `a` (accept) keymap already supports this via the `!` suffix (e.g., `a!` sets `skip_amend=True`), which skips the
checkout/apply/amend steps and only renumbers the ChangeSpec entries. We want the same pattern for rewind.

## Design

The user types an entry number with a `!` suffix in the rewind input bar (e.g., `3!`). This triggers a "bookkeeping
only" rewind that:

- Kills running processes (same as normal rewind)
- Validates entries (same as normal rewind)
- Skips all VCS operations (workspace claim, checkout, clean, rewind diffs, amend)
- Runs `rewind_commit_entries()` to renumber the ChangeSpec
- Adds a `REWIND` timestamp entry

This mirrors the accept `!` suffix pattern exactly.

## Changes

### Phase 1: Parse `!` suffix from rewind input

**File: `src/sase/ace/tui/actions/hints/_rewind.py`**

1. In `_process_rewind_input()`: strip a trailing `!` from `user_input` before parsing the entry number. Set a local
   `skip_vcs = True` if `!` was present. Pass `skip_vcs` to `_run_rewind_workflow()`.

2. In `_run_rewind_workflow()`: accept a `skip_vcs: bool = False` parameter. Pass it through to `_rewind_task()`.

3. In `_rewind_task()`: accept a `skip_vcs: bool = False` parameter. Pass it to `RewindWorkflow.__init__()`.

4. Update the notification message in `_run_rewind_workflow()` to append `" (bookkeeping only)"` when `skip_vcs` is
   True.

### Phase 2: Add `skip_vcs` support to `RewindWorkflow`

**File: `src/sase/workflows/rewind/workflow.py`**

1. Add `skip_vcs: bool = False` parameter to `RewindWorkflow.__init__()` and store as `self._skip_vcs`.

2. In `run()`, when `self._skip_vcs` is True:
   - Still run `_kill_running_processes()` and all validation (entry exists, entries after, has DIFF).
   - Skip the entire workspace block: no `get_first_available_axe_workspace`, no `claim_workspace`, no `chdir`, no
     `run_sase_hg_clean`, no `update_to_changespec`, no `provider.rewind()`, no `provider.amend()`.
   - Still run `rewind_commit_entries()` and `add_timestamp_entry_atomic()`.
   - Return the success/failure message with a `" (bookkeeping only)"` suffix.

   The cleanest approach: after `_kill_running_processes()` and validation, add an early-return branch for `skip_vcs`
   that runs only the bookkeeping steps (renumber + timestamp), before the workspace claim block.

### Phase 3: Update help modal

**File: `src/sase/ace/tui/modals/help_modal/bindings.py`**

1. Update the rewind help text from `"Rewind to prev commit (non-Sub/Rev)"` to `"Rewind to prev commit (! skip VCS)"` to
   document the `!` suffix, matching the style of other suffix docs.
