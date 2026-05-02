---
create_time: 2026-05-02 00:08:01
status: proposed
prompt: sdd/prompts/202605/chat_update_workspace_resolution.md
---

# Fix Chat Update Workspace Resolution

## Problem

The Telegram screenshot shows `/update` replying:

`Update not started: could not resolve the primary SASE workspace.`

The Telegram plugin is already dispatching `/update` correctly. The failure is returned by
`sase.integrations.chat_install.start_chat_install_worker()` when `resolve_primary_workspace_for_chat_install()` returns
`None`.

That resolver currently delegates directly to `sase.bead.workspace.resolve_primary_workspace()`. That helper is
intentionally current-project/CWD-oriented: it infers the project from the process CWD, then returns that project's
primary workspace. This is a poor fit for chat-driven SASE self-update:

- The inbound Telegram process can run from outside any registered SASE project, causing `None`.
- If it runs from a plugin repo such as `sase-telegram`, the current-project resolver can choose the plugin workspace,
  not the core `sase` workspace that should be updated.
- The chat update workflow documentation says the command runs from the primary SASE workspace, not from whichever repo
  happens to be the bot process CWD.

## Goal

Make `/update` resolve the installed/core `sase` project workspace deterministically, independent of Telegram or Google
Chat process CWD, while preserving the existing `chat_install` config and worker lifecycle.

## Implementation Plan

1. Update `src/sase/integrations/chat_install.py` so `resolve_primary_workspace_for_chat_install()` first resolves the
   registered `sase` project file directly:
   - Read `~/.sase/projects/sase/sase.gp`.
   - Parse `WORKSPACE_DIR` with the existing `sase.workspace_provider.utils.parse_workspace_dir()` helper.
   - Return the path only when it exists and is a directory.

2. Keep a conservative fallback path:
   - If the explicit `sase` project file is missing, has no usable `WORKSPACE_DIR`, or points at a deleted directory,
     fall back to the existing `sase.bead.workspace.resolve_primary_workspace()`.
   - This preserves current behavior for unusual development setups while fixing the chat-hosted update path.

3. Add focused tests in `tests/test_chat_install.py`:
   - Resolves `~/.sase/projects/sase/sase.gp` even when CWD is outside any known workspace.
   - Prefers the registered `sase` workspace over a different CWD-derived project workspace.
   - Falls back to the existing CWD resolver when the registered `sase` project workspace is unavailable.

4. Update documentation wording where it currently says "primary workspace" without the project qualifier:
   - Clarify that chat update runs from the registered primary workspace for the `sase` project.
   - Keep `chat_install.command`, lock paths, and log paths unchanged for compatibility.

5. Validate:
   - Run `just install` in this workspace first, because this ephemeral clone may not have a current editable install.
   - Run targeted tests for `tests/test_chat_install.py`.
   - Run `just check` before replying, as required by the repo memory after modifying this repo.

## Non-Goals

- Do not change Telegram command dispatch; `/update` is already wired.
- Do not edit `sase-telegram` unless core tests reveal a plugin-side regression.
- Do not rename `chat_install` config/state keys; the previous rename plan intentionally preserved them.
- Do not add a new user-facing config key unless the direct `sase` project resolution proves insufficient.
