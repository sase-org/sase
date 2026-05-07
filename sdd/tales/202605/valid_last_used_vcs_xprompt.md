---
create_time: 2026-05-07 16:53:16
status: done
prompt: sdd/prompts/202605/valid_last_used_vcs_xprompt.md
---
# Plan: Filter Stale Last-Used VCS XPrompt Selections

## Problem

The `@` project picker now uses `list_launchable_projects()`, which filters out project entries whose `.gp` file is
missing, lacks a usable `WORKSPACE_DIR`, points at a missing workspace, or cannot resolve to a registered workflow type.
The `<space>` repeat workflow still replays the persisted last `@/<space>` selection from
`~/.sase/last_agent_selection.json` and reconstructs `~/.sase/projects/<project>/<project>.gp` directly.

That leaves a stale path where a project that no longer appears in the `@` picker can still be replayed by `<space>`.
The current guard only checks whether the project file exists, which prevents one class of failure but still permits
invalid projects whose `.gp` exists but is no longer launchable.

## Goals

- Reuse the same launchability decision for the `@` picker and the `<space>` last-selection replay.
- Clear persisted last selections when their project is no longer launchable.
- Avoid showing or cycling stale last-used VCS workflow entries where practical, so invalid projects are not surfaced as
  launch targets.
- Keep home-mode and free-form prompt behavior unchanged.

## Proposed Design

1. Add a small helper near `project_discovery.py` for single-project validation.
   - Expose something like `is_launchable_project(project_name: str, projects_dir: Path | None = None) -> bool`.
   - Implement it by constructing `<projects_dir>/<project>/<project>.gp` and delegating to the same private
     `_is_launchable_project_file()` predicate already used by `list_launchable_projects()`.
   - Keep `home` excluded from project-scoped launches.

2. Use that helper when loading/replaying the last `@/<space>` selection.
   - In `_start_custom_agent_from_selection()`, replace the `os.path.exists(project_file)` guard with the launchability
     check for non-home project/CL selections.
   - If invalid, keep the current user-facing behavior: clear in-memory and persisted selection, notify once, and
     return.
   - Adjust the stale message to say the project is “not launchable” instead of only “project file not found”, since the
     invalid cases now include missing workspace/provider as well.

3. Validate before accepting saved last-selection state.
   - In `load_last_agent_selection()`, validate the deserialized `SelectionItem` enough to reject malformed item types.
   - Prefer keeping filesystem/project launchability validation in the TUI layer so the persistence module stays a thin
     JSON adapter and avoids importing Textual-facing modal modules.
   - Add a small TUI/helper function if needed to load-and-validate the persisted selection in one place, so
     `action_start_agent_from_changespec()` and prompt-history replay do not duplicate stale-clearing logic.

4. Filter VCS MRU cycling candidates for known project refs.
   - The prompt input widget’s `ctrl+n`/`ctrl+p` MRU path loads raw entries from `vcs_xprompt_mru.json`.
   - Add a helper in `sase.history.vcs_xprompt_mru` or a TUI adapter that filters entries whose ref names a known
     project but is not launchable.
   - Preserve entries that cannot be classified as project refs, since plugin-specific CL refs may be valid even when
     they are not in `list_launchable_projects()`.
   - Optionally rewrite the MRU file after pruning invalid project entries, so stale entries do not reappear on the next
     cycle.

5. Tests.
   - Extend `tests/ace/tui/modals/test_project_select_modal.py` or add a focused test for the new
     `is_launchable_project()` helper.
   - Add regression coverage for `_start_custom_agent_from_selection()` showing a project with an existing `.gp` but
     invalid/missing workspace clears the persisted selection and does not call prompt-bar launch.
   - Extend `tests/test_vcs_xprompt_mru.py` or prompt widget tests to show invalid known-project MRU entries are
     filtered while unclassified refs remain.

6. Verification.
   - Run the focused test files first:
     - `pytest tests/ace/tui/modals/test_project_select_modal.py tests/test_vcs_xprompt_mru.py`
     - plus the new/updated TUI entry-point regression test.
   - Because this repo’s memory requires it after code changes, run `just install` followed by `just check` before
     reporting completion.

## Risks and Tradeoffs

- `list_launchable_projects()` is currently a TUI helper, while known-project fallback resolution is shared by CLI and
  agent launch paths. For this request, the target symptom is the ACE TUI `<space>` workflow, so keeping the first
  change in TUI code is lowest risk.
- Filtering MRU entries is trickier than filtering explicit project selections because `#gh:<ref>` may mean a project,
  branch, PR, or CL depending on provider. The safe rule is to prune only refs that clearly target a stale known project
  entry and leave ambiguous refs alone.
- If a persisted CL selection belongs to a launchable project but the CL itself no longer exists, the existing behavior
  should be preserved unless tests reveal a separate stale-CL failure path.
