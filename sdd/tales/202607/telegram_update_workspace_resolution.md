---
create_time: 2026-07-06 15:03:38
status: done
prompt: sdd/prompts/202607/telegram_update_workspace_resolution.md
---
# Fix Telegram `/update` Workspace Resolution

## Problem

Telegram `/update` now replies:

```text
Update not started: could not resolve the primary SASE workspace.
```

The Telegram plugin delegates `/update` to `sase.integrations.chat_install.start_chat_install_worker()`. That shared
launcher returns `workspace_resolution_failed` when `_resolve_primary_workspace_for_chat_install()` cannot find the
primary SASE checkout.

Current resolver behavior is too narrow:

1. It hard-codes the registered project spec location as `~/.sase/projects/sase/sase.sase` or legacy `sase.gp`.
2. It falls back to the CWD-based bead workspace resolver.

That fails when the SASE repo is registered under a canonical provider-derived project key such as `gh_sase-org__sase`,
with `PROJECT_NAME: sase`. The live project registry has that shape, so the hard-coded `sase/sase.sase` lookup misses
the real ProjectSpec. From Telegram, the process CWD is not guaranteed to be inside the SASE repo, so the fallback can
also fail. The screenshot shows exactly this failure mode.

## Desired Behavior

`/update` should resolve the primary SASE checkout from the registered logical project name `sase` regardless of whether
the ProjectSpec directory key is `sase`, `gh_sase-org__sase`, or another canonical provider key that declares
`PROJECT_NAME: sase` or an alias that resolves `sase`.

The fallback to CWD-based resolution should remain for older installations and partial project registries.

## Implementation Plan

1. Update `src/sase/integrations/chat_install.py`.
   - Resolve the logical project ref `sase` through `sase.project_aliases.resolve_project_alias_ref("sase")`.
   - Use the returned canonical project key to find the preferred ProjectSpec path.
   - Parse `WORKSPACE_DIR` from that ProjectSpec and return it if it exists.
   - Preserve current behavior when alias resolution or ProjectSpec parsing fails by returning `None` from the
     registered lookup and letting `_resolve_primary_workspace_for_chat_install()` call the existing fallback.

2. Keep the resolver conservative.
   - Do not create or mutate project files.
   - Do not special-case Telegram in the plugin.
   - Do not change `chat_install.command`, lock paths, worker lifecycle, completion delivery, or update messages.

3. Add focused tests in `tests/test_chat_install.py`.
   - Add a regression test where the ProjectSpec lives under a provider-derived key like `gh_sase-org__sase` but
     contains `PROJECT_NAME: sase`; the resolver should return that workspace outside any workspace CWD and should not
     call the CWD fallback.
   - Keep existing tests for direct `sase` registration, precedence over CWD, and fallback when the registered workspace
     is unavailable.
   - If needed, adjust the test helper so it can write `PROJECT_NAME` metadata before `WORKSPACE_DIR`.

4. Verify.
   - Run `just install` first because numbered SASE workspaces are ephemeral.
   - Run the targeted `tests/test_chat_install.py` test file.
   - Run `just check` before finishing because code files in the SASE repo changed.

## Expected Outcome

Telegram `/update` should start the shared update worker again on installations where the SASE project is stored under a
provider-derived canonical key but exposed as logical project name `sase`.
