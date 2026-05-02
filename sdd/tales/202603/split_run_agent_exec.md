---
create_time: 2026-03-27 08:58:56
status: done
prompt: sdd/prompts/202603/split_run_agent_exec.md
---

# Plan: Split `run_agent_exec.py` into multiple files

## Problem

`src/sase/axe/run_agent_exec.py` is 714 lines, dominated by one massive `run_execution_loop` function (~543 lines). The
function mixes retry handling, plan marker handling, questions marker handling, and finalization — all deeply nested
inside one `while True` loop.

## Public API (must remain importable from `sase.axe.run_agent_exec`)

- `AgentExecContext` — imported by `run_agent_runner.py`
- `run_execution_loop` — imported by `run_agent_runner.py`
- `_get_embedded_workflow_refs` — imported by `tests/test_xprompt_tags_rollover.py`
- Mock path `sase.axe.run_agent_exec` — used in `tests/test_axe_run_agent_runner_retry.py`

## Proposed split (3 files)

### 1. `run_agent_exec.py` — orchestrator (~300 lines)

Keep as the entry point. All existing imports continue to work.

- `AgentExecContext` dataclass (unchanged)
- `_AgentExecResult` dataclass (unchanged)
- New `_LoopState` dataclass — bundles the ~12 mutable loop variables into a single object passed to handlers
- `run_execution_loop()` — simplified: the while-loop body calls out to handler functions, post-loop calls
  `_finalize_loop()`
- `_finalize_loop()` — extracted from lines 596–713 (cleanup, done marker, result construction)
- Re-export `_get_embedded_workflow_refs` from `run_agent_exec_plan` so test imports keep working

### 2. `run_agent_exec_retry.py` — retry/error handling (~130 lines)

Extract the 100-line exception handler (lines 220–321) into a clean function.

- `_RetryAction` — enum or literal type: `"continue"` | `"break"` | `"raise"`
- `_RetryTracker` — dataclass holding `retry_cfg`, `retry_errors`, `retry_count`, `using_fallback`
- `handle_workflow_error(exc, tracker, ctx, state)` → `_RetryAction` — encapsulates all retry/fallback logic

### 3. `run_agent_exec_plan.py` — plan, questions, and artifact helpers (~330 lines)

Extract the plan marker branch (lines 336–536) and questions marker branch (lines 538–589), plus the three helper
functions they use.

- `_commit_sdd_files()` — moved from `run_agent_exec.py`
- `_write_plan_path_artifact()` — moved from `run_agent_exec.py`
- `_get_embedded_workflow_refs()` — moved from `run_agent_exec.py` (re-exported by `run_agent_exec.py`)
- `handle_plan_marker(plan_data, ctx, state)` → `str | None` — returns loop outcome if should break, else None
  (continue)
- `handle_questions_marker(q_data, ctx, state)` → `str | None` — same pattern

## `_LoopState` dataclass

```python
@dataclass
class _LoopState:
    current_prompt: str
    current_role_suffix: str
    current_artifacts_dir: str
    loop_outcome: str
    sdd_spec_path: str | None
    original_prompt: str
    qa_sections: list[str]
    feedback_bullets: list[str]
    feedback_round: int
    agent_step: int
    allow_retry: bool
```

Handlers mutate the state object in-place and return a signal ("continue" / loop_outcome string / None).

## Implementation steps

1. Create `run_agent_exec_retry.py` with `_RetryTracker` and `handle_workflow_error()`
2. Create `run_agent_exec_plan.py` with the three helpers + `handle_plan_marker()` + `handle_questions_marker()`
3. Rewrite `run_agent_exec.py`: add `_LoopState`, simplify `run_execution_loop()`, add `_finalize_loop()`, re-export
   `_get_embedded_workflow_refs`
4. Update test imports if needed (should be minimal since we re-export)
5. Run `just install && just lint && just test`
