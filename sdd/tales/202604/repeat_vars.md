---
create_time: 2026-04-14 20:41:13
status: done
prompt: sdd/prompts/202604/repeat_vars.md
---

# Plan: Split repeat directive Jinja2 variables into `n` (iteration) and `N` (total)

## Problem

The `%repeat` directive currently exposes a single Jinja2 variable `N` containing the 1-based iteration number. Users
who want to reference the total count must hard-code it (e.g. `{{ N }} of 5`). This is fragile — if you change
`%repeat:5` to `%repeat:10`, you must also update the prompt body.

## Desired behavior

| Variable | Meaning                                   | Example with `%repeat:5` |
| -------- | ----------------------------------------- | ------------------------ |
| `n`      | Current iteration (1-based)               | 1, 2, 3, 4, 5            |
| `N`      | Total iterations (the `%repeat` argument) | 5                        |

Users can write `{{ n }} of {{ N }}` and only change the directive argument.

## Changes

### 1. Thread `repeat_count` into `run_execution_loop()`

**`run_agent_exec.py`** — Add a `repeat_count: int | None = None` parameter alongside `repeat_iteration`. Inject both
into `named_args`:

```python
**({"n": repeat_iteration, "N": repeat_count} if repeat_iteration is not None else {}),
```

**`run_agent_runner.py:362-363`** — Pass `repeat_count=repeat_count` to the call.

### 2. Update tests

**`tests/test_axe_run_agent_runner_repeat.py`** — Update both test methods:

- `test_n_injected_when_repeat_iteration_set` → assert `named_args["n"] == 3` and `named_args["N"]` equals the total
- `test_n_not_injected_without_repeat_iteration` → assert neither `n` nor `N` in named_args

### 3. Update documentation

**`docs/xprompt.md:715-732`** — Update the Repeat Directive section to describe both variables and show the
`{{ n }} of {{ N }}` pattern.
