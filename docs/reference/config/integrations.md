---
title: Integrations and telemetry configuration
description: Chat, mobile access, and local telemetry settings.
covers: config
---

<!-- generated, do not edit; source: src/sase/config/sase.schema.json and src/sase/default_config.yml (tools/render_config; run just fix to regenerate) -->

# Integrations and telemetry configuration

Chat, mobile access, and local telemetry settings.

Defaults come from the schema when declared, otherwise from the bundled YAML. An object
with listed children is expanded below; `{…}` and `[…]` summarize compound defaults. A
dash means the schema has no finite allowed-value list.

## `chat_install`

| Config key                                                                | Type    | Default                                                | Allowed values | Description                                                                                                                     |
| ------------------------------------------------------------------------- | ------- | ------------------------------------------------------ | -------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| <a id="chat_install"></a>`chat_install`                                   | object  | {`timeout_seconds`, `restart_attempts`} (values below) | —              | Configuration for chat-driven update workflows                                                                                  |
| <a id="chat_install-timeout_seconds"></a>`chat_install.timeout_seconds`   | integer | `900`                                                  | —              | Maximum runtime for `sase update --json` before returning exit code 124.                                                        |
| <a id="chat_install-restart_attempts"></a>`chat_install.restart_attempts` | integer | `3`                                                    | —              | Number of scheduler readiness polls after requesting its service proc start when the scheduler is not running after the update. |

## `feature_flags`

| Config key                                                                                          | Type    | Default | Allowed values | Description                                                                                                   |
| --------------------------------------------------------------------------------------------------- | ------- | ------- | -------------- | ------------------------------------------------------------------------------------------------------------- |
| <a id="feature_flags"></a>`feature_flags`                                                           | object  | not set | —              | Code-owned SASE feature flags keyed by flag name.                                                             |
| <a id="feature_flags-artifacts_agent_pane_retired"></a>`feature_flags.artifacts_agent_pane_retired` | boolean | `true`  | —              | Artifacts has no Agent sub-tab: Stitch becomes digit 1 and agent history lives in the Agents tab Archive.     |
| <a id="feature_flags-claude_explicit_instructions"></a>`feature_flags.claude_explicit_instructions` | boolean | `true`  | —              | Deliver Claude root and helper instruction bundles through explicit system-prompt files.                      |
| <a id="feature_flags-codex_explicit_instructions"></a>`feature_flags.codex_explicit_instructions`   | boolean | `true`  | —              | Deliver the Codex root bundle through developer_instructions and suppress SASE native instruction duplicates. |
| <a id="feature_flags-grok_explicit_instructions"></a>`feature_flags.grok_explicit_instructions`     | boolean | `true`  | —              | Deliver Grok instruction bundles through --rules                                                              |
| <a id="feature_flags-muse_explicit_instructions"></a>`feature_flags.muse_explicit_instructions`     | boolean | `true`  | —              | Deliver Muse instruction bundles as a prompt prefix                                                           |
| <a id="feature_flags-key"></a>`feature_flags.<key>`                                                 | boolean | not set | —              | —                                                                                                             |

## `mobile_gateway`

