---
create_time: 2026-05-12 19:15:38
status: done
prompt: sdd/prompts/202605/workspace_env_spawn_leak.md
---
# Fix workspace-env leak across agent spawns

Fix the `SASE_ACTIVE_PROJECT_DIR` / `CODEX_PROJECT_DIR` env-leak bug that caused the `sase-39.1` Codex commit fallback
to inspect the wrong workspace and skip committing.

## Background

The `sase-39.1` Codex agent (session `20260512183050`) ran in `/home/bryan/projects/github/sase-org/sase_101/`, made
changes (still uncommitted today: `src/sase/agent/launch_failures.py` and modified launcher files), and triggered the
in-band Codex commit fallback. The fallback skipped with `reason=no_changes` because it inspected
`/home/bryan/projects/github/sase-org/sase_106/` (clean) instead of `sase_101`.

Verified log entry from `~/.sase_commit_stop_hook.jsonl`:

```json
{
  "timestamp": "2026-05-12T18:39:40-04:00",
  "event": "codex_fallback_skip",
  "reason": "no_changes",
  "session_id": "20260512183050",
  "native_marker_present": false,
  "project_dir": "/home/bryan/projects/github/sase-org/sase_106/",
  "cwd": "/home/bryan/projects/github/sase-org/sase_101"
}
```

The skip log lacks a `workspace_env` field, so per the logic at `src/sase/llm_provider/codex.py:428-430` the stale value
came from either `CODEX_PROJECT_DIR` or `SASE_ACTIVE_PROJECT_DIR` (not `SASE_GIT_WORKSPACE_DIR` /
`SASE_CD_WORKSPACE_DIR`).

## Root cause

`apply_chdir_output()` at `src/sase/xprompt/workflow_executor_utils.py:142-152` mutates
`os.environ[SASE_ACTIVE_PROJECT_DIR]` in the executor process when a workflow's `_chdir` output fires. The ACE process /
parent then accumulates that mutation in its own `os.environ`. When that parent later calls `spawn_agent_subprocess()`
at `src/sase/agent/launch_spawn.py:60` to launch a new agent (`sase-39.1` here), the env-stripping helpers at lines
22-27 only drop `SASE_*_PRE_ALLOCATED` / `_WORKSPACE_NUM` / `_WORKSPACE_DIR` keys — `SASE_ACTIVE_PROJECT_DIR` and
`CODEX_PROJECT_DIR` leak through.

Inside the child, the agent runner chdir's correctly to its workspace at `src/sase/axe/run_agent_runner.py:192` but
never resets `SASE_ACTIVE_PROJECT_DIR`. The new chdir happens _only_ on `cwd`, not the env var. Result: env says
`sase_106`, cwd says `sase_101`. `_resolve_codex_project_dir()` (`src/sase/llm_provider/codex.py:134-141`) trusts the
env over cwd by design and returns `sase_106`. Same hazard exists for the native `sase_commit_stop_hook.py` resolver
(`src/sase/scripts/sase_commit_stop_hook.py:88`) which checks `CLAUDE/GEMINI/CODEX_PROJECT_DIR` — though that path uses
subprocess-isolated hooks so the immediate fault here is the Codex in-band fallback.

## What the previous fix got wrong

The `sdd/tales/202605/codex_fallback_workspace_env.md` tale added workspace-env precedence and richer diagnostics, but
assumed the env vars in the precedence chain would always be correct for the current agent. It didn't consider that
`os.environ` mutations in the ACE parent (from `apply_chdir_output`) outlive any single workflow and leak into
subsequent spawns. The diagnostics added by that fix (`cwd`, `workspace_env`) are exactly what let us identify this bug
— keep those, but also fix the leak.

## Fix scope

The bug is at the spawn boundary: the parent process's accumulated env state should not contaminate a freshly-launched
agent whose workspace is known at spawn time. Fix it by explicitly authoring the workspace-pointing env in
`spawn_agent_subprocess`, and by guaranteeing the agent's own runner keeps it consistent if it later chdirs.

Out of scope:

- Changing `_resolve_codex_project_dir()` precedence (current order is correct given the fix below).
- Reworking `apply_chdir_output()` to stop mutating `os.environ` (it should mutate — it just shouldn't leak across
  spawns).
- Recovering the existing dirty `sase_101` workspace (separate task).
- Native commit-stop hook for non-Codex runtimes (subprocess-isolated; lower risk; defer until/unless we see the same
  symptom there).

## Plan

### 1. Rewrite workspace env at the spawn boundary (`src/sase/agent/launch_spawn.py`)

In `spawn_agent_subprocess`, after the existing `_remove_inherited_*` calls and the
`subprocess_env.update(prepared.env_delta)` (around line 175), add an explicit overwrite of workspace-pointing env vars
to match the child agent's actual workspace:

