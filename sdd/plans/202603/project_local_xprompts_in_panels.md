---
create_time: 2026-03-22 20:55:53
status: done
prompt: sdd/prompts/202603/project_local_xprompts_in_panels.md
---

# Plan: Show Project-Local sase.yml XPrompts in TUI Panels

## Problem

Two related issues with xprompt panels in the `sase ace` TUI:

1. **Snippet panel (`#@`)**: When a VCS workflow tag like `#gh:sase` is embedded in the prompt text, typing `#@` opens
   the xprompt selection panel but does NOT show xprompts from that repo's local `sase.yml` (e.g., `#sase/docs`).

2. **Browser panel (`#` key)**: The xprompt browser modal shows no project-local xprompts at all. It should show ALL
   xprompts from ALL known projects' local `sase.yml` files.

## Root Cause

The TUI calls `set_include_local_config(False)` at startup (`src/sase/main/ace_handler.py:18`), which prevents
`load_xprompts_by_source()` from ever returning `"local_config"` entries. This is intentional -- the TUI shouldn't
inherit CWD's repo-level config for its own behavior. But it means project-local xprompts defined in each repo's
`sase.yml` are invisible to the xprompt panels.

Additionally:

- The snippet panel gets its project from `_prompt_context`, which is "home" when using VCS-prefixed prompts. It doesn't
  look at the embedded VCS tag.
- The browser panel passes no project at all to `XPromptBrowserModal()`.

## Architecture

### Where project sase.yml files live

Each project has a `.gp` file at `~/.sase/projects/{name}/{name}.gp` containing a `WORKSPACE_DIR:` line pointing to the
primary repo directory. The repo directory contains the project's `sase.yml` with xprompts in its `xprompts:` section.

### Current xprompt loading flow

```
get_all_prompts(project) -> get_all_xprompts(project) + get_all_workflows(project)
  -> _load_xprompts_from_config(project)
    -> load_xprompts_by_source()  <-- skips local_config when _include_local_config=False
```

## Implementation Plan

### Phase 1: Add project workspace discovery utility

**File: `src/sase/xprompt/loader.py`**

Add a function to parse `.gp` files and find workspace directories:

```python
def get_known_project_workspaces() -> dict[str, Path]:
    """Enumerate all known projects and their primary workspace directories.

    Parses ~/.sase/projects/*/*.gp files for WORKSPACE_DIR lines.
    Returns {project_name: workspace_dir_path}.
    """
```

This is a simple text parse of `.gp` files -- no network, no git, no VCS resolution needed. Fast enough for synchronous
use.

### Phase 2: Add project-local xprompt loading

**File: `src/sase/xprompt/loader.py`**

Add functions to load xprompts directly from a project's sase.yml, bypassing `_include_local_config`:

```python
def load_project_local_xprompts(workspace_dir: Path, project: str) -> dict[str, XPrompt]:
    """Load xprompts from a project's sase.yml file.

    Reads <workspace_dir>/sase.yml directly (bypasses _include_local_config).
    Returns xprompts namespaced with {project}/.
    """

def get_all_project_local_prompts() -> dict[str, Workflow]:
    """Load xprompts from ALL known projects' sase.yml files.

    Calls get_known_project_workspaces() then load_project_local_xprompts()
    for each. Returns unified Workflow dict.
    """
```

Note: sase.yml xprompts are simple key-value entries (name -> content string or dict with `input:` + `content:`), so
they become XPrompt objects via `parse_xprompt_entries()`, then get converted to single-step Workflows via
`xprompt_to_workflow()`.

### Phase 3: Fix snippet panel (`#@`) to detect embedded VCS project

**File: `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`**

Modify `on_prompt_input_bar_snippet_requested()`:

1. Get the current prompt text from the text area widget
2. Call `extract_vcs_workflow_tag()` on it to detect a VCS tag like `#gh:sase`
3. If found, extract the project name from the tag (parse the ref portion after the workflow type prefix)
4. Look up workspace dir via `get_known_project_workspaces()`
5. Load that project's local xprompts
6. Pass them to `XPromptSelectModal` as additional xprompts

**File: `src/sase/ace/tui/modals/xprompt_select_modal.py`**

Add an `extra_prompts: dict[str, Workflow] | None = None` parameter to the constructor. Merge these into `_prompts` /
`_all_items`.

### Phase 4: Fix browser panel (`#` key) to show all projects

**File: `src/sase/ace/tui/modals/xprompt_browser_modal.py`**

Modify `_load_xprompts()`:

1. After loading the normal `get_all_prompts()`, also call `get_all_project_local_prompts()`
2. Merge project-local xprompts into the items list
3. Classify their source as `"Project ({project_name}) sase.yml"` for grouping

**File: `src/sase/ace/tui/modals/xprompt_browser_helpers.py`**

May need to update `classify_source()` to handle the new source paths (project sase.yml files).

### Phase 5: Extract project name from VCS tag

**File: `src/sase/xprompt/_parsing.py`** (or a new helper)

Add a function to extract the project name from a VCS workflow tag string without doing full VCS resolution:

```python
def extract_project_from_vcs_tag(tag: str) -> str | None:
    """Extract project name from a VCS tag like '#gh:sase ' -> 'sase'."""
```

This avoids the overhead of `resolve_ref()` -- we just need the ref portion of the tag, then check if it matches a known
project in `~/.sase/projects/`.

### Phase 6: Tests

Add tests for:

- `get_known_project_workspaces()` -- mock `.gp` files
- `load_project_local_xprompts()` -- mock sase.yml with xprompts
- `get_all_project_local_prompts()` -- integration of the above
- `extract_project_from_vcs_tag()` -- various tag formats
- Snippet modal receiving extra prompts
- Browser modal including project-local xprompts

## Performance Considerations

- **Browser panel startup**: Scanning `~/.sase/projects/` (typically <10 projects), parsing `.gp` text files, and
  loading YAML files -- all local file I/O, should complete in <50ms. No performance concern.
- **Snippet panel**: Same as above but for a single project. Negligible.
- **Caching**: `get_known_project_workspaces()` could be cached, but given the low cost and the fact that projects can
  be added/removed, keep it uncached for correctness.

## Key Files

| File                                                     | Change                                                                                                   |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `src/sase/xprompt/loader.py`                             | Add `get_known_project_workspaces()`, `load_project_local_xprompts()`, `get_all_project_local_prompts()` |
| `src/sase/xprompt/_parsing.py`                           | Add `extract_project_from_vcs_tag()`                                                                     |
| `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py` | Detect VCS tag in prompt, pass extra xprompts to snippet modal                                           |
| `src/sase/ace/tui/modals/xprompt_select_modal.py`        | Accept `extra_prompts` parameter                                                                         |
| `src/sase/ace/tui/modals/xprompt_browser_modal.py`       | Load and display all project-local xprompts                                                              |
| `src/sase/ace/tui/modals/xprompt_browser_helpers.py`     | Handle new source classification                                                                         |