| Config key                                                                                    | Type    | Default                     | Allowed values                  | Description                                                                                      |
| --------------------------------------------------------------------------------------------- | ------- | --------------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------ |
| <a id="mobile_gateway"></a>`mobile_gateway`                                                   | object  | {…} (13 keys; values below) | —                               | Configuration for the workstation-hosted mobile gateway                                          |
| <a id="mobile_gateway-bind_address"></a>`mobile_gateway.bind_address`                         | string  | `"127.0.0.1"`               | —                               | Host address to bind the mobile gateway.                                                         |
| <a id="mobile_gateway-port"></a>`mobile_gateway.port`                                         | integer | `7629`                      | —                               | TCP port for the mobile gateway HTTP API.                                                        |
| <a id="mobile_gateway-state_dir"></a>`mobile_gateway.state_dir`                               | string  | `""`                        | —                               | State directory passed to the gateway as the SASE home. Empty string uses the runtime default.   |
| <a id="mobile_gateway-allow_non_loopback"></a>`mobile_gateway.allow_non_loopback`             | boolean | `false`                     | —                               | Allow explicit non-loopback gateway binds.                                                       |
| <a id="mobile_gateway-command"></a>`mobile_gateway.command`                                   | string  | `""`                        | —                               | Gateway command override, parsed without a shell. Empty string uses PATH/sibling-repo discovery. |
| <a id="mobile_gateway-agent_bridge_command"></a>`mobile_gateway.agent_bridge_command`         | string  | `""`                        | —                               | Agent bridge command override passed through to the gateway.                                     |
| <a id="mobile_gateway-helper_bridge_command"></a>`mobile_gateway.helper_bridge_command`       | string  | `""`                        | —                               | Helper bridge command override passed through to the gateway.                                    |
| <a id="mobile_gateway-push_provider"></a>`mobile_gateway.push_provider`                       | string  | `"disabled"`                | `"disabled"`, `"test"`, `"fcm"` | Push notification provider for mobile clients.                                                   |
| <a id="mobile_gateway-fcm_project_id"></a>`mobile_gateway.fcm_project_id`                     | string  | `""`                        | —                               | Firebase Cloud Messaging project ID.                                                             |
| <a id="mobile_gateway-fcm_service_account_json"></a>`mobile_gateway.fcm_service_account_json` | string  | `""`                        | —                               | Path to a Firebase service account JSON file. Empty string disables file credentials.            |
| <a id="mobile_gateway-fcm_credential_env"></a>`mobile_gateway.fcm_credential_env`             | string  | `""`                        | —                               | Environment variable containing Firebase credentials JSON.                                       |
| <a id="mobile_gateway-fcm_dry_run"></a>`mobile_gateway.fcm_dry_run`                           | boolean | `false`                     | —                               | Send FCM notifications in dry-run mode.                                                          |
| <a id="mobile_gateway-push_timeout_seconds"></a>`mobile_gateway.push_timeout_seconds`         | number  | `5`                         | —                               | Seconds to wait for each push notification request.                                              |
| <a id="mobile_gateway-push_retry_limit"></a>`mobile_gateway.push_retry_limit`                 | integer | `1`                         | —                               | Number of push notification retry attempts.                                                      |
| <a id="mobile_gateway-startup_timeout_seconds"></a>`mobile_gateway.startup_timeout_seconds`   | number  | `10`                        | —                               | Seconds to wait for the gateway to become ready.                                                 |

## `telegram`

| Config key                                                                          | Type   | Default                     | Allowed values       | Description                                                                 |
| ----------------------------------------------------------------------------------- | ------ | --------------------------- | -------------------- | --------------------------------------------------------------------------- |
| <a id="telegram"></a>`telegram`                                                     | object | {`commands`} (values below) | —                    | Configuration for the SASE Telegram integration.                            |
| <a id="telegram-commands"></a>`telegram.commands`                                   | object | `{}`                        | —                    | Custom Telegram slash commands keyed by their bot-command name.             |
| <a id="telegram-commands-key"></a>`telegram.commands.<key>`                         | object | not set                     | —                    | The executable and delivery settings for one custom Telegram slash command. |
| <a id="telegram-commands-key-description"></a>`telegram.commands.<key>.description` | string | not set                     | —                    | Description shown for the command in Telegram's slash-command menu.         |
| <a id="telegram-commands-key-run"></a>`telegram.commands.<key>.run`                 | string | not set                     | —                    | Executable and fixed arguments to run without a shell.                      |
| <a id="telegram-commands-key-output"></a>`telegram.commands.<key>.output`           | string | `"message"`                 | `"message"`, `"pdf"` | How the command's Markdown stdout is delivered to Telegram.                 |
| <a id="telegram-commands-key-timeout"></a>`telegram.commands.<key>.timeout`         | string | `"60s"`                     | —                    | Maximum command runtime as a duration ending in seconds, minutes, or hours. |

## `telemetry`

