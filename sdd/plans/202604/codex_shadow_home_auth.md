---
create_time: 2026-04-30 01:37:52
status: done
prompt: sdd/prompts/202604/codex_shadow_home_auth.md
---
# Plan: Fix Codex Auth Loss From Nested Shadow Homes

## Problem

Recent SASE-launched Codex agents fail with:

```text
401 Unauthorized: Missing bearer or basic authentication in header
```

The failures are not generic OpenAI authentication failures. The live `~/.codex/auth.json` exists, and currently running
Codex sessions can see a shadow `CODEX_HOME` that symlinks back to the real auth file.

The risky path is SASE's Codex provider shadow-home feature. `src/sase/llm_provider/codex.py` resolves the "real" Codex
home from `$CODEX_HOME` when present. That is valid when `$CODEX_HOME` is a user-managed Codex home, but invalid when
SASE itself is running inside a Codex subprocess launched by SASE:

1. Parent SASE Codex invocation creates `~/.cache/sase/codex_home/<pid>-<uuid>` and runs `codex exec` with
   `CODEX_HOME=<that shadow>`.
2. The Codex agent launches detached/queued SASE agents. Those child SASE processes inherit the parent shadow path.
3. The parent Codex invocation exits and SASE removes that shadow directory.
4. A later queued child agent starts its own Codex provider invocation. `_real_codex_home()` trusts the inherited
   `CODEX_HOME`, sees a deleted directory, creates an empty shadow home, and Codex starts without `auth.json`.

That directly explains the snapshot: agents that begin after waiting can fail with missing bearer auth even though the
normal user Codex home is authenticated.

## Goals

- Keep the shadow-home protection that prevents Codex from dirtying `~/.codex/config.toml`.
- Make nested or detached SASE-launched Codex agents resolve the persistent user Codex home, not an ephemeral parent
  shadow home.
- Avoid leaking stale `CODEX_HOME` into detached SASE agent runners.
- Add focused regression coverage for the deleted-shadow-home case and subprocess environment sanitization.

## Implementation

### Phase 1: Canonical Codex Home Resolution

Update `src/sase/llm_provider/codex.py`:

- Add a helper that identifies SASE-managed Codex shadow homes under `~/.cache/sase/codex_home`.
- Change `_real_codex_home()` so it ignores `$CODEX_HOME` when it points inside that SASE shadow-home root.
- If `$CODEX_HOME` is unset or points at a SASE shadow home, fall back to `~/.codex`.
- Continue honoring non-SASE custom `CODEX_HOME` values so tests and advanced user setups still work.

### Phase 2: Detached Agent Environment Sanitization

Update `src/sase/agent/launcher.py`:

- When building the detached agent runner environment, remove `CODEX_HOME` if it points inside SASE's Codex shadow-home
  root.
- Leave non-SASE `CODEX_HOME` values intact.
- Keep existing `extra_env` behavior, allowing explicit caller overrides after the base environment is sanitized.

This prevents queued/running SASE agent processes from carrying a parent invocation's temporary Codex home after that
parent exits.

### Phase 3: Tests

Extend focused tests:

- `tests/test_llm_provider_codex.py`
  - `_real_codex_home()` ignores a SASE-managed shadow `CODEX_HOME`.
  - a deleted inherited SASE shadow home still produces a new shadow that links real `~/.codex/auth.json`.
  - non-SASE custom `CODEX_HOME` remains honored.
- Add or extend launcher tests around `spawn_agent_subprocess()`:
  - inherited SASE shadow `CODEX_HOME` is removed from the detached runner env;
  - custom non-SASE `CODEX_HOME` is preserved;
  - explicit `extra_env["CODEX_HOME"]` still wins.

## Verification

Run:

```bash
just install
pytest tests/test_llm_provider_codex.py tests/test_axe_chop_agents.py tests/test_multi_prompt_launcher.py
just check
```

Also inspect the resulting mocked subprocess environments to ensure `auth.json` comes from `~/.codex` and no stale SASE
shadow path is propagated to child agent runners.
