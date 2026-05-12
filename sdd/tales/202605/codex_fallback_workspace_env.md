---
create_time: 2026-05-12 15:12:30
status: done
prompt: sdd/prompts/202605/codex_fallback_workspace_env.md
---
# Codex fallback: add workspace-env precedence and richer skip diagnostics

## Background

Commit `25356a7e fix: honor workflow project dir for Codex fallback` implemented the `codex_phase_commit_workspace`
plan. Resolution now flows through `_resolve_codex_project_dir`:

```
CODEX_PROJECT_DIR → SASE_ACTIVE_PROJECT_DIR → os.getcwd()
```

`SASE_ACTIVE_PROJECT_DIR` is set whenever a workflow script step emits `_chdir=<path>`, which covers the embedded
`#gh:sase` / `#git` setup paths that produced the `sase-36.x` symptoms.

A separate plan, `~/.sase/plans/202605/codex_phase_agent_commit_fallback.md`, diagnosed the same incident from a
different angle and proposed:

1. Use the SASE phase-agent workspace env vars as a fallback signal (the plan names `SASE_GH_WORKSPACE_DIR` /
   `SASE_GIT_WORKSPACE_DIR`).
2. Capture the project dir once at the top of `invoke()` and thread it through.
3. Enrich the `codex_fallback_skip reason=no_changes` log with `project_dir`, `cwd`, and the workspace env value so the
   next regression is one log read.
4. Add focused tests for both behaviors.

## Assessment of the alternative plan against current code

- **Item 1 — workspace env fallback.** Legitimate gap. Today's resolution chain only catches the embedded-workflow case
  (where `_chdir` populates `SASE_ACTIVE_PROJECT_DIR` inside the parent process). When the agent is spawned as its own
  subprocess via `spawn_agent_subprocess`, the child inherits `SASE_GIT_WORKSPACE_DIR` / `SASE_CD_WORKSPACE_DIR` on its
  env (see `tests/test_cd_spawn_env.py`), but no `_chdir` step runs inside that subprocess, so `SASE_ACTIVE_PROJECT_DIR`
  is absent. If cwd in that subprocess ever drifts (a workflow `finally`, a `cd` inside the agent's tool calls, a
  workspace cleanup), the fallback falls all the way to `os.getcwd()` and re-introduces the same TOCTOU window the
  original fix closed for embedded flows. Adding `SASE_GIT_WORKSPACE_DIR` and `SASE_CD_WORKSPACE_DIR` to the precedence
  chain closes that window cheaply.

  Note: `SASE_GH_WORKSPACE_DIR` does not exist in the codebase (grep confirms); the GitHub flow runs as an embedded
  workflow inside the parent and is already covered by `SASE_ACTIVE_PROJECT_DIR`. Skip the `_GH_` name.

- **Item 2 — capture once at `invoke()` and thread through.** Not worth the refactor. The current code reads
  `os.environ` at the fallback site and at the subprocess-env construction site; both are inside the same `invoke()`
  call and there is no observable behavior difference vs. capturing once. Threading the value through changes signatures
  without closing any bug. Skip.

- **Item 3 — richer skip diagnostics.** Worth doing. The `block_emitted` branch already logs `project_dir`; bringing
  `no_changes` to parity costs nothing and the alternative plan's stated motive ("turn the next occurrence into a
  one-line log read") applies regardless of the resolution chain. Add `cwd` and the inspected workspace env value
  alongside the existing `project_dir`.

- **Item 4 — tests.** Add the two cases the alternative plan specifies, scoped to the new precedence layer.

## Plan

### 1. Extend resolution chain in `src/sase/llm_provider/codex.py`

Update `_resolve_codex_project_dir` to consult the SASE workspace env vars between `SASE_ACTIVE_PROJECT_DIR` and
`os.getcwd()`:

```
CODEX_PROJECT_DIR
→ SASE_ACTIVE_PROJECT_DIR
→ SASE_GIT_WORKSPACE_DIR
→ SASE_CD_WORKSPACE_DIR
→ os.getcwd()
```

Keep the helper a single small function — no signature changes elsewhere.

### 2. Enrich `no_changes` skip log

In `_maybe_run_commit_fallback_turn`, extend the `codex_fallback_skip reason=no_changes` `jlog` call to also record:

- `cwd`: `os.getcwd()` at the moment of the check.
- `workspace_env`: the first non-empty value among the workspace env vars we consult, or absent if none are set.

`project_dir` is already included.

### 3. Tests in `tests/test_llm_provider_codex_fallback.py`

- `test_codex_fallback_uses_workspace_env_when_cwd_diverges`: set `SASE_GIT_WORKSPACE_DIR` to a path, leave
  `SASE_ACTIVE_PROJECT_DIR` and `CODEX_PROJECT_DIR` unset, assert `build_commit_details` is called with the workspace
  path even when `os.getcwd()` is something else. Use the same mock shape the other tests use; we don't need a real git
  repo because `build_commit_details` is monkeypatched.
- `test_codex_fallback_skip_log_includes_diagnostics`: capture `jlog` calls, trigger a `no_changes` skip, assert the
  recorded payload includes `project_dir`, `cwd`, and `workspace_env` keys.

### 4. Validation

```bash
just install
.venv/bin/pytest tests/test_llm_provider_codex_fallback.py tests/test_commit_stop_hook.py -x
just check
```

## Out of scope

- Threading `project_dir` through as an explicit `invoke()` local.
- Backporting workspace-env precedence to Claude / Gemini / Qwen / opencode. They use the native Stop hook, which has
  its own resolver (`sase_commit_stop_hook._resolve_project_dir`). If we see the same symptom there, extend that
  resolver as a follow-up.
- Recovering the existing dirty `sase-36.x` workspaces.

## Risk

Low. The resolution change adds two more env vars to an existing precedence chain; the new entries only fire when those
vars are populated (the phase-agent spawn path) and otherwise no-op. The log change is additive keys on an existing
event.