```python
subprocess_env["SASE_ACTIVE_PROJECT_DIR"] = workspace_dir
subprocess_env.pop("CODEX_PROJECT_DIR", None)
```

Rationale:

- `SASE_ACTIVE_PROJECT_DIR`: explicitly overwrite (not just strip) because downstream code in the child (e.g.
  `_resolve_codex_project_dir`) consults it before falling to cwd. Setting it correctly at spawn time means any race
  between `os.chdir` and a fallback firing is harmless.
- `CODEX_PROJECT_DIR`: strip (not overwrite). It's authored per Codex CLI invocation inside `_codex_subprocess_env()` at
  `src/sase/llm_provider/codex.py:179,186`, derived from `_resolve_codex_project_dir()`. Stripping the inherited value
  means that resolver no longer reads a stale parent value as the highest-priority signal; it instead falls through to
  `SASE_ACTIVE_PROJECT_DIR` (which we just set correctly).

Prefer a sibling helper `_overwrite_project_dir_env(env, workspace_dir)` over extending
`_remove_inherited_workspace_preallocation_env`, since the semantics differ (one strips, the other overwrites).

### 2. Keep the runner's chdir and env in sync

At `src/sase/axe/run_agent_runner.py:192` (`os.chdir(workspace_dir)`), also set
`os.environ["SASE_ACTIVE_PROJECT_DIR"] = workspace_dir` immediately after. This is defense-in-depth: even if some future
code path skips the spawn helper (e.g. an in-process agent invocation), the runner itself guarantees the env matches
cwd.

This mirrors what `apply_chdir_output()` already does for workflow chdirs.

Also handle the other workspace-binding chdir sites:

- `src/sase/axe/run_agent_phases.py:594`
- `src/sase/axe/run_workflow_runner.py:148`
- `src/sase/axe/run_agent_exec_retry.py:188, 223`

For each, add the matching `os.environ` set. Skip `src/sase/axe/lumberjack.py:540` (chdir to `~`) — that's intentional
cleanup, not workspace-binding.

### 3. Tests

**a. Spawn-env behavior** in `tests/test_cd_spawn_env.py` (or a new `tests/test_agent_spawn_env.py`):

- `test_spawn_agent_subprocess_overwrites_stale_active_project_dir`: set `SASE_ACTIVE_PROJECT_DIR` in the parent to a
  stale path, call `spawn_agent_subprocess` (mocking the actual process spawn via `spawn_prepared_agent_process`),
  assert the env passed to the spawn matches `workspace_dir`, not the stale value.
- `test_spawn_agent_subprocess_strips_stale_codex_project_dir`: same shape, but for `CODEX_PROJECT_DIR`, assert it's
  absent from the spawn env.

**b. Runner's chdir-env coupling**:

- `test_run_agent_runner_sets_active_project_dir_on_chdir`: invoke the runner code path that hits the chdir, assert
  `os.environ["SASE_ACTIVE_PROJECT_DIR"]` matches `workspace_dir` after. Use monkeypatch to isolate.

**c. Regression test for the actual bug** in `tests/test_llm_provider_codex_fallback.py`:

- `test_codex_fallback_inspects_spawn_workspace_when_parent_env_stale` — set up env where the parent's
  `SASE_ACTIVE_PROJECT_DIR` points at a clean repo and the spawned child's `workspace_dir` is a dirty one; construct via
  the spawn helper; assert the dirty workspace is the one inspected and a commit block is emitted.

### 4. Validation

```bash
just install
.venv/bin/pytest tests/test_cd_spawn_env.py tests/test_llm_provider_codex_fallback.py \
  tests/test_commit_stop_hook.py -x
just check
```

Manual smoke check: in this repo, set `SASE_ACTIVE_PROJECT_DIR=/tmp/somewhere-else` in the shell, run a small `#gh:sase`
agent that makes a one-line edit, confirm the commit fires against the agent's actual workspace and
`~/.sase_commit_stop_hook.jsonl` no longer shows a `project_dir` ≠ `cwd` divergence.

## Risk

Low-medium.

- The spawn-env overwrite is additive and only changes behavior when the parent has a stale value (the bug case). No
  code currently relies on the leak.
- The runner chdir-env coupling could theoretically conflict with code that intentionally chdirs without wanting
  `SASE_ACTIVE_PROJECT_DIR` to follow — grep `os.chdir` confirms no such case; all listed chdirs are workspace-binding
  except `lumberjack.py:540` which we skip.
- The native commit-stop hook path (Claude/Gemini/etc.) isn't touched. They use subprocess hooks with their own
  resolver; if the same bug shape ever surfaces there, the runner-level env fix in step 2 already prevents one class of
  leak. A follow-up could harden `sase_commit_stop_hook._resolve_project_dir` if needed.
