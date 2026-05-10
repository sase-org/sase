---
create_time: 2026-05-01 17:00:38
status: done
prompt: sdd/prompts/202605/rename_chat_install_to_update.md
---
# Rename Chat Install Commands to Update

## Goal

Rename the user-facing chat command that runs the SASE install/update worker:

- Telegram: `/install` becomes `/update`
- Google Chat: `.install` becomes `.update`

The command behavior remains the same: start the detached shared worker, stop axe, sync the primary SASE workspace, run
the configured `chat_install.command`, and restart axe. The change should read as an update workflow in chat while
preserving the existing shared `chat_install` configuration contract unless there is a stronger reason to introduce a
separate config migration.

## Current Shape

The implementation spans three repositories:

- `sase_101`
  - Owns the shared worker in `src/sase/integrations/chat_install.py`.
  - Owns shared docs for the `chat_install` config and integration helper.
  - Current shared launch message says `Install worker started; log: ...`.
- `../sase-telegram`
  - Parses slash commands in `src/sase_telegram/scripts/sase_tg_inbound.py`.
  - Dispatches `command == "install"` to `_handle_install_command()`.
  - Registers `("install", "Update SASE and restart axe")` in `_SLASH_COMMANDS`.
  - Caches command registration in `~/.sase/telegram/commands_registered_ts`, so a pure `_SLASH_COMMANDS` edit can leave
    stale Telegram command menu entries visible for up to one hour.
  - Tests and docs explicitly cover `/install`.
- `../retired chat plugin`
  - Parses dot commands in `src/retired_chat_plugin/inbound.py`.
  - `_DOT_COMMANDS` contains `install`; `process_dot_command(".install")` returns `DotCommand("install", [])`.
  - Dispatches `cmd.command == "install"` in `src/retired_chat_plugin/scripts/sase_gc_inbound.py`.
  - Help, tests, README, and inbound docs explicitly cover `.install`.

## Product Decisions

1. Treat this as a hard rename, not an alias.
   - `/install` and `.install` should stop being advertised and stop dispatching.
   - This matches "change the name" rather than "add an alternate name".
   - Tests should assert the old spellings are unsupported where practical.

2. Keep the underlying shared config key as `chat_install`.
   - `chat_install.command` is already documented, configured, and shipped.
   - Renaming config and state paths would create migration work unrelated to the visible command name.
   - Docs can describe it as the update workflow while noting that the existing config key remains `chat_install`.

3. Rename chat-visible acknowledgement text to "Update" where users see it.
   - Missing config, missing workspace, already-running, and launched messages should say "Update ..." rather than
     "Install ...".
   - Internal module names, log paths, locks, and dataclass names can remain `chat_install` unless later product work
     explicitly wants a compatibility migration.

4. Fix Telegram command registration invalidation as part of the rename.
   - Relying on the existing timestamp-only cache is fragile for command changes.
   - Store a small fingerprint of `_SLASH_COMMANDS` next to the timestamp, or replace the timestamp file contents with a
     versioned JSON payload that includes both timestamp and fingerprint.
   - Existing timestamp-only files should still parse gracefully and should force a registration if the payload is not
     the new format.

## Implementation Plan

### Phase 1: Shared SASE Worker Wording

In `sase_101`:

- Update only user-facing result messages in `src/sase/integrations/chat_install.py`:
  - `chat_install.command is not configured; update was not started.`
  - `Could not resolve the primary SASE workspace; update was not started.`
  - `A chat update worker is already running.`
  - `Update worker started; log: ...`
  - `Failed to launch chat update worker: ...`
- Keep:
  - module path `sase.integrations.chat_install`
  - config section `chat_install`
  - state dir `~/.sase/chat_install`
  - lock/log filenames
  - function/type names
- Update `tests/test_chat_install.py` expected launched message and any explicit install/start wording if asserted.
- Update `docs/configuration.md`, `docs/integrations.md`, and relevant current docs to describe "install/update" as
  "update" from the chat-user point of view while preserving `chat_install.command` references.

