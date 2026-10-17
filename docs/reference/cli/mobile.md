---
title: "sase mobile"
description: "Run mobile integration helpers"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase mobile

Run mobile integration helpers

Reference for `sase mobile`. Run `sase mobile --help` for the exact output on this checkout.

```text
usage: sase mobile [-h]
                   {agent-bridge,gateway,helper-bridge,notification-bridge}
                   ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand            | Summary                                      |
| --------------------- | -------------------------------------------- |
| `sase mobile gateway` | Manage the workstation-hosted mobile gateway |

## `sase mobile gateway`

```text
usage: sase mobile gateway [-h] {pair,start} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                  | Summary                                              |
| --------------------------- | ---------------------------------------------------- |
| `sase mobile gateway pair`  | Request a pairing challenge from the running gateway |
| `sase mobile gateway start` | Start the mobile gateway in the foreground           |

### `sase mobile gateway pair`

```text
usage: sase mobile gateway pair [-h] [-b BIND_ADDRESS] [-p PORT]
```

Options:

| Option                                           | Description                                            | Default |
| ------------------------------------------------ | ------------------------------------------------------ | ------- |
| `-b BIND_ADDRESS`, `--bind-address BIND_ADDRESS` | Host address to contact (default: config or 127.0.0.1) | —       |
| `-h`, `--help`                                   | show this help message and exit                        | —       |
| `-p PORT`, `--port PORT`                         | Port to contact (default: config or 7629)              | —       |

### `sase mobile gateway start`

```text
usage: sase mobile gateway start [-h] [-b BIND_ADDRESS] [-p PORT]
                                 [-H STATE_DIR] [-L] [-c GATEWAY_COMMAND]
                                 [-T STARTUP_TIMEOUT] [-P {disabled,test,fcm}]
                                 [-F FCM_PROJECT_ID]
                                 [-S FCM_SERVICE_ACCOUNT_JSON]
                                 [-E FCM_CREDENTIAL_ENV] [-D]
                                 [-U PUSH_TIMEOUT_SECONDS]
                                 [-R PUSH_RETRY_LIMIT]
```

Options:

| Option                                                                               | Description                                                                                   | Default |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- | ------- |
| `-L`, `--allow-non-loopback`                                                         | Allow explicit LAN or tailnet binds                                                           | `false` |
| `-b BIND_ADDRESS`, `--bind-address BIND_ADDRESS`                                     | Host address to bind (default: config or 127.0.0.1)                                           | —       |
| `-c GATEWAY_COMMAND`, `--command GATEWAY_COMMAND`                                    | Gateway command override, parsed without a shell                                              | —       |
| `-E FCM_CREDENTIAL_ENV`, `--fcm-credential-env FCM_CREDENTIAL_ENV`                   | Environment variable containing an FCM bearer token or service-account JSON                   | —       |
| `-D`, `--fcm-dry-run`                                                                | Ask FCM to validate messages without delivering them                                          | `false` |
| `-F FCM_PROJECT_ID`, `--fcm-project-id FCM_PROJECT_ID`                               | Firebase project ID for FCM HTTP v1                                                           | —       |
| `-S FCM_SERVICE_ACCOUNT_JSON`, `--fcm-service-account-json FCM_SERVICE_ACCOUNT_JSON` | Path to the FCM service-account JSON file                                                     | —       |
| `-h`, `--help`                                                                       | show this help message and exit                                                               | —       |
| `-p PORT`, `--port PORT`                                                             | Port to bind (default: config or 7629)                                                        | —       |
| `-P PUSH_PROVIDER`, `--push-provider PUSH_PROVIDER`                                  | Push provider for hint delivery (disabled, test, or fcm) (choices: `disabled`, `fcm`, `test`) | —       |
| `-R PUSH_RETRY_LIMIT`, `--push-retry-limit PUSH_RETRY_LIMIT`                         | Number of retry attempts for best-effort push delivery                                        | —       |
| `-U PUSH_TIMEOUT_SECONDS`, `--push-timeout-seconds PUSH_TIMEOUT_SECONDS`             | Seconds to wait for each push provider HTTP attempt                                           | —       |
| `-T STARTUP_TIMEOUT`, `--startup-timeout STARTUP_TIMEOUT`                            | Seconds to wait for startup before exiting                                                    | —       |
| `-H STATE_DIR`, `--state-dir STATE_DIR`                                              | SASE state root for gateway storage                                                           | —       |

Related: [CLI command groups](index.md).
