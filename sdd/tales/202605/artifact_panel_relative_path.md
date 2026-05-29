---
create_time: 2026-05-29 07:31:20
status: done
prompt: sdd/prompts/202605/artifact_panel_relative_path.md
---
# Plan: Artifact Panel `Y` Copies Repo-Relative Paths

## Goal

Change the `Y` keybinding in the TUI artifact selection panel so it copies a path relative to the agent's project
workspace/repo when the selected artifact can be mapped into that workspace. Keep the existing absolute/home-relative
fallback for artifacts outside the repo or artifacts with incomplete metadata.

## Context

- The keybinding is defined in `AgentArtifactSelectionModal.BINDINGS` in
  `src/sase/ace/tui/modals/agent_artifacts_modal.py`.
- `action_copy_path()` currently resolves the selected artifact display path and passes it through `_clipboard_path()`,
  which only produces `~`-relative or absolute output.
- The modal already has workspace-aware display helpers:
  - `_artifact_workspace_dir()` reads `artifact.workspace_dir`.
  - `_artifact_resolved_display_path()` resolves relative artifact/source paths against that workspace.
  - `_display_path()` renders paths relative to `workspace_dir` for the visible artifact list.
- Default artifacts usually get `workspace_dir` from `done.json`/`agent_meta.json`.
- Persisted/default artifacts and explicit artifacts can have a stored artifact path under SASE's global artifact store
  while retaining a `source_path` pointing at the original repo file.

## Design

1. Add a small clipboard-specific helper in `agent_artifacts_modal.py`, scoped to the modal:
   - Determine the best workspace root from `artifact.workspace_dir`.
   - If that is missing, best-effort read `agent_meta.json` or `done.json` from `artifact.agent_artifacts_dir` to
     recover `workspace_dir` for older/indexed artifacts.
   - Do not infer from current working directory; only use explicit artifact/run metadata as the project repo root.
2. For `Y`, choose the copied path in this order:
   - Resolve the current display path (`path`, or PDF `source_path`) and return it relative to the workspace root if it
     is inside the workspace.
   - If the display path is not inside the workspace, try `artifact.source_path` as the original repo source and return
     it relative to the workspace root if it is inside the workspace.
   - Fall back to the existing `_clipboard_path()` behavior.
3. Keep path output POSIX-style (`sdd/research/202605/foobar.md`) and avoid `../...` paths for files outside the repo.
4. Keep the behavior of `y` copy-contents unchanged; only `Y` path-copy output changes.

## Tests

Update `tests/ace/tui/modals/test_agent_artifacts_modal.py` with focused coverage:

- `Y` copies a workspace-relative path for an artifact whose path is inside `workspace_dir`.
- The existing no-workspace case still falls back to `~/...`.
- PDF markdown source path copy becomes workspace-relative when the source is in the workspace.
- A persisted/global artifact can copy the repo-relative `source_path` when the stored `path` is outside the workspace.
- Metadata fallback can recover `workspace_dir` from `agent_artifacts_dir/agent_meta.json` for artifacts that do not
  carry `workspace_dir` directly.

## Verification

Run targeted tests first:

```bash
just install
just test tests/ace/tui/modals/test_agent_artifacts_modal.py
```

Because this repo requires it after file changes, finish with:

```bash
just check
```
