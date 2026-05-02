---
create_time: 2026-04-24 15:42:04
status: done
prompt: sdd/prompts/202604/startup_stopwatch_full_startup_completion.md
---
# Plan: Keep Startup Stopwatch Visible Until Full Startup Completes

## Problem

The startup stopwatch currently ends as soon as AXE finishes its first async startup load, even if other startup
surfaces (notably Agents) are still loading. This makes startup appear complete too early.

Current behavior source:

- `src/sase/ace/tui/actions/axe_display/_loaders.py` calls `footer.end_startup_stopwatch()` inside the AXE first-load
  path.
- Agents and AXE startup loads are launched concurrently from `AceApp._start_post_mount_background_loads`, so either
  side can finish first.

## Desired Behavior

The stopwatch should remain active until startup is globally complete.

For this codebase, "startup globally complete" means:

- Agents first async load has completed (`_agents_first_load_done == True`), and
- AXE first async load has completed (`_axe_first_load_done == True`).

Only when both are true should the stopwatch be ended.

## Design

### 1. Centralize startup-completion gating in `AceApp`

Add a small app-level coordinator method (name example: `_maybe_end_startup_stopwatch`) that:

- Returns immediately unless both first-load flags are true.
- On success, queries the footer and calls `end_startup_stopwatch()`.
- Is safe to call repeatedly (footer end is already idempotent).

This makes completion policy explicit and avoids coupling it to one panel's loader.

### 2. Trigger the coordinator from both first-load completion paths

- In `AgentLoadingMixin._apply_loaded_agents`, after the first-load flag is flipped and startup loading indicators are
  cleared, call `_maybe_end_startup_stopwatch()`.
- In `AxeDisplayLoadersMixin._apply_axe_status_data`, after AXE first-load flag handling and loading-indicator clear,
  call `_maybe_end_startup_stopwatch()`.

Result:

- If AXE finishes first, stopwatch stays on because agents flag is still false.
- If Agents finish first, stopwatch stays on because AXE flag is still false.
- When the second one completes, stopwatch ends immediately.

### 3. Remove direct stopwatch termination from AXE loader

Delete the direct `footer.end_startup_stopwatch()` call from the AXE first-load block so all termination flows through
the shared coordinator.

## Invariants to Preserve

- Startup loaders still launch concurrently (no serial gating).
- Individual panel loading indicators still clear on each panel’s own first load.
- Stopwatch timeout safety behavior (30s) remains unchanged.
- Behavior remains teardown-safe/idempotent.

## Test Plan

### Update existing startup wiring tests

`tests/ace/tui/test_startup_stopwatch_live_update.py`

- Keep existing concurrent scheduling and non-gating tests.
- Add focused tests for new coordinator logic:
  - Ends only when both flags are true.
  - Does not end when only one flag is true.
  - Idempotent under repeated calls.

### Add/adjust loader-level regression coverage

Add lightweight unit tests (or extend current file) that validate:

- AXE first-load path no longer ends stopwatch directly.
- Calling first-load apply on one loader alone does not end stopwatch.
- After simulating both first-load applies, stopwatch end is triggered exactly once.

Preferred pattern: use small harness objects and monkeypatched `query_one`/footer mocks to avoid full Textual mount
complexity.

## Implementation Steps

1. Add `_maybe_end_startup_stopwatch` to `AceApp` (or equivalent lifecycle mixin that both loaders can call).
2. Remove AXE direct footer-end call.
3. Invoke coordinator from AXE and Agents first-load paths.
4. Add/adjust tests covering dual-flag gating and idempotency.
5. Run focused tests for startup stopwatch behavior.
6. Run full `just check`.

## Risks and Mitigations

- Risk: one startup loader fails and never flips its first-load flag, leaving stopwatch visible until timeout.
  - Mitigation: acceptable and preferable to false "startup complete"; existing timeout still guarantees eventual exit.
- Risk: mixin type-check complaints when calling app-level coordinator.
  - Mitigation: add protocol/type hints to mixins (as done for other app methods).
- Risk: duplicate end calls due to repeated refreshes.
  - Mitigation: footer end is idempotent; coordinator may be called multiple times safely.

## Rollout

Single commit scoped to startup stopwatch gating + tests.
