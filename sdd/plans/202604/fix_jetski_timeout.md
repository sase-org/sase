---
create_time: 2026-04-24 15:55:30
status: wip
prompt: sdd/prompts/202604/fix_jetski_timeout.md
---
# Plan: Fix Jetski Agent Timeouts in `sase ace`

## Problem Summary

`JetskiProvider` (in `../sase-google`) currently invokes Jetski in print mode (`-p`) without explicitly setting key
non-interactive flags. The observed failure (`Error: timed out waiting for response`) aligns with Jetski defaults:

- `--print-timeout=5m`
- `--dangerously-skip-permissions=false`

In automated `sase ace` agent runs, prompts frequently require tool calls (read/search/edit). If permission gating is
left interactive, print mode can stall until timeout. Even when permission is not the blocker, the default 5-minute
print timeout is too short for long planning/review prompts.

## Goals

1. Make Jetski provider robust for non-interactive automated agent runs.
2. Eliminate avoidable 5-minute timeout failures for legitimate long-running prompts.
3. Keep behavior configurable without requiring user code edits.

## Proposed Changes

1. Update `../sase-google/src/sase_google/llm_jetski/provider.py` command construction:

- Always add `--dangerously-skip-permissions` for non-interactive provider invocations.
- Always add `--print-timeout <value>` where default is increased from implicit `5m` to a safer provider default (e.g.,
  `30m`).
- Add env override (e.g., `SASE_JETSKI_PRINT_TIMEOUT`) so operators can tune timeout without code changes.

2. Keep prompt passing behavior unchanged (`-p <prompt>`) since this was already corrected and covered by regression
   tests.

3. Extend tests in `../sase-google/tests/test_llm_jetski_provider.py`:

- Assert command includes `--dangerously-skip-permissions`.
- Assert command includes `--print-timeout` with provider default.
- Add env-override test for custom print timeout.
- Keep existing prompt/mode/model regression coverage intact.

## Validation

1. Run targeted Jetski provider tests in `../sase-google`.
2. Run `just check` in `../sase-google` to validate lint/type/tests.
3. Confirm no core `sase` code changes are required for this fix path.

## Risks / Tradeoffs

- Longer print timeout means slower failure in true hang scenarios, but this is preferable to false failures at 5
  minutes for legitimate long tasks.
- Auto-skipping permissions increases autonomy in non-interactive runs; this matches existing provider behavior patterns
  for automated workflows.

## Rollback Strategy

If needed, revert to prior behavior by:

- Removing injected `--dangerously-skip-permissions` / `--print-timeout` flags, or
- Setting `SASE_JETSKI_PRINT_TIMEOUT` to a smaller value as an operational mitigation.
