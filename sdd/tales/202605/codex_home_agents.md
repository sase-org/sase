---
create_time: 2026-05-31 08:16:32
status: done
prompt: sdd/prompts/202605/codex_home_agents.md
---
# Plan: Make SASE-launched Codex see home AGENTS.md

## Problem

SASE treats `~/AGENTS.md` as the home-level instruction root. `sase memory list` shows it as loaded alongside the
project `AGENTS.md`, and `sase amd list` reports the home AGENTS file and shims as managed.

The installed Codex CLI does not use `~/AGENTS.md` as its global instruction location. Its current global AGENTS
discovery is based on `CODEX_HOME`: Codex looks for `AGENTS.override.md` first and then `AGENTS.md` in `$CODEX_HOME`
(normally `~/.codex`). This machine has `~/AGENTS.md`, but no `~/.codex/AGENTS.md` or `~/.codex/AGENTS.override.md`, so
a SASE-launched Codex process can miss the home SASE instructions even though SASE's memory inventory correctly reports
them.

SASE also creates a disposable shadow `CODEX_HOME` for Codex subprocesses. That shadow home currently copies
`config.toml` and symlinks the rest of the real Codex home. This preserves native Codex global instructions if they
already exist in the real Codex home, but it does not bridge SASE's home instruction root from `~/AGENTS.md` into
Codex's expected global location.

## Goals

- Preserve Codex's native precedence: an existing real Codex `AGENTS.override.md` or `AGENTS.md` must win.
- When no native Codex-global AGENTS file exists, expose SASE's `~/AGENTS.md` to SASE-launched Codex via the shadow
  `CODEX_HOME`.
- Keep the behavior runtime-local to Codex invocation. Do not mutate `~/AGENTS.md`, `~/.codex`, or memory files.
- Keep shadow-home isolation: Codex may rewrite its shadow config, but user config and home memory files stay untouched.
- Document the bridge so the behavior is diagnosable.

## Proposed Implementation

1. Add a small helper in `src/sase/llm_provider/codex.py` that links the live home `AGENTS.md` into the shadow
   `CODEX_HOME` as `AGENTS.md` only when: the source `~/AGENTS.md` exists, the shadow does not already contain
   `AGENTS.md`, and neither the real Codex home nor the shadow contains `AGENTS.override.md`.

2. Call that helper from `_create_shadow_codex_home` after copying/symlinking real Codex-home entries. Also run it when
   the real Codex home does not exist, since the fallback still matters for users who have SASE home memory but no Codex
   home yet.

3. Add focused tests in `tests/test_llm_provider_codex_shadow_home.py`:
   - fallback links `~/AGENTS.md` into the shadow when real Codex global AGENTS files are absent.
   - a real `$CODEX_HOME/AGENTS.md` remains the chosen global file.
   - a real `$CODEX_HOME/AGENTS.override.md` suppresses the fallback.

4. Update `docs/configuration.md` near the Codex shadow-home section to mention that SASE links `~/AGENTS.md` into the
   shadow only as a fallback for Codex's `$CODEX_HOME/AGENTS.md` global-instruction mechanism.

## Verification

- Run the focused Codex shadow-home tests first.
- Because this repo requires it after source/doc changes, run `just install` if needed and then `just check`.
- Optionally inspect a mocked or local Codex launch env to confirm the shadow home receives `AGENTS.md` only in the
  fallback case.

## Risks

- If a user intentionally wants SASE-launched Codex to ignore `~/AGENTS.md`, this makes the home memory contract
  stronger for Codex. Existing native Codex-global files still provide the opt-out path by taking precedence.
- Users who disable the shadow home with `SASE_CODEX_DISABLE_SHADOW_HOME=1` will not get this runtime bridge, because
  SASE then does not control `CODEX_HOME`.
