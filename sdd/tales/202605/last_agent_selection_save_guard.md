---
create_time: 2026-05-08 00:24:48
status: done
prompt: sdd/prompts/202605/last_agent_selection_save_guard.md
---
# Plan: Validate `project_name` On All `save_last_agent_selection()` Call Sites

## Problem & Diagnosis

`~/.sase/last_agent_selection.json` keeps getting persisted with `project_name="project"` even though no
`~/.sase/projects/project/` directory exists. Two prior fix attempts (commits `3e6eabc4` and `4d326696`) only partially
closed the gap:

- `3e6eabc4 fix: ignore stale last VCS selections` added `_last_selection_is_replayable` validation on **load** and a
  stale-clear flow in `_load_last_custom_agent_selection`.
- `4d326696 fix: prevent stale VCS replay state` added `_is_launchable_replay_project(ctx.project_name)` validation
  inside `_save_replayable_vcs_selection` only.

Five call sites currently write `last_agent_selection.json` via `save_last_agent_selection()`. Only one of them is
guarded:

| #   | File                                                               | Function                             | `project_name` source                  | Guarded? |
| --- | ------------------------------------------------------------------ | ------------------------------------ | -------------------------------------- | -------- |
| 1   | `src/sase/ace/tui/actions/agent_workflow/_entry_points.py:218-226` | `_start_agent_from_changespec_quick` | `changespec.project_basename`          | **No**   |
| 2   | `src/sase/ace/tui/actions/agent_workflow/_entry_points.py:255-263` | `_start_agent_from_agent_quick`      | `Path(agent.project_file).parent.name` | **No**   |
| 3   | `src/sase/ace/tui/actions/agent_workflow/_entry_points.py:305-308` | `action_start_custom_agent`          | `ProjectSelectModal` selection         | **No**   |
| 4   | `src/sase/ace/tui/actions/agent_workflow/_entry_points.py:499-507` | `_edit_and_relaunch_agent`           | `Path(project_file).parent.name`       | **No**   |
| 5   | `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py:67-89`   | `_save_replayable_vcs_selection`     | `ctx.project_name`                     | Yes      |

### How `project_name="project"` originally got into the file

The GitHub plugin's `resolve_gh_ref()` Mode 1
(`/home/bryan/projects/github/sase-org/sase-github/src/sase_github/workspace_plugin.py:371-402`) handles
`#gh:user/project` by splitting `parts = ['user', 'project']`, deriving
`project_file = ~/.sase/projects/project/project.gp`, and calling `set_workspace_dir(project_file, …)` — which
**auto-creates** that `.gp` file even when `project` is just a literal repo segment. After that, an agent gets launched
with `agent.project_file` pointing at the bogus `~/.sase/projects/project/project.gp`. Later, when the user runs
`,<space>` on the Agents tab (binding for `_start_agent_from_agent_quick`), line 249 computes
`project_name = Path(agent.project_file).parent.name = "project"` and the unguarded `save_last_agent_selection()` call
on line 263 persists it.

Confirming evidence: the original crash trace in `sdd/prompts/202605/space_keymap_error_toast.md` shows
`SelectionItem(display_name='branch', item_type='cl', project_name='project', cl_name='branch')`. The bare
`display_name='branch'` (no `[C] ` prefix) is only produced by the `_start_agent_from_*_quick` and
`_edit_and_relaunch_agent` paths — `_save_replayable_vcs_selection` would have written `display_name="[C] branch"`. The
fixed path is therefore _not_ the one that wrote the bad value.

## Goals

1. Stop persisting `last_agent_selection.json` with a non-launchable `project_name`, regardless of which TUI entry point
   triggers the save.
2. Keep behavior identical for valid project/CL/home selections.
3. Add focused regression coverage that fails on master and passes after the fix.

## Proposed Design

### 1. Centralize the save guard

Add a helper in `src/sase/ace/last_agent_selection.py` next to `save_last_agent_selection()`:

```python
def save_last_agent_selection_if_launchable(selection: SelectionItem) -> bool:
    """Persist *selection* only if its project is launchable (or item_type is home/all)."""
    if selection.item_type in ("home", "all"):
        return save_last_agent_selection(selection)
    # Local import keeps TUI modal helpers out of the persistence module's
    # top-level import graph.
    from sase.ace.tui.modals.project_discovery import is_launchable_project
    if not is_launchable_project(selection.project_name):
        return False
    return save_last_agent_selection(selection)
```

Rationale for placement: keeps the persistence layer cohesive and lets all current importers swap in one symbol. The
`is_launchable_project` import is local to avoid pulling TUI-facing modules into the persistence module's import graph
at module load time. Alternative considered (per-call-site `if is_launchable_project(...)` checks) rejected because the
same logic would be duplicated four times and easy to forget on the next save site that gets added.

