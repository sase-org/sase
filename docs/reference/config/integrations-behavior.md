---
title: "Integration configuration behavior"
description: "Configuration behavior for chat and mobile integrations."
---

# Integration configuration behavior

Configuration behavior for chat and mobile integrations.

<a id="chatinstall"></a>

## chat_install

Configuration for chat-driven update workflows. External chat integrations can call
`sase.integrations.chat_install.start_chat_install_worker()` to run the built-in
`sase update --json` engine in a detached worker. The worker uses the same
managed-vs-dev routing as the TUI Updates tab and the `sase update` CLI, so no custom
update command is required.

```yaml
chat_install:
  timeout_seconds: 900
  restart_attempts: 3
```

[Generated reference for `chat_install`](integrations.md#chat_install)

Only one chat update worker may run at a time; a lock under
`~/.sase/chat_install/install.lock` rejects concurrent starts. Worker output is written
to timestamped logs under `~/.sase/chat_install/logs/`. The configuration key and state
paths remain named `chat_install` for compatibility. The old `chat_install.command` and
`chat_install.sync_workspace` keys have been removed; delete them from user config if
schema validation reports them. See
[`docs/integrations.md`](../../integrations.md#chat-update-worker) for the
integration-facing Python API.

Source: `src/sase/default_config.yml`, `src/sase/integrations/chat_install.py`

## telegram

Custom Telegram slash commands are keyed by the bot command name. Define them in user
configuration or an overlay; the Telegram integration deliberately ignores project-local
configuration so a repository cannot add commands to your bot. Core SASE validates the
definitions, and `sase doctor` checks that each command's executable resolves.

```yaml
telegram:
  commands:
    projects:
      description: List enabled SASE projects.
      run: sase project list --state enabled
      output: message
      timeout: 60s
```

[Generated reference for `telegram`](integrations.md#telegram)

Command names must contain 1–32 lowercase letters, digits, or underscores. The built-in
names `bead`, `beads`, `changes`, `fork`, `kill`, `list`, `update`, and `macros` are
reserved. The integration parses `run` as an argument vector and never invokes a shell.
Text following `/name` is appended as one final argument, and the process runs from an
isolated temporary directory, so use absolute paths or commands available on `PATH`
rather than relying on a project working directory.

Run `sase doctor -C integrations.telegram_commands` after editing the map; unresolved
command heads produce a warning with the affected names.

Source: `src/sase/default_config.yml`, `src/sase/doctor/checks_integrations.py`

<a id="mobilegateway"></a>

## mobile_gateway

Configuration for `sase mobile gateway start`, which launches the workstation-hosted
Rust gateway for paired mobile clients.

```yaml
mobile_gateway:
  bind_address: "127.0.0.1"
  port: 7629
  state_dir: ""
  allow_non_loopback: false
  command: ""
  agent_bridge_command: ""
  helper_bridge_command: ""
  push_provider: "disabled"
  fcm_project_id: ""
  fcm_service_account_json: ""
  fcm_credential_env: ""
  fcm_dry_run: false
  push_timeout_seconds: 5
  push_retry_limit: 1
  startup_timeout_seconds: 10
```

[Generated reference for `mobile_gateway`](integrations.md#mobile_gateway)

Push payloads are hint-only and must not contain bearer tokens, pairing codes, prompt
bodies, response text, attachment contents, attachment tokens, or host paths. Only
credential paths or environment-variable names are placed on the gateway command line.
See [`docs/mobile_gateway.md`](../../mobile_gateway.md#push-hints) for setup examples
and security notes.

Source: `src/sase/default_config.yml`, `src/sase/integrations/mobile_gateway.py`

## Related

- [Integrations and telemetry configuration](integrations.md) — generated keys and
  defaults.
- [Integrations](../../integrations.md) — integration APIs.