### Phase 2: Telegram Slash Command Rename

In `../sase-telegram`:

- Rename the dispatch branch from `command == "install"` to `command == "update"`.
- Rename `_handle_install_command()` to `_handle_update_command()` if the local surface stays readable; keep a small
  private helper only if test churn or readability argues for it.
- Rename `_format_install_ack()` to `_format_update_ack()` and update chat-visible strings:
  - `Update not started: chat_install.command is not configured.`
  - `Update not started: could not resolve the primary SASE workspace.`
  - `Update already running.`
  - launched path comes from the shared result and should already say `Update worker started; log: ...`.
- Change `_SLASH_COMMANDS` from `("install", ...)` to `("update", "Update SASE and restart axe")`.
- Replace timestamp-only command registration caching with timestamp plus command fingerprint:
  - Add a helper that deterministically hashes/serializes `_SLASH_COMMANDS`.
  - Re-register if the cache is absent, invalid, too old, or has a different fingerprint.
  - After successful registration, write the new payload.
  - This avoids requiring a manual `rm ~/.sase/telegram/commands_registered_ts` after the rename.
- Update tests:
  - `/update` dispatches to the update handler.
  - `/install` is no longer handled.
  - `_SLASH_COMMANDS` contains `update` and not `install`.
  - A new cache/fingerprint test proves command-list changes force registration before the hourly interval expires.
  - Existing acknowledgement tests expect "Update ..." wording.
- Update README and `docs/inbound.md` from `/install` to `/update`, including deployment notes that no manual cache
  deletion is needed after this change because command registration now fingerprints the command list.

### Phase 3: Google Chat Dot Command Rename

In `../retired chat plugin`:

- Change `_DOT_COMMANDS` from `install` to `update`.
- Update `process_dot_command()` docs and tests:
  - `.update` returns `DotCommand("update", [])`.
  - `.install` returns `None`.
- Rename the dispatch branch in `_handle_dot_command()` from `cmd.command == "install"` to `cmd.command == "update"`.
- Rename local helpers from install to update where helpful for readability:
  - `_format_install_ack()` -> `_format_update_ack()`.
- Update `_HELP_TEXT`, README, `docs/inbound.md`, and `docs/architecture.md` references from `.install` to `.update`.
- Update tests:
  - Help lists `.update` and not `.install`.
  - Dispatching `DotCommand("update", [])` starts `start_chat_install_worker()`.
  - Missing config acknowledgement uses "Update ..." wording.
  - Existing integration-ish dot-command cases use `.update`.

### Phase 4: Cross-Repo Search and Validation

- Run targeted searches in all three repos:
  - `rg -n '(/install|\\.install|command == "install"|DotCommand\\("install"|Install worker|Install not started|Install already running)'`
  - Keep historical plans/specs unchanged unless they are current user-facing docs; do not churn old research artifacts.
- Run checks:
  - In `sase_101`: `just install` then targeted `pytest tests/test_chat_install.py`, then `just check` because this repo
    requires it after file changes.
  - In `../sase-telegram`: `just install`, targeted inbound tests, then `just check`.
  - In `../retired chat plugin`: `just install`, targeted inbound tests, then `just check`.

## Risks and Notes

- Telegram allows command names without the leading `/` in `set_my_commands`; `_SLASH_COMMANDS` must use `update`, not
  `/update`.
- Google Chat has no slash-command registration in this integration, so the corresponding command is `.update`, not
  `/update`.
- Keeping `chat_install.command` while renaming visible commands is slightly asymmetric, but avoids breaking existing
  config. The docs should make this explicit enough that the config key does not look stale.
- If preserving `/install` or `.install` as temporary aliases is desired, that should be an explicit product decision;
  the proposed implementation intentionally removes them from dispatch and tests.
