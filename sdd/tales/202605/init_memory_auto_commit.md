---
create_time: 2026-05-22 20:39:51
status: done
prompt: sdd/prompts/202605/init_memory_auto_commit.md
---
# Plan: `sase init memory` Workspace Hint and Auto-Commit

## Goal

Update `sase init memory` so generated sibling-repository guidance tells agents how to infer the primary workspace
number from their starting directory, and so successful runs automatically commit and push project memory changes by
default. Add an option to disable the new auto-commit behavior.

## Current Behavior

`src/sase/main/init_memory_handler.py` renders both project-level and home-level SASE memory. The sibling repository
section currently says:

```text
`<workspace_num>` must be the workspace number assigned to the primary repo.
```

The command writes project memory, home memory, `AGENTS.md`, and provider shims, then validates that memory files are
reachable. If `use_chezmoi` is enabled, home-level written paths are committed in the chezmoi repo and applied, but the
primary project repo is not committed or pushed.

The existing commit workflow has `run_precommit(cwd)`, which loads the configured `precommit_command` and executes it
before normal SASE commits. `sase init memory` should use that same behavior before creating its own generated-memory
commit.

## Proposed Behavior

1. Update the generated workspace instruction text to:

   ```text
   `<workspace_num>` must be the workspace number assigned to the primary repo (check what directory you were started in to figure this out).
   ```

   Keep the rest of the sibling-repository section unchanged.

2. Add `--no-commit` to `sase init memory`.
   - Default: after successful generation and memory reachability validation, auto-commit and push project-level
     changes.
   - `--no-commit`: skip the project repo commit/push entirely.
   - The option name should match the existing `sase init skills --no-commit` style.

3. Implement a project-repo deploy helper in `init_memory_handler`.
   - Run only after config validation, file generation, and unreferenced-memory validation pass.
   - Skip cleanly when `--no-commit` is set.
   - Locate the current project git root with `git rev-parse --show-toplevel`.
   - Run `run_precommit(str(git_root))` before staging/committing. If it fails, exit non-zero and do not commit.
   - Stage the project paths managed by this command. Include initially written paths plus the project memory target so
     precommit edits to generated memory are captured.
   - If nothing is staged, print a concise "nothing to commit" message and skip push.
   - Commit with a deterministic message such as `chore: run sase init memory`.
   - Pull with rebase, then push to the configured upstream/default remote. Treat pull, commit, or push failures as
     command failures.

4. Preserve existing chezmoi behavior.
   - Keep home-level chezmoi deployment independent from the project repo auto-commit.
   - If both project auto-commit and chezmoi deploy run, surface failures through a non-zero final exit.

## Tests

Add focused tests in `tests/main/test_init_memory_handler.py` and parser coverage in `tests/main/test_parser_help.py`.

- Assert generated project memory contains the new parenthetical phrase.
- Assert parser accepts `sase init memory --no-commit`.
- Assert default init-memory execution runs precommit, stages, commits, pulls, and pushes for the project repo when
  there are staged changes.
- Assert `--no-commit` skips precommit and all project git commit/push work.
- Assert a failing precommit aborts before staging/commit/push.
- Keep existing tests isolated by defaulting their handler namespace to `no_commit=True` where commit behavior is not
  under test.

## Verification

Run targeted tests:

```bash
python -m pytest tests/main/test_init_memory_handler.py tests/main/test_parser_help.py
```

Then follow repo requirements after code changes:

```bash
just install
just check
```

Finally, run this repo's command as requested:

```bash
sase init memory
```

Because the command will auto-commit and push by default after this change, this final manual test should exercise the
new behavior in the current `sase_10` workspace.
