---
create_time: 2026-06-02 13:53:30
status: done
prompt: sdd/prompts/202606/auto_name_zero_first.md
---
# Auto Name Zero-First Plan

## Context

Auto-generated agent names currently use this alphabet:

```text
1234567890abcdefghijklmnopqrstuvwxyz
```

Because `_name_sequence()` generates names in shortlex order, the existing sequence is:

```text
1, 2, ..., 9, 0, a, ..., z, 11, 12, ...
```

The requested behavior is for numeric names to start at zero and end at nine. The new alphabet should be:

```text
0123456789abcdefghijklmnopqrstuvwxyz
```

With that ordering, once all single-character names `0` through `z` are reserved, the next available generated name is
`00`.

## Design

1. Change the shared auto-name alphabet in `src/sase/agent/names/_auto.py` to put digits in normal numeric order before
   lowercase letters.
2. Keep the existing shortlex generator shape. This preserves the important property that all one-character names are
   exhausted before two-character names, so the sequence becomes:

   ```text
   0, 1, ..., 9, a, ..., z, 00, 01, ...
   ```

3. Update nearby docstrings and comments that describe the sequence, including `reserve_repeat_name_base()` in
   `src/sase/agent/names/__init__.py`.
4. Make parent-side planned auto-name allocation use the durable reserved-name registry rather than only the visible
   active-agent snapshot. This matters for the concrete expected launch behavior: if historical/dismissed names `0`
   through `z` are still reserved, the next launched agent should be planned as `00` instead of reusing `0`.
5. Preserve existing behavior for explicit names, wait-derived names, resume/fork-derived names, indexed templates, name
   claims, force reuse, wipe/delete reuse, and the historical migration. The migration should not be broadened just
   because the fresh auto alphabet now includes numeric names.

## Tests

Update and extend the focused tests around auto naming:

1. In `tests/test_agent_names_auto_name.py`, update constants and expectations so an empty registry returns `0`, skipped
   names advance to `1`, all single-character names advance to `00`, and two-character tails order as
   `00, 01, ..., 09, 0a, ..., 0z, 10`.
2. Add or adjust a regression that reserves every single-character name from `0` through `z` and asserts
   `get_next_auto_name() == "00"`.
3. Update parent-side launch planning expectations in `tests/test_launch_planned_agent_name.py` and
   `tests/test_multi_prompt_launcher_launch.py` so bare auto launches plan `0`, then `1`, and wait chains derive from
   `0`.
4. Update repeat-child collision tests in `tests/test_names_repeat.py` so an orphan child like `0.2` reserves root `0`
   and the repeat base advances to `1`.
5. Update child-side directive extraction tests in `tests/test_agent_names_extract.py` where unplanned auto fallback now
   returns `0` first, and concurrent allocation returns `0` and `1`.
6. Search for remaining hard-coded old auto-name expectations and update only those that assert generated auto-name
   ordering.

## Verification

Run targeted tests first:

```bash
python -m pytest tests/test_agent_names_auto_name.py tests/test_names_repeat.py tests/test_launch_planned_agent_name.py tests/test_multi_prompt_launcher_launch.py tests/test_agent_names_extract.py
```

Then run the repository check required after code changes:

```bash
just install
just check
```
