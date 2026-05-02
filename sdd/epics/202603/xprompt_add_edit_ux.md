---
bead_id: sase-5
status: done
prompt: sdd/prompts/202603/xprompt_add_edit_ux.md
---

# Plan: Improve XPrompt Add/Edit UX in `sase ace` TUI

## Goal

Overhaul the `<c-o>` (add) and `enter` (edit) keymaps in the xprompt browser modal to support:

- Location-aware xprompt creation (select from all known locations)
- Proper .md vs .yml file handling (with workflow YAML templates)
- Editing ALL xprompts (including plugin/built-in)
- Git commit & push integration after editing

## Phase 1: Location selector modal for `<c-o>` add flow

**Objective**: Replace the current `AddXPromptModal` (simple text input with `.xprompts/` default) with a two-step flow:
first select a location, then enter a filename if needed.

### New modal: `XPromptLocationModal`

Create `src/sase/ace/tui/modals/xprompt_location_modal.py` — a modal that presents the user with a list of all known
xprompt locations. The modal should use an `OptionList` (similar to existing modals like `project_select_modal.py`).

**Location discovery function**: Create `get_all_xprompt_locations()` in this module (or a shared utility). It should
return a list of location entries, each with:

- `label`: Human-readable name (e.g., "CWD .xprompts/", "User sase.yml")
- `path`: Absolute path to the directory or file
- `location_type`: Either `"directory"` (xprompts dir — user will create .md/.yml files) or `"config"` (sase.yml/
  default_config.yml — user will edit inline xprompts)

**Locations to enumerate** (in display order):

1. **xprompts directories** (type: `"directory"`):
   - `.xprompts/` (CWD) — always show, even if doesn't exist yet
   - `xprompts/` (CWD) — only if exists
   - `~/.xprompts/` — always show
   - `~/xprompts/` — only if exists
   - `~/.config/sase/xprompts/{project}/` — only if project detected

2. **Config files** (type: `"config"`):
   - `~/.config/sase/sase.yml` — always show
   - Each `~/.config/sase/sase_*.yml` overlay — only existing ones
   - `./sase.yml` (CWD) — only if exists

3. **Plugin xprompts directories** (type: `"directory"`):
   - For each plugin discovered via `discover_plugin_resources("sase_xprompts")`, resolve the actual filesystem path of
     its `xprompts/` directory using `importlib.resources.files(module).joinpath("xprompts")`. Use
     `importlib.resources.as_file()` to get the real path. Show as "Plugin ({short_name}) xprompts/".

4. **Built-in locations** (type: `"directory"` and `"config"`):
   - `src/sase/xprompts/` (the package xprompts dir) — resolved via `get_sase_package_xprompts_dir()`
   - `src/sase/default_config.yml` — resolved via `importlib.resources`
   - Plugin `default_config.yml` files — for each plugin via `discover_plugin_resources("sase_config")`

**Modal behavior**:

- Show all locations in an OptionList with group headers (directories, config files, plugins, built-in)
- Each entry shows the display path and whether it exists yet
- `enter` selects the location and dismisses with the selection
- `escape` cancels

### Wire into `action_add_xprompt()`

Update `XPromptBrowserModal.action_add_xprompt()` to:

1. Push `XPromptLocationModal`
2. On selection:
   - If `location_type == "directory"`: push a second modal asking for filename (see Phase 2)
   - If `location_type == "config"`: open the config file in `$EDITOR` directly

### Files to create/modify

- **Create**: `src/sase/ace/tui/modals/xprompt_location_modal.py`
- **Modify**: `src/sase/ace/tui/modals/xprompt_browser_modal.py` — update `action_add_xprompt()`
- **Modify**: `src/sase/ace/tui/modals/__init__.py` — export new modal
- **Modify**: `src/sase/ace/tui/styles.tcss` — add styles for the new modal if needed

---

## Phase 2: Filename input and .md/.yml template handling

**Objective**: When the user selects a directory location, prompt for a filename with proper validation, then create the
file with the right template content.

### New modal: `XPromptFilenameModal`

Create `src/sase/ace/tui/modals/xprompt_filename_modal.py` — a small modal with:

- A label showing the selected directory
- An `Input` for the filename
- Validation: must end with `.md` or `.yml` (show error label if not)
- `enter` submits, `escape` cancels
- Dismisses with the full path (directory + filename) or None

### File creation logic

Update `XPromptBrowserModal._create_and_edit_xprompt()` to handle both .md and .yml:

- **If `.md`**: Create with the existing skeleton:

  ```markdown
  # {name}

  Your xprompt content here.
  ```

