---
create_time: 2026-06-19 11:28:15
status: done
prompt: sdd/prompts/202606/amd_init_git_commit.md
---
# Plan: Make AMD Init Commit Its Own Changes

## Problem

Bare `sase init` plans AMD before memory and applies them in that same order. In the reported run:

1. `sase init amd` overwrote `AGENTS.md`.
2. `sase init memory` then refreshed memory files and started its project commit/pull/push workflow.
3. Memory committed only the paths from its own initializer result, leaving the prior AMD `AGENTS.md` write unstaged.
4. `git pull --rebase` failed because the worktree still had unstaged changes.

The root issue is not the registry order. AMD is the owner of the first `AGENTS.md` write, so AMD should leave its
owning git repo clean before the next initializer runs.

## Goals

- Make `sase amd init` and `sase init amd` commit AMD-managed file changes by default.
- Preserve an explicit opt-out with a public CLI option: `-C, --no-commit`.
- Keep bare `sase init` default behavior safe: if AMD changes files and commits successfully, memory can run afterward
  without inheriting AMD dirt.
- Stage only AMD-planned paths, not unrelated user changes.
- Support all AMD roots discovered by `amd_init_roots()`, including project plus chezmoi source home when `use_chezmoi`
  is enabled.
- Keep check mode read-only.

## Proposed Design

Add an AMD git deploy step in `sase.amd._runner` after planned writes/deletes are applied.

The runner will:

1. Build and apply the AMD plan exactly as it does today.
2. Collect the actual written and deleted paths.
3. If `args.no_commit` is true, stop after writing files.
4. Otherwise, group changed paths by owning git repo.
5. For each repo:
   - verify `git rev-parse --show-toplevel` works;
   - run the configured precommit command via `run_precommit(git_root)`;
   - stage only the AMD paths in that repo with `git add -- <path>`;
   - commit if there is a staged diff;
   - use a scoped message such as `chore: run sase init amd` with an automatic runtime type tag.

I plan to commit locally only, not pull/push from AMD. That is enough to fix the handoff to memory; when AMD runs as
part of bare `sase init`, the later memory commit/pull/push can push both local commits. This also avoids adding new
network behavior to standalone `sase amd init`.

If a changed AMD path is not inside a git repo and commits are enabled, AMD should fail after writing and report the
repo issue. This matches `sase memory init`'s default commit behavior and makes the new default honest: a command that
says it commits by default should not silently leave changes uncommitted.

## CLI Changes

- Add `-C, --no-commit` to the shared AMD init parser for:
  - `sase amd init -C`
  - `sase init amd -C`
- Keep `-c, --check` behavior unchanged.
- Update help text and bare `sase init` prompt copy so AMD changes clearly say they may create a local git commit.
- Do not add a bare `sase init --no-commit` in this change; the existing pattern is that advanced deploy controls live
  on explicit subcommands.

## Tests

Add focused coverage for:

- Parser accepts `sase amd init -C`, `sase amd init --no-commit`, `sase init amd -C`, and `sase init amd --no-commit`.
- AMD default commit path:
  - writes managed files;
  - runs precommit before staging;
  - stages only AMD-planned paths;
  - creates a commit with the expected message/tag;
  - leaves a real temporary git repo clean.
- AMD `--no-commit` path preserves the old write-only behavior.
- Check mode remains read-only and does not run git/precommit.
- Bare `sase init --yes` with AMD plus memory no longer hands memory an unstaged AMD `AGENTS.md` change.
- Multi-root AMD plans commit project and chezmoi-source roots independently when both are git repos.

Existing AMD tests that exercise file rendering in non-git temp directories should opt into `no_commit=True`; new tests
will cover the default commit behavior explicitly.

## Verification

Run focused tests first:

- `pytest tests/main/test_amd_init.py`
- `pytest tests/main/test_init_onboarding_flow.py`
- `pytest tests/main/test_init_onboarding_parser.py tests/main/test_parser_namespace_migrations.py`

Then run the broader init/AMD/memory sweep used for the previous fix.

Finally verify against the original scenario:

1. From `~/projects/github/bbugyi200/bob-cli`, run `sase init`.
2. Accept AMD and memory prompts.
3. Confirm AMD commits its `AGENTS.md` change before memory starts.
4. Confirm memory no longer fails at `git pull --rebase` with unstaged AMD changes.
5. Inspect `git status --short` afterward and report any remaining unrelated dirt separately.

## Risks and Mitigations

- Precommit may modify files outside AMD's planned path set. The AMD commit step will stage only AMD paths to avoid
  sweeping user work. If unrelated dirt still blocks a later pull, that is a separate pre-existing worktree cleanliness
  issue and should be reported as such.
- Some tests currently call AMD in non-git temp directories. Those tests should pass `no_commit=True` where they are
  testing rendering, not deploy behavior.
- Committing after writes means a commit failure still leaves files changed. This matches the existing memory
  initializer model and is preferable to pretending the operation succeeded.
