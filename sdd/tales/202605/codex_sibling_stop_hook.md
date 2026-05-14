---
create_time: 2026-05-13 22:34:58
status: done
prompt: sdd/prompts/202605/codex_sibling_stop_hook.md
---
# Plan: Fix Codex Sibling Stop Hook Execution

## Problem

Codex phase agents in the `sase-3e.*` family have been leaving changes in the primary sibling repo `../sase-core`
without being stopped by `tools/sase_sibling_commit_stop_hook`.

The old Codex sibling-hook failure modes are already addressed in the current tree:

- SASE-launched Codex agents receive `CODEX_PROJECT_DIR`.
- `~/.codex/hooks.json` and its chezmoi source invoke the sibling hook with a `$PWD` fallback when `CODEX_PROJECT_DIR`
  is absent.
- `tests/test_sibling_commit_stop_hook.py` proves the hook script blocks for dirty primary sibling repos and skips
  ephemeral `sase-*_N` workspaces.

The current evidence points elsewhere:

- Recent `sase-3e.4.*` Codex phase agents produced `codex_fallback_*` records in `~/.sase_commit_stop_hook.jsonl`,
  meaning SASE's in-band Codex fallback ran.
- Those same runs did not produce native Codex `script_start` records for `sase_commit_stop_hook`, and only a few recent
  `sase_sibling_hook_done_*` marker files exist.
- The live and chezmoi Codex hook config files contain the expected `Stop` hook commands, but the live and chezmoi Codex
  `config.toml` files do not enable Codex hooks.
- The local Codex hook documentation requires:

  ```toml
  [features]
  codex_hooks = true
  ```

So the likely root cause is that Codex is loading the config but ignoring `hooks.json` because `codex_hooks` is not
enabled. SASE's in-band fallback only checks the active SASE workspace, not sibling repositories, which explains why
workspace commits are caught while `../sase-core` changes are not.

## Goals

1. Enable native Codex hooks for SASE-managed Codex sessions.
2. Preserve the existing Codex shadow-home behavior: SASE should continue copying the real `config.toml` into the shadow
   `CODEX_HOME`.
3. Keep sibling detection repo-local and scoped exactly as it is today:
   - primary `../sase-*` sibling repos;
   - `~/.local/share/chezmoi`;
   - no ephemeral `_<number>` workspaces.
4. Add regression coverage so the Codex config cannot lose hook enablement silently.
5. Verify that a real Codex/SASE launch path will now execute native hooks, not just the in-band fallback.

## Implementation

### 1. Update Codex config source

Modify the chezmoi-managed Codex config source:

```text
~/.local/share/chezmoi/home/dot_codex/config.toml
```

Add:

```toml
[features]
codex_hooks = true
```

Place it before project-specific and hook-state tables so it remains easy to spot.

Then apply the chezmoi source to the live config:

```bash
chezmoi apply --force
```

Verify `~/.codex/config.toml` contains the same feature flag.

### 2. Add config regression coverage

Add or extend a chezmoi test that inspects `home/dot_codex/config.toml` and asserts:

- `[features]` exists;
- `codex_hooks = true`;
- `home/dot_codex/hooks.json` still contains `sase_commit_stop_hook`;
- `home/dot_codex/hooks.json` still contains `sase_sibling_commit_stop_hook`.

If the chezmoi test suite has no TOML/JSON config test harness, add a small bash test under its existing test
conventions rather than adding a new dependency.

### 3. Improve in-repo diagnostics coverage

In this repo, add a focused test around `_create_shadow_codex_home` or `_codex_subprocess_env` only if the existing
coverage does not already assert that the shadow home receives a copied `config.toml`. The test should not depend on the
user's real `~/.codex`; it should use a temporary `CODEX_HOME` source and verify the shadow config file contains the
same feature flag.

Do not reimplement sibling scanning in Python; the existing bash hook tests already cover the scanner.

### 4. Manual smoke test

Run a controlled smoke test after applying the config:

1. Create or use a temporary dirty primary sibling repo under a temporary parent with a fake `sase` project checkout.
2. Execute Codex with a minimal prompt from that project directory and with a temporary `CODEX_HOME` that contains:
   - `config.toml` with `[features] codex_hooks = true`;
   - `hooks.json` with a tiny `Stop` hook that appends to a temp log.
3. Confirm the temp stop hook log is written.
4. Separately execute the real `tools/sase_sibling_commit_stop_hook` command shape against a dirty sibling repo and
   confirm it emits a Codex JSON block payload.

This avoids mutating the current real sibling repo state while proving the native Codex hook machinery now fires.

## Verification

Run, in this repo:

```bash
just install
pytest tests/test_sibling_commit_stop_hook.py
just check
```

Run, in `~/.local/share/chezmoi`:

```bash
just check
```

Finally, inspect recent logs after a Codex smoke run:

```bash
tail -n 50 ~/.sase_commit_stop_hook.jsonl
```

A native Codex hook run should produce a `script_start` record with `runtime: "codex"`; sibling dirty-state runs should
also create a `sase_sibling_hook_done_<session>` marker when they block.
