---
create_time: 2026-06-23 07:14:03
status: done
prompt: sdd/prompts/202606/agent_restore_delete_saved_group.md
---
# Plan: `ctrl+d` to delete a saved agent group from the Agent Restore panel

## Goal

Add a `ctrl+d` keymap to the **Agent Restore** panel (the `SavedAgentGroupRevivalModal`) that deletes the
currently-highlighted **saved agent group** after a y/n confirmation. The keymap is only meaningful when a
_Saved-groups_ row is highlighted; it is a no-op on _Recent dismissals_ rows, headings, separators, the "Load more" row,
and "Custom revival search...".

### Decisions (already confirmed with the user)

- **Scope (Q1):** Saved groups only (`group:`-prefixed rows). Recent dismissals are never deleted by this keymap.
- **After delete (Q2):** Stay in the panel and refresh the list in place — remove the row, re-highlight a sensible
  neighbor, keep the modal open so the user can delete more.
- **Confirm popup (Q3):** Reuse the generic `ConfirmActionModal` (title + message + Yes(y)/No(n)). The message includes
  the group's display title and states the action cannot be undone.

## Background / current state

- **Panel:** `src/sase/ace/tui/modals/saved_agent_group_revival_modal.py` — `SavedAgentGroupRevivalModal` (titled "Agent
  Restore"). Rows:
  - Saved groups → option ids `group:<group_id>`, summaries in `self._groups`.
  - Recent dismissals → option ids `recent:<group_id>`, summaries in `self._recent_groups`.
  - Sentinels: `heading:saved`, `heading:recent`, `sep:1`, `sep:2`, `empty:saved`, `empty:recent`, `load-more`,
    `custom-search`.
  - Helpers already exist: `_current_highlighted_option_id()`, `_group_location_from_option()`,
    `_group_id_from_option(prefix=...)`, `_summary_for_group_id(location=...)`,
    `_rebuild_options(highlighted_option_id=...)`, `_update_hints()` / `_hints_text()`.
  - The modal receives behavior via injected callbacks in `__init__` (`page_loader`, `group_loader`,
    `recent_group_loader`). We will add a delete callback in the same style.
- **Confirm modal:** `src/sase/ace/tui/modals/confirm_action_modal.py` — `ConfirmActionModal(title, message)` is a
  `ModalScreen[bool]`; pushed with `self.app.push_screen(modal, callback)` where the callback receives `bool | None`
  (`True` = Yes, `False`/`None` = No). This is the same pattern used by quit/kill/delete confirmations elsewhere.
- **Wiring:** `src/sase/ace/tui/actions/agents/_revive_flow.py::_revive_agent()` constructs the modal and passes the
  loader callbacks. This is where we inject the delete callback.
- **Backend gap:** There is currently **no delete operation** for saved agent groups. The store only supports save /
  list / load / mark-revived / record-recent (with implicit pruning of the _recent_ store). We must add an explicit
  "delete one saved group" backend operation.

### Backend boundary (important)

Per `memory/rust_core_backend_boundary.md`, deleting a saved agent group is **core backend behavior**: a CLI, web app,
or other frontend would need it to match the TUI. It therefore belongs in the Rust core (`sase-core`), exposed through
the `sase_core_rs` binding, with a Python fallback in the facade — mirroring every other saved-group operation. This
plan adds the operation across the full stack (Rust core → PyO3 binding → Python facade → re-export → TUI), not just in
Python.

The saved-group record is **lightweight metadata** that references per-agent dismissed bundles. Deleting a saved group
removes only the group record; the underlying dismissed agent bundles are untouched and remain individually revivable
via "Custom revival search". The confirmation message must say this honestly.

## Changes

### A. Rust core — add the delete operation (`sase-core` repo)

> Access the linked `sase-core` repo via `sase workspace open -p sase-core -r "<reason>" <N>` using the primary
> workspace number; operate only under the path it prints.

1. **`crates/sase_core/src/agent_group_archive/mod.rs`**
   - Add a public function next to `mark_dismissed_agent_group_revived`:
     `delete_dismissed_agent_group(root: &Path, group_id: &str) -> Result<bool, String>`.
   - Behavior: validate the id via the existing `group_path()` (reuses `validate_group_id`), then `fs::remove_file`.
     Return `Ok(true)` when removed, `Ok(false)` when the file was already absent (`ErrorKind::NotFound`), `Err(..)` for
     other IO errors. Follow the same NotFound-tolerant pattern already used in `prune_recent_dismissed_agent_groups`.
   - Add a unit test in the existing `#[cfg(test)] mod tests`: save two groups, delete one, assert it returns `true`,
     the file is gone, the other group still lists; deleting a missing id returns `false`; (optionally) an invalid id
     returns `Err`.

2. **`crates/sase_core_py/src/lib.rs`**
   - Import `delete_dismissed_agent_group as core_delete_dismissed_agent_group` in the `agent_group_archive` use-block
     (alongside the other `core_*` group imports).
   - Add `py_delete_dismissed_agent_group(py, root: &str, group_id: &str) -> PyResult<bool>` mirroring
     `py_load_dismissed_agent_group` (use `py.allow_threads`, map the `String` error via `PyValueError::new_err`).
     Return the `bool` directly (no JSON conversion needed).
   - Register it in `init_module` next to the other `py_*_dismissed_agent_group*` registrations:
     `m.add_function(wrap_pyfunction!(py_delete_dismissed_agent_group, m)?)?;`

3. Run the Rust crate's tests + lint (cargo test / clippy / fmt for the affected crates) and rebuild the `sase_core_rs`
   extension so the new binding is importable.

### B. Python facade — expose delete (`sase` repo)

4. **`src/sase/ace/dismissed_agent_groups.py`**
   - Add `delete_dismissed_agent_group(group_id: str, *, groups_dir: Path | None = None) -> bool`. Resolve
     `root = groups_dir or _default_dismissed_agent_groups_dir()`, then try the binding via
     `_rust_group_archive_binding("delete_dismissed_agent_group")`; on `(ImportError, AttributeError)` fall back to
     `_delete_dismissed_agent_group_python`. (The wire-capability gate is additive-safe: an older binding that lacks
     this function simply triggers the Python fallback.)
   - Add `_delete_dismissed_agent_group_python(root, group_id) -> bool` using `_group_path(root, group_id)` +
     `Path.unlink(missing_ok=True)`; return whether the file existed before removal (so semantics match the Rust
     `bool`).
   - Add `"delete_dismissed_agent_group"` to `__all__`.

5. **`src/sase/ace/dismissed_agents.py`** (the re-export/adapter module the TUI imports from)
   - Import `delete_dismissed_agent_group as _delete_dismissed_agent_group_impl` from `.dismissed_agent_groups`.
   - Add the thin wrapper used by the rest of the app: `delete_dismissed_agent_group(group_id: str) -> bool` →
     `_delete_dismissed_agent_group_impl(group_id, groups_dir=_dismissed_agent_groups_dir())`.

### C. Modal — keymap, confirm flow, in-place refresh (`sase` repo)

6. **`src/sase/ace/tui/modals/saved_agent_group_revival_modal.py`**
   - **Constructor:** add `delete_callback: Callable[[str], bool] | None = None` and store as `self._delete_callback`.
     (Default `None` keeps existing callers/tests working.)
   - **Binding:** add `Binding("ctrl+d", "delete_group", "Delete", priority=True)` to `BINDINGS`. `priority=True`
     mirrors the existing `pagedown` binding so it fires even while the inner `OptionList` has focus. (Verify there is
     no conflicting global/app `ctrl+d`; none found in the modal's own bindings or `OptionList` defaults.)
   - **`action_delete_group()`:** Resolve the highlighted row via `_current_highlighted_option_id()`. If its location
     (`_group_location_from_option`) is not `"saved"`, return immediately (no-op → enforces "saved groups only").
     Extract `group_id = _group_id_from_option(option_id, prefix=_GROUP_PREFIX)`; if `None`, return. Look up the summary
     (`_summary_for_group_id(group_id, location="saved")`) to build the display title (`summary.name or summary.title`,
     with a safe fallback). Push `ConfirmActionModal(title="Delete Saved Agent Group", message=...)` with a callback
     that, on `True`, calls `_perform_delete(group_id)`. The message includes the group title and notes the dismissed
     agents themselves are not deleted and that the action cannot be undone.
   - **`_perform_delete(group_id)`:**
     - If `self._delete_callback is None`, `self.notify(..., severity="warning")` and return.
     - Compute the post-delete highlight target **before** mutating
       `self._groups** via a new helper `_next_highlight_after_saved_delete(group_id)`: prefer the next saved group, else the previous saved group, else (no saved groups remain) `load-more`if a cursor exists, else the first recent row, else`custom-search`.
     - Call `deleted = self._delete_callback(group_id)` in `try/except`; on exception, `self.notify(error)` and return
       without mutating state.
     - Remove the group from `self._groups` (filter by `group_id`) and drop its cached entry from `self._loaded_groups`
       (`group:<id>` key). Clear any active jump hints.
     - `self._rebuild_options(highlighted_option_id=<target>)`, then refocus the option list, refresh the preview for
       the new highlight, and `self._update_hints()` (the saved/recent counts changed).
     - `self.notify("Deleted saved group '<title>'")` (and a `severity="warning"` notice if `deleted is False`, i.e. it
       was already gone — still refresh).
   - **Hint discoverability:** surface `^d: delete` in the modal's hint line. Chosen approach: show it **conditionally**
     — call `self._update_hints()` from `on_option_list_option_highlighted` and have `_hints_text()` append
     `" | ^d: delete"` only when the highlighted row is a saved group. This matches the "active only on saved rows"
     semantics and the project's conditional-keymap convention. (The existing jump-mode guard in `_update_hints` is
     preserved.) This will change the saved-groups PNG snapshot, which is regenerated as an intentional visual change.

### D. Wiring (`sase` repo)

7. **`src/sase/ace/tui/actions/agents/_revive_flow.py::_revive_agent()`**
   - Import `delete_dismissed_agent_group` from `....dismissed_agents`.
   - Define `_delete_group(group_id: str) -> bool: return delete_dismissed_agent_group(group_id)`.
   - Pass `delete_callback=_delete_group` to the `SavedAgentGroupRevivalModal(...)` constructor.

## Conventions to honor

- **`just check`:** After the `sase`-repo changes, run `just install` then `just check` (ephemeral workspaces may have
  stale deps). For `sase-core`, run that crate's own test/lint and rebuild the binding.
- **Help popup:** `help_modal.py` does **not** document the Agent Restore modal (verified — no references); this modal
  self-documents via its hint line, which we update. No `help_modal.py` change required. (Re-verify during
  implementation.)
- **Footer convention:** `keybinding_footer.py` governs the _main TUI_ footer, not modal screens, so it does not apply
  here; the modal's own hint line is the right surface.
- **Short options rule** is about `sase` CLI options, not Textual key bindings — N/A.
- **Uniform runtimes:** no runtime-specific branching is introduced.

## Tests

- **Rust** (`agent_group_archive/mod.rs`): unit test for `delete_dismissed_agent_group` (deletes existing → `true`,
  leaves siblings; missing → `false`).
- **Python facade** (`tests/test_dismissed_agent_groups.py`): add a round-trip test that saves a group, calls
  `delete_dismissed_agent_group`, and asserts the file is gone and the group no longer lists; assert deleting a missing
  id returns `False`. Add a Python-fallback variant by patching `sase.ace.dismissed_agent_groups.require_rust_binding`
  to raise `AttributeError` (mirroring the existing fallback tests), and patch
  `sase.ace.dismissed_agents._DISMISSED_AGENT_GROUPS_DIR` to a tmp dir.
- **Modal** (`tests/ace/tui/modals/test_saved_agent_group_revival_modal.py`), using the existing `_TestApp`/pilot
  pattern and a fake `delete_callback`:
  - `ctrl+d` on a saved group opens `ConfirmActionModal`; pressing `y` invokes the callback with the right `group_id`,
    removes the row, keeps the modal open, and re-highlights a neighbor; counts update.
  - Pressing `n` (or escape) cancels: callback not invoked, row remains.
  - `ctrl+d` on a recent row / heading / `custom-search` is a no-op (no confirm modal, callback not invoked).
  - Deleting the only/last saved group falls back to a recent row or `custom-search` and the "Saved groups (N)" count
    goes to 0.
  - Conditional hint: `^d: delete` appears when a saved group is highlighted and not on a recent/sentinel row.
- **Visual snapshots:** regenerate the affected saved-group PNG golden(s) (`tests/ace/tui/visual/...saved_groups...`)
  with `--sase-update-visual-snapshots` to absorb the new hint text; review the diff to confirm only the hint line
  changed.
- Re-run `just test` / `just check` and the `sase-core` crate tests.

## Out of scope / non-goals

- Deleting **recent dismissals** (Q1: saved only).
- Deleting the underlying per-agent dismissed **bundles** (only the group metadata record is removed).
- Multi-select / bulk delete, undo, or a dedicated styled delete modal (Q3 reuses the generic confirm modal).
- Closing the panel after delete (Q2: stay open).

## Risk notes

- Until the rebuilt `sase_core_rs` binding ships, the facade uses the Python fallback, so the feature is functional
  regardless; the additive binding does not affect the wire-capability probe.
- `priority=True` means `ctrl+d` is captured by the modal even when the `OptionList` is focused; while in jump mode the
  existing `on_key` interceptor will treat `ctrl+d` as an unrecognized jump key and simply exit jump mode (acceptable
  edge case).
