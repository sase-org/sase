---
create_time: 2026-04-11 22:22:51
status: done
prompt: sdd/prompts/202604/repeat_iteration_variable.md
---

# Plan: Expose `N` Jinja variable for `%N` / `%repeat` directive

## Problem

The `%N` directive (alias for `%repeat`) runs a prompt N times sequentially in a single workspace. The iteration number
is tracked internally for TUI display via `repeat_state.json`, but is **not** exposed to the prompt template. Users have
no way to know which iteration they're on inside the prompt.

## Goal

When `%N:5` (or `%repeat:5`) is used, make a Jinja variable `N` available so that `{{ N }}` renders to the current
1-based iteration number (1, 2, 3, 4, 5).

## Design

The prompt flows through this chain:

```
run_agent_runner.py  repeat loop (iteration 1..N)
  → run_execution_loop(ctx, prompt)
    → execute_workflow(name, [], {"cl_name": ..., "workspace_num": ...}, ...)
      → WorkflowExecutor(args=named_args)  # self.context = dict(args)
        → _execute_prompt_step()
          → preprocess_prompt_early(step.agent, context=self.context)  # Jinja2 render
```

The iteration number needs to be threaded from the repeat loop into the workflow's named_args so it lands in
`self.context` and is available to Jinja2 rendering.

### Phase 1: Thread iteration through `run_execution_loop`

**`src/sase/axe/run_agent_exec.py`** — Add `repeat_iteration: int | None = None` parameter to `run_execution_loop()`.
When building the named_args dict for `execute_workflow()`, inject `"N": repeat_iteration` if set.

**`src/sase/axe/run_agent_runner.py`** — In the repeat loop (line 328), pass `repeat_iteration=iteration`. The
non-repeat else branch (line 353) leaves it as None, so `N` is not injected.

### Phase 2: Tests

**`tests/test_axe_run_agent_runner_repeat.py`** — Test that `{{ N }}` in a prompt template is rendered correctly when
repeat_iteration is provided via the named_args pathway.

**`tests/test_preprocessing.py`** — Test that `preprocess_prompt_early` renders `{{ N }}` when context contains
`{"N": 3}`.

### Edge case: `{{ N }}` without `%N`

Jinja2 will raise `UndefinedError` since `N` won't be in the context. This is correct — it tells the user they need
`%N`. No special handling needed.

### Not in scope

- Exposing `REPEAT_COUNT` or other variables
- Environment variable approach
- Documentation (xprompt.md doesn't document `%repeat` yet)
