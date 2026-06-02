---
create_time: 2026-06-02 06:22:52
status: done
prompt: sdd/prompts/202606/numeric_auto_agent_names.md
---
# Numeric-leading auto agent names

## Goal

Allow auto-generated agent names to begin with digits and make automatic allocation choose the smallest available short
name before moving to longer names. In an empty name registry, the next auto-generated agent should be `1`, then `2`,
and so on through all available one-character names, then two-character names, while still respecting every historical
reservation recorded by the durable agent-name registry.

## Current behavior

Auto naming is local Python behavior in `src/sase/agent/names/_auto.py`, backed by the durable registry in
`src/sase/agent/names/_registry.py`. The current sequence is letter-first:

`a, b, ..., z, aa, ab, ..., az, a0, ..., a9, ba, ...`

The current prefix reservation regex in `src/sase/agent/names/_common.py` also only recognizes auto-name roots that
begin with `[a-z]`, so dotted descendants like `m.plan` reserve `m`, but numeric dotted descendants would not reserve
`1` if the allocator started using numeric roots.

The launch code already routes the important parent-side auto-name flows through this allocator:

- bare `%name` uses `get_next_auto_name()`
- multi-prompt planning uses `allocate_auto_names()`
- repeat batches use `reserve_repeat_name_base(None, count)`, which delegates to `get_next_auto_name()`
- fan-out naming in `xprompt/_directive_alt.py` uses `get_next_auto_name()` when no explicit/resume/wait name exists

Explicit-name launch validation currently rejects only hyphens, so numeric-leading names do not need a new syntax
exception. `%wait:1` is not treated as a time wait under the current time parser, so numeric names remain
wait-addressable.

## Design decisions

Use a shortlex auto-name order: exhaust one-character names before two-character names, and two-character names before
three-character names. This matches the request to use the smallest available name and to keep using one- and
two-character names until none remain.

Use `1` as the first numeric auto name, not `0`. Existing SASE numbering conventions in this code path are 1-based:
repeat children use `.1`, indexed names use `-1`, and their allocators start at `1`. To still remove the numeric-leading
constraint, include `0` as an allowed leading character after `1` through `9` in the one-character pool.

The new one-character order should be:

`1, 2, 3, 4, 5, 6, 7, 8, 9, 0, a, b, ..., z`

For two or more characters, use the same character order in each position, so after all one-character names are
reserved, allocation continues:

`11, 12, ..., 19, 10, 1a, 1b, ..., 1z, 21, ...`

Historical names remain reserved exactly as before. This is not a migration that renames prior agents; it only changes
future auto allocation.

## Implementation plan

1. Update `src/sase/agent/names/_auto.py`.
   - Replace the letter-first `_name_sequence()` with a single shortlex generator over the new auto alphabet.
   - Update comments/docstrings that describe the auto sequence.
   - Keep `_next_available_name()` and `allocate_auto_names()` behavior unchanged except for the sequence they iterate.

2. Update `src/sase/agent/names/_common.py`.
   - Expand `_AUTO_NAME_PREFIX_RE` so dotted auto roots beginning with digits are recognized, for example `1.plan`
     reserves `1`.
   - Keep the regex limited to names reachable by the auto sequence: lowercase letters and digits only, before the first
     dot.
   - Update the explanatory comment so it no longer claims auto roots must start with letters.

3. Review registry prefix behavior in `src/sase/agent/names/_registry.py`.
   - The registry already calls `extract_auto_name_prefix()` when rebuilding entries, so the regex change should make
     numeric dotted descendants reserve their numeric root automatically.
   - Add registry-focused tests rather than changing registry structure.

4. Update tests that encode old sequence expectations.
   - In `tests/test_agent_names_auto_name.py`, change empty allocation from `a` to `1`, add skip tests for `1`/`2`,
     verify wrap from one-character names to `11`, and verify numeric dotted descendants reserve their root.
   - Update existing letter-tail tests to reflect the new alphabet order, or replace them with clearer shortlex tests.
   - In `tests/test_names_repeat.py`, adjust auto-repeat expectations from letter roots to numeric roots and add a
     numeric child reservation case.
   - In launch planning tests such as `tests/test_launch_planned_agent_name.py` and multi-prompt launch tests, update
     expected planned auto names from `a` to `1` where the test is asserting default allocator behavior rather than
     explicitly mocking `get_next_auto_name()`.
   - Leave tests that deliberately mock `get_next_auto_name()` as `a` or `b` alone unless their purpose is sequence
     behavior.

5. Run focused validation first.
   - `just install`
   - `pytest tests/test_agent_names_auto_name.py tests/test_names_repeat.py tests/test_agent_name_registry.py tests/test_launch_planned_agent_name.py tests/test_multi_prompt_launcher_launch.py`

6. Run repo validation after implementation.
   - Because this change edits source files in the SASE repo, run `just check` before finishing.

## Risks and mitigations

- Numeric-leading auto names may interact with any implicit parsing that treats numbers as time or counts. I checked the
  prompt directive time parser: `%wait:1` is not parsed as a duration or absolute time, and explicit `%name:1` passes
  validation because only hyphens are rejected. Focused tests should still cover `%wait:1`.
- Dotted numeric descendants must reserve their root. Updating `extract_auto_name_prefix()` and testing registry
  rebuilds covers this.
- Broad test churn is possible because many launch tests assert `a` as the historical default. Only expectations tied to
  real allocation should change; mocked values and unrelated alphabetical fixtures should remain untouched.
