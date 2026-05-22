---
create_time: 2026-05-22 15:39:20
status: done
prompt: sdd/prompts/202605/workspace_open_clean.md
---
# Plan: `sase workspace open --clean`

## Context

`sase workspace open` currently behaves like `sase workspace path`: it resolves a workspace number and prints the
checkout path. Agent and workflow launch paths already prepare workspaces through
`prepare_workspace(..., VCS_DEFAULT_REVISION, ...)`, which:

- stashes uncommitted and untracked changes via the active VCS provider,
- checks out the provider's default parent revision (for git, the origin default branch such as `origin/master`),
- runs provider sync after checkout when implemented,
- fails fast when clean, checkout, or sync fails.

This request should make the CLI expose that same preparation path for future agents that need to prepare sibling
workspace directories directly.

## Design

Add `-c|--clean` to `sase workspace open`.

Keep `sase workspace open <num>` and `sase workspace open <num> --print` behavior unchanged when `--clean` is absent:
resolve/materialize using the existing `path` logic and print the path.

When `--clean` is present:

1. Resolve the project context exactly like `path/open` do today.
2. Validate `workspace_num >= 0`.
3. Materialize the requested checkout unconditionally, because a workspace cannot be prepared unless it exists on disk.
4. Run the same workspace preparation sequence used by new agents:
   - use
     `prepare_workspace(checkout_path, clean_label, VCS_DEFAULT_REVISION, backup_suffix=..., project_basename=ctx.project_name)`;
   - use a CLI-specific backup suffix such as `workspace-open` so stashes/diffs are identifiable;
   - use a deterministic clean label based on project and workspace number, e.g. `<project>-workspace-<num>`, rather
     than requiring a ChangeSpec name.
5. Print the checkout path only after successful preparation.
6. Return non-zero if materialization or preparation fails, preserving the existing stderr behavior from the preparation
   helper.

This is intentionally an opt-in side-effect. `path` remains path-only, and `open` without `--clean` remains
path-compatible.

## Module Boundary

This belongs in the Python CLI/provider layer, not `sase-core`, because it performs host-coupled VCS side effects
through Python provider plugins and local checkout materialization. The key correctness requirement is to reuse the
existing agent preparation helper rather than create a second checkout/sync implementation.

If the direct import from `sase.axe.runner_utils.prepare_workspace` feels too coupled during implementation, introduce a
small neutral helper module and keep `runner_utils.prepare_workspace` as the compatibility wrapper. Do not duplicate the
preparation sequence.

## Tests

Add focused CLI tests under `tests/main/`:

- parser accepts `sase workspace open -c <num>` and `sase workspace open --clean <num>`,
- open without `--clean` still delegates to path behavior and does not call preparation,
- open with `--clean` materializes the checkout even for an unregistered workspace number,
- open with `--clean` calls preparation with `VCS_DEFAULT_REVISION`, the resolved checkout path, project basename, and a
  CLI-specific backup suffix,
- materialization failure returns `1` and reports the error,
- preparation failure returns `1` and does not print a successful ready path.

Also run the targeted workspace handler and runner utility tests first, then `just check` after implementation because
this repo requires it after code changes.

## Implementation Steps

1. Update `src/sase/main/parser_workspace.py` to add `-c/--clean` on the `open` parser.
2. Update `src/sase/main/workspace_handler.py`:
   - keep `_handle_open` as the compatibility path when `args.clean` is false;
   - add a private `_handle_open_clean` or equivalent branch for the new behavior;
   - reuse `_resolve_project_context` and `_resolve_checkout_path(..., materialize=True)`;
   - call the existing agent preparation helper with `VCS_DEFAULT_REVISION`;
   - print the path and return `0` only on success.
3. Add/update tests in `tests/main/test_workspace_handler_parser.py` and
   `tests/main/test_workspace_handler_list_path.py` or a new focused open test file.
4. Run targeted tests:
   - `just install` if needed for this workspace,
   - `python -m pytest tests/main/test_workspace_handler_parser.py tests/main/test_workspace_handler_list_path.py tests/test_axe_runner_utils.py`,
   - `just check`.