| Config key                                                                                                      | Type    | Default                                                                                | Allowed values | Description                                                           |
| --------------------------------------------------------------------------------------------------------------- | ------- | -------------------------------------------------------------------------------------- | -------------- | --------------------------------------------------------------------- |
| <a id="telemetry"></a>`telemetry`                                                                               | object  | {`enabled`, `flush_interval_seconds`, `retention`, `health_thresholds`} (values below) | —              | Local telemetry settings                                              |
| <a id="telemetry-enabled"></a>`telemetry.enabled`                                                               | boolean | `true`                                                                                 | —              | Whether telemetry collection is enabled                               |
| <a id="telemetry-flush_interval_seconds"></a>`telemetry.flush_interval_seconds`                                 | number  | `15`                                                                                   | —              | Seconds between local telemetry store flushes in long-lived processes |
| <a id="telemetry-retention"></a>`telemetry.retention`                                                           | object  | {`raw_seconds`, `rollup_5m_seconds`, `rollup_1h_seconds`} (values below)               | —              | Retention windows for raw and rolled-up metric samples                |
| <a id="telemetry-retention-raw_seconds"></a>`telemetry.retention.raw_seconds`                                   | integer | `172800`                                                                               | —              | Seconds to retain raw metric samples                                  |
| <a id="telemetry-retention-rollup_5m_seconds"></a>`telemetry.retention.rollup_5m_seconds`                       | integer | `2592000`                                                                              | —              | Seconds to retain five-minute metric rollups                          |
| <a id="telemetry-retention-rollup_1h_seconds"></a>`telemetry.retention.rollup_1h_seconds`                       | integer | `31536000`                                                                             | —              | Seconds to retain hourly metric rollups                               |
| <a id="telemetry-prometheus"></a>`telemetry.prometheus`                                                         | object  | not set                                                                                | —              | Deprecated legacy settings accepted for compatibility and ignored     |
| <a id="telemetry-prometheus-exposition_port"></a>`telemetry.prometheus.exposition_port`                         | integer | `9464`                                                                                 | —              | Port for the Prometheus metrics exposition endpoint                   |
| <a id="telemetry-prometheus-pushgateway_url"></a>`telemetry.prometheus.pushgateway_url`                         | string  | `"localhost:9091"`                                                                     | —              | URL of the Prometheus Pushgateway                                     |
| <a id="telemetry-prometheus-url"></a>`telemetry.prometheus.url`                                                 | string  | `"localhost:9090"`                                                                     | —              | URL of the Prometheus server                                          |
| <a id="telemetry-health_thresholds"></a>`telemetry.health_thresholds`                                           | object  | {…} (6 keys; values below)                                                             | —              | Thresholds for the telemetry health traffic-light check               |
| <a id="telemetry-health_thresholds-error_rate_warn"></a>`telemetry.health_thresholds.error_rate_warn`           | number  | `10.0`                                                                                 | —              | Error rate percentage to trigger a warning                            |
| <a id="telemetry-health_thresholds-error_rate_critical"></a>`telemetry.health_thresholds.error_rate_critical`   | number  | `25.0`                                                                                 | —              | Error rate percentage to trigger a critical alert                     |
| <a id="telemetry-health_thresholds-retry_rate_warn"></a>`telemetry.health_thresholds.retry_rate_warn`           | number  | `10.0`                                                                                 | —              | Retry rate percentage to trigger a warning                            |
| <a id="telemetry-health_thresholds-retry_rate_critical"></a>`telemetry.health_thresholds.retry_rate_critical`   | number  | `25.0`                                                                                 | —              | Retry rate percentage to trigger a critical alert                     |
| <a id="telemetry-health_thresholds-p95_latency_warn"></a>`telemetry.health_thresholds.p95_latency_warn`         | number  | `300.0`                                                                                | —              | P95 latency in seconds to trigger a warning                           |
| <a id="telemetry-health_thresholds-p95_latency_critical"></a>`telemetry.health_thresholds.p95_latency_critical` | number  | `600.0`                                                                                | —              | P95 latency in seconds to trigger a critical alert                    |

## Related

- [Configuration reference](index.md) — all key families.