- **If `.yml`**: Create with a workflow YAML template, reusing the pattern from
  `src/sase/ace/tui/actions/agent_workflow/_editor.py:99-106`:

  ```yaml
  # yaml-language-server: $schema={schema_path}

  steps:
    - name: main
      prompt: |
        <your prompt here>
  ```

  Where `schema_path` is resolved via `get_sase_package_xprompts_dir() / "workflow.schema.json"`.

### Files to create/modify

- **Create**: `src/sase/ace/tui/modals/xprompt_filename_modal.py`
- **Modify**: `src/sase/ace/tui/modals/xprompt_browser_modal.py` — update `_create_and_edit_xprompt()` for .yml handling
- **Modify**: `src/sase/ace/tui/modals/__init__.py` — export new modal

---

## Phase 3: Make all xprompts editable (including plugin/built-in)

**Objective**: Allow editing ANY xprompt, even plugin and built-in ones. Resolve plugin source paths
(`"plugin:module/file"`) to actual filesystem paths.

### Changes to `_classify_source()`

Update `_classify_source()` in `xprompt_browser_modal.py`:

- Change `is_editable` to `True` for ALL sources (plugins, built-in, default_config)
- Keep the category labels as-is for display purposes

### Changes to `action_edit_xprompt()`

Update the edit action to resolve ALL source paths to actual file paths:

- **`"plugin:module_name/filename"`**: Resolve the plugin module's xprompts directory using
  `importlib.resources.files(module).joinpath("xprompts")` and `as_file()` to get the real filesystem path. Then append
  the filename portion.
- **`"plugin_config:module_name"`**: Resolve the plugin module's `default_config.yml` using
  `importlib.resources.files(module).joinpath("default_config.yml")` and `as_file()`.
- **`"default_config"`**: Resolve via `importlib.resources.files("sase").joinpath("default_config.yml")`.
- **`"local_config"`**: Resolve to `./sase.yml`.
- **`"config"` and `"config_overlay:*"`**: Already handled.
- **Regular file paths**: Already handled.

### Helper function

Create `_resolve_source_to_file_path(source_path: str) -> str | None` to centralize this resolution logic. This will be
useful for both edit and the git commit flow in Phase 4.

### Files to modify

- **Modify**: `src/sase/ace/tui/modals/xprompt_browser_modal.py` — update `_classify_source()`, `action_edit_xprompt()`,
  add `_resolve_source_to_file_path()`

---

## Phase 4: Git commit & push after editing/creating xprompts

**Objective**: After the user closes their editor, if the file is under git version control, offer to commit and push.

### Git detection

Create a helper function `_get_git_root(file_path: str) -> str | None` that runs
`git -C <dir> rev-parse --show-toplevel` to check if the file is in a git repo.

### Change detection

After the editor closes, run `git -C <repo> status --porcelain -- <file>` to check if the file was modified.

### Commit flow

Create a confirmation modal (or reuse a simple yes/no pattern like `ConfirmDeleteModal`):

- "Commit changes to `<relative_path>`?"
- If confirmed:
  1. `git -C <repo> add <file>`
  2. Generate commit message: `chore: Update xprompt <name>` (for edits) or `chore: Add xprompt <name>` (for new files)
  3. `git -C <repo> commit -m <message>`
  4. Show a second confirmation: "Push to remote?"
  5. If confirmed: `git -C <repo> push` (with a notification on success/failure)

### Integration points

Update both `action_edit_xprompt()` and `_create_and_edit_xprompt()` to call the git flow after the editor subprocess
returns.

### Files to create/modify

- **Create**: `src/sase/ace/tui/modals/confirm_action_modal.py` — a generic yes/no confirmation modal (if
  `ConfirmDeleteModal` is too specific to reuse; otherwise just reuse the pattern)
- **Modify**: `src/sase/ace/tui/modals/xprompt_browser_modal.py` — add git helpers and integrate into edit/create flows

---

## Summary of phases

| Phase | Description                     | Key deliverable                                                                  |
| ----- | ------------------------------- | -------------------------------------------------------------------------------- |
| 1     | Location selector modal         | `XPromptLocationModal` — enumerate all locations, wire into `<c-o>`              |
| 2     | Filename input + .yml templates | `XPromptFilenameModal` — validate .md/.yml, create with proper templates         |
| 3     | Make all xprompts editable      | Resolve plugin/built-in source paths to real files, remove read-only restriction |
| 4     | Git commit & push integration   | Detect git repos, offer commit + push after edit/create                          |
