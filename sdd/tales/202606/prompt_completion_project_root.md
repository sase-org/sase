---
create_time: 2026-06-06 14:17:10
status: done
prompt: sdd/prompts/202606/prompt_completion_project_root.md
---
# Plan: Project-Rooted Prompt File Completion

## Problem

`Ctrl+T` file completion and `Ctrl+R` recursive file search in the ACE prompt widget currently resolve relative prompt
paths from the process CWD of `sase ace`. That is wrong for prompts that launch into another project via a VCS xprompt
workflow. For example, `#gh:bob-cli sdd/<ctrl+t>` should enumerate `sdd/` under the `bob-cli` project's primary
checkout, not under the directory where ACE happened to start.

The desired root is:

1. The explicit `#cd:<dirname>` target if the prompt includes a `#cd` workflow reference.
2. Otherwise, the primary workspace directory for the project selected by the prompt's VCS workflow reference, such as
   `#gh:bob-cli`.
3. Otherwise, the existing fallback behavior based on the current process CWD.

Completion insertions should remain exactly what the user typed conceptually: relative completions should insert
relative paths such as `sdd/foo.md`, not absolute paths.

## Current Findings

- `PromptTextArea` maps `ctrl+t` to `_try_file_completion_tab()` and `ctrl+r` to `_open_recursive_file_finder()`.
- The single-level completion engine is `sase.ace.tui.widgets.file_completion.build_completion_candidates(token)`.
- `build_completion_candidates()` only receives a token, so relative tokens are resolved by `os.scandir()` against
  process CWD.
- The recursive finder has the same problem through `resolve_root_abs("") -> os.getcwd()` and
  `os.path.abspath(relative_root)`.
- Launch-time code already knows the intended project/root:
  - registered workspace-provider refs are resolved through
    `workspace_provider.resolve_ref(ref, workflow_type).primary_workspace_dir`;
  - `#cd` is a non-workspace workflow whose provider returns the chosen directory as `primary_workspace_dir`;
  - known-project refs like `#gh:sase` can fall back through `get_known_project_workspaces()` and
    `resolve_known_project_ref()`.
- The completion path should be side-effect-free: no `chdir`, no workspace claiming, and no lifecycle activation during
  a keypress.

## Implementation Plan

1. Add a side-effect-free prompt completion root resolver.
   - Place it near the prompt/completion widgets, likely as a small pure helper module under
     `src/sase/ace/tui/widgets/`.
   - Canonicalize project aliases in the prompt before resolving.
   - Prefer a resolved `#cd` ref when present, using workspace-provider metadata and `resolve_ref(ref, "cd")`.
   - Otherwise scan registered workspace-provider ref patterns in prompt order and return
     `resolve_ref(...).primary_workspace_dir` when available.
   - If no registered provider resolves the prompt, fall back to known-project lookup with
     `get_known_project_workspaces(include_states="all")` and `resolve_known_project_ref()`.
   - Catch resolution errors and return `None` so broken/incomplete refs do not break typing.

2. Thread the resolved base directory into single-level completion.
   - Extend `build_completion_candidates(token, *, base_dir=None)`.
   - Resolve only relative filesystem lookup paths against `base_dir`.
   - Keep absolute paths, `~/...`, env-expanded paths, and insertion strings unchanged.
   - Preserve `@` file-reference prefix behavior.
   - Update `_file_completion.py` call sites, including refresh, shared-prefix recomputation, directory drill-down, and
     xprompt path-argument completion, to pass the prompt-derived base directory.

3. Thread the same base directory into recursive finder root resolution.
   - Extend `resolve_root_abs(root_display, *, base_dir=None)`.
   - Use the prompt-derived base for empty and relative roots.
   - Keep `root_display` and candidate insertions relative so selecting a result inserts `sdd/foo.py`, not an absolute
     path.
   - Update both Ctrl+R cases:
     - active Ctrl+T selection derives the search root from the selected insertion plus the prompt base;
     - cursor token derives the search root from the token plus the prompt base.

4. Consider soft completion consistency.
   - The user-reported bug is `Ctrl+T`/`Ctrl+R`, so the main fix should land there.
   - If the change is low-friction, also pass the same base into file-path soft completion so `Ctrl+L` does not disagree
     with `Ctrl+T`.

5. Add focused tests.
   - Pure `file_completion` test: `build_completion_candidates("sdd/", base_dir=project_root)` reads from
     `project_root/sdd` while process CWD points elsewhere, and insertions stay relative.
   - Pure recursive finder test: `resolve_root_abs("sdd/", base_dir=project_root)` resolves to `project_root/sdd`.
   - Prompt widget test for known-project VCS fallback: with CWD set to an unrelated directory, `#gh:bob-cli sdd/` +
     `Ctrl+T` returns entries from the known `bob-cli` workspace.
   - Prompt widget test for `#cd` precedence: `#gh:bob-cli #cd:<other> sdd/` completes from `<other>/sdd`.
   - Prompt widget or pure context test for `Ctrl+R`: root context for `#gh:bob-cli sdd/foo` points at the project
     workspace, not process CWD.
   - Keep existing CWD-based tests intact for prompts without a resolvable VCS or `#cd` root.

6. Verify.
   - Run targeted tests for the touched prompt completion and recursive finder modules.
   - Because code changes in this repo require it, run `just install` if needed and then `just check` before finalizing.

## Risks And Notes

- Registered provider resolution may fail for incomplete refs while the user is typing; completion should gracefully
  fall back instead of surfacing errors.
- Known-project lookup should include inactive projects for read-only completion context, but completion should not
  activate them. Activation remains launch-time behavior.
- The behavior should not allocate numbered workspaces. The requested root is the main/primary directory, matching the
  provider's `primary_workspace_dir`.
