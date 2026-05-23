---
create_time: 2026-05-23 11:46:16
status: done
prompt: sdd/prompts/202605/scoped_init_check.md
---
# Scoped Init Check Plan

## Goal

Add `-c|--check` to `sase sdd init` and `sase memory init`. The option should be read-only, report the same drift
summary and exit codes as `sase init --check`, and limit the check to the requested initialization type.

## Current Behavior

- Bare `sase init --check` already plans memory, SDD, and skills through `run_init_onboarding()`.
- SDD and memory already have read-only planners:
  - `sase.main.sdd_handler.plan_sdd_init`
  - `sase.main.init_memory_handler.plan_init_memory`
- Direct runners currently apply writes:
  - `sase.main.sdd_handler.run_sdd_init`
  - `sase.main.init_memory_handler.run_init_memory`
- `sase init --check memory` currently parses successfully because `--check` belongs to the parent `init` parser, but
  subcommand dispatch ignores it and still invokes the memory initializer. The same applies to `sase init --check sdd`.

## Design

1. Reuse the existing onboarding check renderer and exit semantics.
   - Extract the check-only path from `run_init_onboarding()` into a small public helper in `sase.main.init_onboarding`.
   - The helper will accept one or more `InitCommandSpec` values, call their planners, render the same summary, and
     return:
     - `0` when the scoped plans are current and have no blockers or warnings requiring action.
     - `1` when drift or blockers are present.
   - This keeps bare `sase init --check` and scoped checks on the same code path.

2. Add CLI flags at the scoped command surfaces.
   - Add `-c, --check` to `sase sdd init`.
   - Add `-c, --check` to `sase memory init`.
   - Add the same flag to `sase init sdd` and `sase init memory` aliases for option parity.
   - Preserve existing flags: `sase memory init -C|--no-commit` remains unchanged; lowercase `-c` is available.

3. Route check mode before apply mode.
   - In `handle_sdd_command()` / `run_sdd_init()`, if `args.check` is true, run the scoped check helper with the SDD
     spec and return its exit code without writing SDD files.
   - In `handle_memory_init_command()` / `run_init_memory()`, if `args.check` is true, run the scoped check helper with
     the memory spec and return its exit code without initializing memory or committing.
   - In `sase init` subcommand dispatch, rely on the same handler behavior so `sase init --check memory`,
     `sase init memory --check`, `sase init --check sdd`, and `sase init sdd --check` are also read-only.

4. Avoid circular imports.
   - Prefer constructing the single scoped `InitCommandSpec` locally in each handler or via a tiny registry helper if it
     stays simple.
   - Keep planner imports lazy where existing modules already do so.

## Tests

Add or update focused tests for:

- Parser acceptance:
  - `sase sdd init -c|--check`
  - `sase memory init -c|--check`
  - `sase init sdd --check`
  - `sase init memory --check`
  - `sase init --check sdd`
  - `sase init --check memory`
- SDD check behavior:
  - Missing generated SDD files exits `1`, prints the existing init-check drift summary, and does not create `sdd/`.
  - Current generated SDD files exits `0`.
- Memory check behavior:
  - Missing generated memory files exits `1`, prints the existing init-check drift summary, and does not create
    `memory/`.
  - Existing blockers still exit `1` and are rendered through the shared check output.
- Regression for alias safety:
  - `sase init --check memory` and `sase init --check sdd` must not call the apply runners.

## Verification

Run targeted tests first:

- `just test tests/main/test_init_onboarding.py tests/main/test_init_sdd_plan.py tests/main/test_init_memory_plan.py tests/main/test_memory_handler.py tests/main/test_parser_help.py`

Because this repo requires it after source changes, run:

- `just install`
- `just check`
