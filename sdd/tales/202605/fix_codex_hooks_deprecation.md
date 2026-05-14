---
create_time: 2026-05-13 23:01:14
status: done
---
# Plan: Remove Deprecated Codex Hook Feature Flag

## Problem

Codex CLI 0.130.0 now warns:

```text
`[features].codex_hooks` is deprecated. Use `[features].hooks` instead.
```

The warning is explained by the current managed and live Codex configs:

- `~/.local/share/chezmoi/home/dot_codex/config.toml`
- `~/.codex/config.toml`

Both already contain the current flag:

```toml
[features]
hooks = true
```

but they also still contain the deprecated compatibility flag:

```toml
codex_hooks = true
```

The prior implementation intentionally kept both because Codex hook docs still referenced `codex_hooks`. Current local
CLI behavior is more authoritative for the user-visible warning: `hooks = true` is accepted and `codex_hooks = true`
causes noise.

## Goals

1. Stop the Codex deprecation warning for normal Codex and SASE-launched Codex sessions.
2. Preserve native hook enablement with `[features].hooks = true`.
3. Preserve the existing SASE hook commands in `hooks.json`.
4. Keep SASE shadow `CODEX_HOME` behavior unchanged: SASE should still copy the real `config.toml` into the temporary
   Codex home.
5. Add regressions so the deprecated key does not come back silently.

## Non-Goals

- Do not change the hook command implementation or sibling-stop fallback logic.
- Do not update historical SDD tale files; they record previous plans and findings.
- Do not modify `memory/` files without explicit user approval. `memory/long/llm_provider_hooks/codex.md` still
  documents the older flag, but AGENTS.md says memory files require approval before edits.

## Implementation Steps

1. Update the chezmoi-managed Codex config source:

   ```text
   ~/.local/share/chezmoi/home/dot_codex/config.toml
   ```

   Remove only:

   ```toml
   codex_hooks = true
   ```

   Keep:

   ```toml
   [features]
   hooks = true
   ```

2. Update the chezmoi Codex config regression test:

   ```text
   ~/.local/share/chezmoi/tests/bash/codex_config_test.sh
   ```

   Keep assertions that:
   - `[features]` exists;
   - `hooks = true` exists in the features table;
   - `home/dot_codex/hooks.json` contains `sase_commit_stop_hook`;
   - `home/dot_codex/hooks.json` contains `sase_sibling_commit_stop_hook`.

   Add an assertion that the features table does not contain:

   ```text
   codex_hooks =
   ```

3. Apply the managed config to the live home:

   ```bash
   chezmoi apply --force
   ```

   Then verify `~/.codex/config.toml` also has `hooks = true` and no `codex_hooks`.

4. Update SASE's shadow-home regression fixture:

   ```text
   tests/test_llm_provider_codex_shadow_home.py
   ```

   Change the sample `config_text` from the old dual-flag form to:

   ```toml
   model = "gpt-5.5"

   [features]
   hooks = true
   ```

   Optionally add a focused assertion in that same test that the copied shadow config does not contain `codex_hooks`.
   This keeps the test aligned with the desired runtime config while still testing only copy/isolation behavior.

5. Do not touch `src/sase/llm_provider/codex.py` unless tests reveal that the provider is injecting or rewriting feature
   flags. Current inspection shows it copies config through the shadow home path; it does not generate `codex_hooks`.

## Verification

Run in `~/.local/share/chezmoi`:

```bash
just check
```

Run in this SASE workspace:

```bash
just install
pytest tests/test_llm_provider_codex_shadow_home.py
just check
```

Also run targeted config checks:

```bash
awk '/^\[features\]$/ { in_features = 1; next } /^\[/ && in_features { exit } in_features { print }' \
  ~/.local/share/chezmoi/home/dot_codex/config.toml

awk '/^\[features\]$/ { in_features = 1; next } /^\[/ && in_features { exit } in_features { print }' \
  ~/.codex/config.toml
```

Expected output from each features table includes `hooks = true` and does not include `codex_hooks`.

Finally, start a small Codex smoke command from this repo and confirm the deprecation warning is absent. This smoke
should not require changing any real sibling repos; it only verifies config parsing noise is gone.

## Risks

- OpenAI's public hooks documentation still shows `codex_hooks = true` in places, while the installed CLI warns to use
  `hooks = true`. The plan follows the installed CLI because it is the component emitting the warning and because
  `hooks = true` is already present in the config.
- Older Codex CLI versions might have required `codex_hooks`. If that compatibility is still needed, the warning cannot
  be eliminated without accepting version-specific config. Given the user-visible problem is current Codex CLI 0.130.0,
  the clean fix is to remove the deprecated key.
