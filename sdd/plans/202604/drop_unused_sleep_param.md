---
create_time: 2026-04-27 12:35:22
status: done
prompt: sdd/prompts/202604/drop_unused_sleep_param.md
---
# Plan: Drop Unused `sleep` Parameter From `_BatchTimestampAllocator`

## Context

Commit `bd5a8f5a` ("fix: prevent multi-prompt timestamp collisions") added `_BatchTimestampAllocator` in
`src/sase/agent/multi_prompt_launcher.py` so that children launched in one multi-prompt batch can't share a
one-second-resolution timestamp.

A post-implementation review of the change turned up **no bugs**. The allocator's "only-check-against-immediate-
predecessor" design is sufficient because `generate_timestamp()` (`src/sase/core/time.py:25`) is monotonic with seconds
resolution. The collision-and-retry interaction with multi-model segments is correctly traced by
`test_launch_multi_prompt_with_multi_model_segment`.

The review did surface one strict simplification opportunity that is a clear win.

## Problem

`_BatchTimestampAllocator.__init__` accepts a `sleep: Callable[[float], None] | None = None` parameter that defaults to
`time.sleep`. The class stores it as `self._sleep` and `next()` calls `self._sleep(0.05)`.

This parameter has no caller and no test:

- The sole construction site is `timestamp_allocator = _BatchTimestampAllocator(generate_timestamp)` at
  `src/sase/agent/multi_prompt_launcher.py:202` — `sleep` is never passed.
- `tests/test_multi_prompt_launcher.py` patches sleeps via `mock.patch("sase.agent.multi_prompt_launcher.time.sleep")`
  (see lines 154, 195, 244, 422), not via the constructor parameter.

The `sleep` parameter exists purely as injectable indirection that nothing injects into. Removing it makes the class
smaller and removes a way to misuse it.

## Change

In `src/sase/agent/multi_prompt_launcher.py` at lines 148-166:

1. Remove the `sleep` parameter from `_BatchTimestampAllocator.__init__`.
2. Remove the `self._sleep = ...` assignment.
3. In `next()`, replace `self._sleep(0.05)` with a direct `time.sleep(0.05)`.

Keep the module-level `from collections.abc import Callable` import — it is still used by `launch_multi_prompt_agents`'s
`on_agent_spawned` parameter.

## Why This Is A Clear Win

- **Same external behavior.** The class has one caller (the launcher itself) and that caller did not pass `sleep`. So
  the patched/observed behavior is identical.
- **Tests still work without changes.** All test patches target `sase.agent.multi_prompt_launcher.time.sleep`, which
  intercepts the direct `time.sleep(0.05)` call exactly the same way it intercepts `time.sleep(1)` used between
  multi-model variants.
- **Strictly smaller surface.** Removes an injectable parameter with no production injection and no test injection —
  purely dead optionality.

## Out Of Scope

- Removing `time.sleep(1)` between multi-model variants. It is now redundant for uniqueness (the allocator guarantees
  that on its own), but removing it changes wall-clock timing between sibling launches. Not a strict win.
- Renaming `next()` to avoid shadowing the `next` builtin. Subjective.
- Adding a max-retry guard inside `next()`. Unnecessary because `generate_timestamp()` advances at least once per
  second.
- Any operational repair of already-collided live `sase-w` agents (per the original plan's out-of-scope clause).

## Verification

- `uv run pytest tests/test_multi_prompt_launcher.py -q` — focused launcher tests, including the three
  collision-coverage tests (`test_launch_multi_prompt_retries_duplicate_timestamps`,
  `test_launch_multi_prompt_wait_segments_get_unique_artifacts`, `test_launch_multi_prompt_with_multi_model_segment`).
- `just check` — repo-wide format/lint/test gate.
