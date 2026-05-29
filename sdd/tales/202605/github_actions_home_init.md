---
create_time: 2026-05-28 20:46:46
status: done
prompt: sdd/prompts/202605/github_actions_home_init.md
---
# Plan: Initialize SASE Home Surfaces In CI Before Validation

## Problem

`just lint` now runs `sase validate`, and `sase validate` runs `sase init --check` plus `sase sdd validate`.

The GitHub Actions lint job runs on a clean runner home. The repository-local generated files are current, but the
home-level initialization surfaces are absent:

- `~/memory/short/sase.md`, `~/memory/README.md`, and home provider shims such as `~/AGENTS.md`
- provider runtime skills under `~/.claude/skills`, `~/.codex/skills`, `~/.gemini/skills`, and similar target roots

That makes `sase init --check` fail before the SDD check can be useful. A local developer with an initialized home does
not see the failure, which is why the issue reproduces only with an isolated `HOME`.

## Findings

- The failure reproduces exactly with `HOME=$(mktemp -d) ./.venv/bin/sase validate`.
- `./.venv/bin/sase validate` passes with the current real home because those generated files already exist.
- The repo already has project memory and AMD files checked in; the failing work is home-only plus generated runtime
  skill deployment.
- Running bare `sase init --yes` in CI would make the check pass, but it also routes through `init memory`'s project
  deploy path and runs the configured precommit command (`just fix`). That is unnecessary and too broad for a lint setup
  step.
- Running the scoped commands below in an isolated home makes the subsequent validation pass without touching tracked
  repository files:

  ```bash
  ./.venv/bin/sase init memory --no-commit
  ./.venv/bin/sase skills init --force
  ./.venv/bin/sase validate
  ```

## Approach

1. Update the GitHub Actions lint job after `just install` and before `just lint`.
2. Add a small setup step that initializes the runner's generated SASE home files:
   - `./.venv/bin/sase init memory --no-commit`
   - `./.venv/bin/sase skills init --force`
3. Do not change `sase validate` behavior. The docs currently state that it includes home-level initialization drift,
   and preserving that behavior keeps local validation strict.
4. Do not use bare `sase init --yes` in CI because it can invoke repo precommit/deploy behavior that is not needed for
   this problem.
5. Add a focused test around the workflow shape if practical; otherwise validate by running the same isolated-home smoke
   sequence locally and then running the existing validation/lint gates.

## Verification

After editing:

1. Run the isolated-home smoke:

   ```bash
   tmp_home=$(mktemp -d)
   HOME="$tmp_home" ./.venv/bin/sase init memory --no-commit
   HOME="$tmp_home" ./.venv/bin/sase skills init --force
   HOME="$tmp_home" ./.venv/bin/sase validate
   rm -rf "$tmp_home"
   ```

2. Run the focused validation command:

   ```bash
   ./.venv/bin/sase validate
   ```

3. Because this repo requires it after file changes, run:

   ```bash
   just check
   ```

## Risks

- The lint job may print setup output from memory/skills initialization. That is acceptable; it happens before the
  actual lint stage and makes the CI setup explicit.
- If GitHub runners lack `prettier`, skill generation may use unformatted Markdown for temporary home files. That does
  not affect tracked files, and the subsequent `init --check` uses the same render path. The existing warning is only
  visible when the check itself fails.
