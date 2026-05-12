---
create_time: 2026-05-12 17:53:32
status: done
prompt: sdd/prompts/202605/fix_just_install_bootstrap.md
---
# Plan: Bootstrap `fix_just` with `just install`

## Goal

Ensure the `#sase/fix_just` chop refreshes the current ephemeral workspace by running `just install` before it runs any
other `just` command.

## Current Behavior

`xprompts/fix_just.yml` starts with three hidden bash steps:

- `_just_fmt_check` runs `just fmt-check`
- `_just_lint` runs `just lint`
- `_just_test` runs `just test`

Later, the conditional `fix_fmt` step runs `just fmt` if formatting failed. The workflow executor runs steps
sequentially in YAML order, and a failing bash step prevents later non-`finally` steps from running. Therefore, a first
ordinary bash step is enough to enforce the required ordering.

## Proposed Change

1. Add a first hidden workflow step named `_just_install` to `xprompts/fix_just.yml`.
2. Make `_just_install` run exactly `just install`.
3. Do not swallow install failures. If `just install` exits non-zero, the workflow should fail before any other `just`
   command is attempted.
4. Leave the existing `decide_fixers` logic unchanged; it only needs the outputs from the three check steps.

## Verification

1. Add a focused test that loads `xprompts/fix_just.yml` and asserts:
   - the first step is `_just_install`
   - the first step is hidden
   - the first step's bash body is `just install`
   - no later step contains a `just` command before that first step by construction
2. Run a targeted pytest for the new test.
3. Because this repo's instructions require workspace refresh before checks, run `just install`.
4. Run `just check`.

## Risk

The only notable cost is that `fix_just` will spend extra time installing dependencies even when the workspace is
already current. That is intentional for stale `sase_<N>` workspaces and matches the repo guidance.
