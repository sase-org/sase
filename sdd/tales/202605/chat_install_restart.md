---
create_time: 2026-05-01 15:47:48
status: done
prompt: sdd/prompts/202605/chat_install_restart.md
---
# Chat Install / Restart Command Plan

## Goal

Add a remote chat command for both Telegram and Google Chat that performs the local "install/update SASE" workflow
safely:

1. User runs `/install` in Telegram or `.install` in Google Chat.
2. The chat handler starts a detached worker process and immediately replies with a short acknowledgement and log path.
3. The detached worker stops axe.
4. From the root of the primary SASE workspace, it syncs the workspace.
5. If sync succeeds, it runs a user-configured shell command from that same workspace root.
6. It attempts to start axe again in a `finally` path, even if workspace resolution, sync, or the install command
   failed.

The restart path is the highest-priority invariant. The chat inbound chop runs under axe, so stopping axe directly
inside the inbound handler is unsafe: the orchestrator may terminate the lumberjack/chop process before the handler gets
to the install or restart step. The handler should only launch a detached worker with `start_new_session=True`; the
worker owns the stop/sync/install/start sequence.

## Proposed User Configuration

Add a core merged-config section with conservative defaults:

```yaml
chat_install:
  command: ""
  sync_workspace: true
  timeout_seconds: 900
  restart_attempts: 3
```

Machine-specific overlays then set the command:

```yaml
chat_install:
  command: "install_sase_github"
```

For the work overlay, use the exact command the user wants configured. The prompt says `install_sase_gopgle`; verify
whether that spelling is intentional before editing the work config, because it looks like it may be a typo for
`install_retired_mercurial_plugin`.

The command is a trusted local user-configured shell string, executed with `shell=True`, `cwd=<primary_sase_workspace>`,
captured stdout/stderr, and a timeout. Empty/missing command should fail before stopping axe and should be reported to
chat.

## Core Implementation

Create a shared core helper module, likely `src/sase/integrations/chat_install.py`, so Telegram and Google Chat do not
duplicate lifecycle behavior.

Core responsibilities:

- `load_chat_install_config()` reads `chat_install` from `load_merged_config()` and returns a typed dataclass.
- `resolve_primary_workspace_for_chat_install()` resolves the primary workspace using the existing
  `sase.bead.workspace.resolve_primary_workspace()` helper.
- `start_chat_install_worker()` acquires a non-blocking lock under `~/.sase/chat_install/install.lock`, resolves the
  workspace, and launches a detached worker process with:
  - `sys.executable -m sase.integrations.chat_install --workspace <path>`
  - `cwd=<primary workspace>`
  - `start_new_session=True`
  - stdout/stderr redirected to a timestamped log in `~/.sase/chat_install/logs/`
- The worker `main()` performs the actual sequence and writes structured, human-readable log lines.

Worker algorithm:

```text
load config
validate command
resolve/use primary workspace
try:
  stop_axe_daemon()
  if sync_workspace:
    provider = get_vcs_provider(workspace)
    success, error = provider.sync_workspace(workspace)
    if not success:
      log failure and skip install command
      return failure
  run configured command from workspace root
  return command status
finally:
  attempt start_axe_daemon() up to restart_attempts
  verify is_axe_running()
  log explicit restart success/failure
  release lock
```

Restart should be attempted even if `stop_axe_daemon()` reports axe was not running, because the command's intended
postcondition is "axe is running".

If sync fails, skip the install command rather than installing from a stale or conflicted tree. The chat/log message
should say sync failed and axe restart was still attempted.

## Telegram Changes

In `sase-telegram`:

- Add `/install` to `_SLASH_COMMANDS`.
- Extend `_handle_command()` to dispatch `install`.
- Add `_handle_install_command()` that calls the shared core launcher and sends one acknowledgement message to the
  configured chat ID.
- The acknowledgement should distinguish:
  - config missing command
  - primary workspace resolution failed
  - worker already running
  - worker launched, with log path
- Update README and `docs/inbound.md`.
- Tests:
  - `/install` dispatches to `_handle_install_command()`.
  - `_SLASH_COMMANDS` includes `install`.
  - handler reports each launcher outcome and does not run the install inline.

## Google Chat Changes

In `retired chat plugin`:

- Add `install` to `_DOT_COMMANDS`.
- Add `.install` to `_HELP_TEXT`, README, and `docs/inbound.md`.
- Extend `_handle_dot_command()` to call shared core launcher and post the acknowledgement into the source thread.
- Tests:
  - `process_dot_command(".install") == DotCommand("install", [])`.
  - help includes `.install`.
  - dispatch calls the shared launcher and posts the result to Google Chat.

## Config / Dotfiles

After code is in place, update chezmoi-managed SASE config overlays rather than editing only `~/.config/sase`:

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`
  - set `chat_install.command: "install_sase_github"`
- `~/.local/share/chezmoi/home/dot_config/sase/sase_work.yml`
  - set the work command, after confirming the spelling of `install_sase_gopgle` vs `install_retired_mercurial_plugin`

Then run `chezmoi apply --force` so the live config is updated.

## Validation

Run checks in every modified repo:

- Core repo (`sase_100`): `just install`, targeted tests for the new core helper, then `just check`.
- `sase-telegram`: `just install`, targeted inbound tests, then `just check`.
- `retired chat plugin`: `just install`, targeted inbound tests, then `just check`.
- Chezmoi repo if edited: `just check`, then `chezmoi apply --force`.

Manual dry-run validation can use a temporary config override such as:

```yaml
chat_install:
  command: "pwd && true"
```

Then trigger `/install` or `.install`, confirm the detached log shows the primary workspace root,
stop/sync/command/start ordering, and a successful axe restart.

## Open Decision

The only thing to confirm before implementation is the work-machine command spelling. The user wrote
`install_sase_gopgle`; if that is literal, configure it as written. If it is a typo, use `install_retired_mercurial_plugin`.
