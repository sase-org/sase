---
create_time: 2026-04-28 18:36:55
status: done
prompt: sdd/prompts/202604/codex_config_churn.md
---
# Plan: Stop Codex from Dirtying Managed Config

## Problem

SASE launches Codex with:

```bash
codex exec --dangerously-bypass-approvals-and-sandbox --json --color never --skip-git-repo-check -
```

That invocation inherits the user's real `CODEX_HOME` (`~/.codex`). Codex CLI 0.125.0 persists runtime state back into
`~/.codex/config.toml`, including an exact `[projects."<cwd>"] trust_level = "trusted"` block for the current workspace.
It does this even when the managed config already trusts the parent `/home/bryan` path. Since SASE workspaces are
ephemeral sibling clones (`sase_100`, `sase_101`, etc.), each Codex run can add another transient workspace path to a
chezmoi-managed file.

Isolated reproduction with a temporary `CODEX_HOME` confirmed:

- `codex debug prompt-input` rewrites `config.toml` permissions to `0664`, explaining chezmoi mode churn.
- `codex exec --dangerously-bypass-approvals-and-sandbox` adds the exact workspace trust block.
- `--ephemeral` does not prevent config writes.
- `--ignore-user-config` does not prevent config writes.
- Passing a matching project trust override via `-c` does not prevent Codex from persisting the project trust block.

Therefore this is not caused by the chezmoi source file and is not fixable by adding broader trust entries there.

## Approach

Add a Codex-provider-local "shadow CODEX_HOME" for SASE-launched Codex processes.

The shadow home should give Codex a disposable copy of `config.toml` while preserving access to the user's real auth,
hooks, skills, logs, state, and caches as much as possible:

1. Resolve the real Codex home from `$CODEX_HOME` or `~/.codex`.
2. Create a per-invocation shadow directory under a non-`/tmp` cache path such as `~/.cache/sase/codex_home/<unique-id>`
   to avoid Codex's warning about helper binaries under temporary directories.
3. For each entry in the real Codex home:
   - copy `config.toml` into the shadow home so Codex can mutate only the disposable copy;
   - symlink other files/directories (`auth.json`, `hooks.json`, `skills`, state DBs, logs, `.tmp`, etc.) back to the
     real home so existing auth, hooks, and runtime integrations continue to work.
4. Launch `subprocess.Popen` with `env={**os.environ, "CODEX_HOME": shadow_home}`.
5. Remove the shadow directory in a `finally` block after the Codex subprocess finishes or errors.
6. Add an explicit opt-out environment variable, likely `SASE_CODEX_DISABLE_SHADOW_HOME=1`, for debugging or emergency
   compatibility.

This keeps the fix inside SASE's Codex provider rather than trying to chase Codex CLI's private config-write behavior.
It also avoids restoring `~/.codex/config.toml` after the fact, which would risk racing with user-initiated config
changes.

## Implementation Scope

- Update `src/sase/llm_provider/codex.py`.
- Add focused tests in `tests/test_llm_provider_codex.py` for:
  - Codex subprocesses receive a shadow `CODEX_HOME` by default.
  - the shadow `config.toml` is a copy, not a symlink.
  - non-config entries are symlinked when present.
  - the real `config.toml` remains untouched when the mocked Codex process mutates its shadow copy.
  - the shadow directory is cleaned after success and after a nonzero Codex result.
  - `SASE_CODEX_DISABLE_SHADOW_HOME=1` preserves the old environment behavior.
- Update `docs/llms.md` and `docs/configuration.md` to document the shadow home behavior and opt-out variable.

## Cleanup

After the code fix is in place, restore the live managed config with `chezmoi apply ~/.codex/config.toml` so the current
extra workspace block is removed from `~/.codex/config.toml`. No change to the chezmoi source is expected.

## Verification

Run:

```bash
just install
pytest tests/test_llm_provider_codex.py
just check
```

Optionally re-run a minimal Codex invocation through SASE or a targeted mocked provider test to confirm the real
`~/.codex/config.toml` does not change.