### 2. Update all four unguarded call sites

Replace each `save_last_agent_selection(selection)` with `save_last_agent_selection_if_launchable(selection)` at:

- `_entry_points.py:226` (`_start_agent_from_changespec_quick`)
- `_entry_points.py:263` (`_start_agent_from_agent_quick`)
- `_entry_points.py:308` (`action_start_custom_agent`)
- `_entry_points.py:507` (`_edit_and_relaunch_agent`)

Also keep `self._last_custom_agent_selection` in lockstep with the persisted state: only assign it when the helper
returns `True`. Otherwise the in-memory cache remembers a selection that was never written, and the next replay attempt
would diverge from disk.

### 3. Refactor `_save_replayable_vcs_selection` to use the same helper

`_agent_launch.py:_save_replayable_vcs_selection` already validates `ctx.project_name` via
`_is_launchable_replay_project()`, but it duplicates the launchability check. Refactor it to use
`save_last_agent_selection_if_launchable()` so all five sites share one source of truth. Keep
`_is_launchable_replay_project()` only if it still has other callers (verify — it is also used by
`_record_resolved_vcs_xprompt_usage` on line 53 of `_agent_launch.py`, so retain it for that path).

### 4. Out of scope: GitHub plugin auto-create

The GitHub plugin's `resolve_gh_ref()` Mode 1 unconditionally calls `set_workspace_dir()` for any `user/project` ref,
which is the upstream cause of the bogus `~/.sase/projects/project/project.gp` files. This is a plugin-side behavior
change (potentially affecting other workflows) and is intentionally out of scope for this fix. The existing
`is_launchable_project()` predicate covers it for our purposes because it also checks that the `WORKSPACE_DIR` exists on
disk, which an auto-created `.gp` for a non-cloned repo will not.

## Tests

### Persistence-layer tests (extend `tests/ace/test_last_agent_selection.py`)

1. `save_last_agent_selection_if_launchable` rejects
   `SelectionItem(project_name="project", item_type="cl", cl_name="branch", display_name="branch")` when no
   `~/.sase/projects/project/project.gp` exists; assert the file was not written and the function returned `False`.
2. The same helper accepts `item_type="home"` regardless of `project_name` (verify file is written and `True` is
   returned).
3. The same helper accepts a launchable project: set up a `tmp_path`-rooted projects dir with a valid `.gp` and
   `WORKSPACE_DIR` pointing at an existing directory, monkeypatch `Path.home()` (or the projects-base resolver) to point
   there, and assert the save succeeds.

### Entry-point regression tests (extend `tests/ace/tui/test_entry_points_*.py` files)

4. `_start_agent_from_agent_quick` with an agent whose `project_file` points at a non-launchable project: assert
   `last_agent_selection.json` is **not** written, but the prompt input bar is still mounted (current UX preserved —
   only persistence is gated).
5. `_start_agent_from_changespec_quick` with a `changespec.project_basename` that's not launchable: same expectation.
6. `_edit_and_relaunch_agent` with a stale project_file: same expectation.

Each test must fail on master and pass after the fix — verify by running the test before and after applying the change.

## Verification

Per repo memory (`memory/short/build_and_run.md`): this touches `src/`, so run `just install` then `just check` before
reporting completion.

Targeted runs first:

```
pytest tests/ace/test_last_agent_selection.py \
       tests/ace/tui/test_entry_points_vcs_prefix_errors.py \
       tests/ace/tui/test_agent_launch_non_blocking.py
```

Then `just check` for the full lint + type + test gate.

## Risks and Tradeoffs

- **Existing corrupt `last_agent_selection.json` on user machines**: the on-load guard from `3e6eabc4` already clears
  stale entries with a one-time toast. Users with a current bogus file will see that toast once after this fix lands;
  subsequent operations won't re-write it.
- **`is_launchable_project()` cost**: filesystem-bound (≈3 stat calls). Called on the synchronous TUI path during
  agent-launch finalization. Negligible — the same call already runs on every `<space>` keymap press today.
- **Hiding a deliberate save**: if a user genuinely wants to persist a project that isn't yet launchable (e.g., they are
  about to set up its workspace), the helper silently skips the save. Acceptable — the user can re-trigger via the `@`
  modal once setup completes, and the alternative (persisting bogus state and crashing later) is worse.
- **Deeper GitHub-plugin auto-create issue**: left intentionally out of scope (see §4). Worth tracking as a follow-up
  but not blocking on this fix.
