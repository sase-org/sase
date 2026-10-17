---
title: "sase machine"
description: "Manage viewer-local aliases for enrolled remote machines."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase machine

Manage enrolled remote machines

Reference for `sase machine`. Run `sase machine --help` for the exact output on this checkout.

```text
usage: sase machine [-h]
                    {add,agent,attention,bootstrap,discover,init,list,remove,rename,repair,show,status}
                    ...
```

Manage viewer-local aliases for enrolled remote machines. With no subcommand, delegates to `sase machine list`.

Bare `sase machine` defaults to `sase machine list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand               | Summary                                                |
| ------------------------ | ------------------------------------------------------ |
| `sase machine add`       | Enroll a remote machine alias                          |
| `sase machine agent`     | Stop, retry, or fork a remote agent on its owning host |
| `sase machine attention` | Answer a remote question or approve a remote gate      |
| `sase machine bootstrap` | Issue a target-local one-time enrollment bundle        |
| `sase machine discover`  | Run explicit provider discovery                        |
| `sase machine init`      | Discover, enroll, and activate remote machines         |
| `sase machine list`      | List configured machine aliases without network IO     |
| `sase machine remove`    | Remove a configured machine alias                      |
| `sase machine rename`    | Rename a viewer-local machine alias                    |
| `sase machine repair`    | Repair a quarantined or mismatched enrollment          |
| `sase machine show`      | Show one configured machine alias without network IO   |
| `sase machine status`    | Run an authenticated hello check                       |

## `sase machine add`

```text
usage: sase machine add [-h] [-B PATH] [-c REF] [-j] [-p PROVIDER] [-S TARGET]
                        [-t SECONDS]
                        ALIAS [ENDPOINT]
```

Enroll ALIAS against ENDPOINT using a pasted enrollment bundle, then deploy, reload, and require an authenticated hello. Canonical `sase machine init` is the guided path; this command is the direct add. The bundle is read from --bootstrap-file or an interactive prompt; no secret value is accepted as a command-line option.

Options:

| Option                               | Description                                                    | Default         |
| ------------------------------------ | -------------------------------------------------------------- | --------------- |
| `-B PATH`, `--bootstrap-file PATH`   | Read the enrollment bundle from PATH instead of prompting      | —               |
| `-c REF`, `--candidate REF`          | Use a discovered candidate key formatted as PROVIDER\|ENDPOINT | —               |
| `-h`, `--help`                       | show this help message and exit                                | —               |
| `-j`, `--json`                       | Emit a schema-versioned JSON result                            | `false`         |
| `-p PROVIDER`, `--provider PROVIDER` | Dispatch provider ref to store with the alias                  | `builtin@https` |
| `-S TARGET`, `--ssh-target TARGET`   | SSH destination used for terminal handoffs; defaults to ALIAS  | ``              |
| `-t SECONDS`, `--timeout SECONDS`    | Per-request gateway timeout in seconds                         | —               |

Arguments:

| Argument   | Description                  |
| ---------- | ---------------------------- |
| `alias`    | Viewer-local alias           |
| `endpoint` | HTTPS fleet gateway endpoint |

## `sase machine agent`

```text
usage: sase machine agent [-h] {fork,retry,stop} ...
```

Submit a journaled lifecycle mutation for a remote agent. ALIAS is the enrolled machine; AGENT identifies the exact remote row. sase's TUI supplies locator, revision, and operation key through the durable request sidecar.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                 | Summary                                  |
| -------------------------- | ---------------------------------------- |
| `sase machine agent fork`  | Fork a remote agent on its owning host   |
| `sase machine agent retry` | Retry remote agents on their owning host |
| `sase machine agent stop`  | Stop remote agents on their owning host  |

### `sase machine agent fork`

```text
usage: sase machine agent fork [-h] [-j] [-t SECONDS] [-Q PATH] [-R PATH]
                               ALIAS AGENT [INSTRUCTION]
```

Fork AGENT on ALIAS with INSTRUCTION. The fork runs on the target through its own launch machinery.

Options:

| Option                            | Description                                                                                                             | Default |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                    | Emit a schema-versioned JSON result                                                                                     | `false` |
| `-Q PATH`, `--request-path PATH`  | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`   | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |
| `-t SECONDS`, `--timeout SECONDS` | Per-request gateway timeout in seconds                                                                                  | —       |

Arguments:

| Argument      | Description                                                                                                          |
| ------------- | -------------------------------------------------------------------------------------------------------------------- |
| `alias`       | Enrolled machine alias                                                                                               |
| `agent`       | Remote agent name                                                                                                    |
| `instruction` | Fork instruction appended to #fork:<name>. Optional when sase's TUI supplies it through the durable request sidecar. |

### `sase machine agent retry`

```text
usage: sase machine agent retry [-h] [-j] [-t SECONDS] [-Q PATH] [-R PATH]
                                ALIAS AGENT [AGENT ...]
```

Retry one or more remote agents on ALIAS.

Options:

| Option                            | Description                                                                                                             | Default |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                    | Emit a schema-versioned JSON result                                                                                     | `false` |
| `-Q PATH`, `--request-path PATH`  | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`   | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |
| `-t SECONDS`, `--timeout SECONDS` | Per-request gateway timeout in seconds                                                                                  | —       |

Arguments:

| Argument | Description            |
| -------- | ---------------------- |
| `alias`  | Enrolled machine alias |
| `agents` | Remote agent names     |

### `sase machine agent stop`

```text
usage: sase machine agent stop [-h] [-j] [-t SECONDS] [-Q PATH] [-R PATH]
                               ALIAS AGENT [AGENT ...]
```

Stop one or more remote agents on ALIAS.

Options:

| Option                            | Description                                                                                                             | Default |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                    | Emit a schema-versioned JSON result                                                                                     | `false` |
| `-Q PATH`, `--request-path PATH`  | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`   | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |
| `-t SECONDS`, `--timeout SECONDS` | Per-request gateway timeout in seconds                                                                                  | —       |

Arguments:

| Argument | Description            |
| -------- | ---------------------- |
| `alias`  | Enrolled machine alias |
| `agents` | Remote agent names     |

## `sase machine attention`

```text
usage: sase machine attention [-h] {answer,approve} ...
```

Answer a pending remote question or approve a pending remote gate on its owning host. ALIAS is the enrolled machine; REQUEST identifies the pending attention request. sase's TUI supplies the request key, observed revision, selection, and operation key through the durable request sidecar.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                       | Summary                  |
| -------------------------------- | ------------------------ |
| `sase machine attention answer`  | Answer a remote question |
| `sase machine attention approve` | Approve a remote gate    |

### `sase machine attention answer`

```text
usage: sase machine attention answer [-h] [-j] [-t SECONDS] [-Q PATH]
                                     [-R PATH]
                                     ALIAS REQUEST [ANSWER]
```

Answer REQUEST on ALIAS with ANSWER.

Options:

| Option                            | Description                                                                                                             | Default |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                    | Emit a schema-versioned JSON result                                                                                     | `false` |
| `-Q PATH`, `--request-path PATH`  | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`   | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |
| `-t SECONDS`, `--timeout SECONDS` | Per-request gateway timeout in seconds                                                                                  | —       |

Arguments:

| Argument  | Description                                                                                                  |
| --------- | ------------------------------------------------------------------------------------------------------------ |
| `alias`   | Enrolled machine alias                                                                                       |
| `request` | Pending attention request identity                                                                           |
| `answer`  | Free-text answer. Optional when sase's TUI supplies a structured answer through the durable request sidecar. |

### `sase machine attention approve`

```text
usage: sase machine attention approve [-h] [-f TEXT] [-j] [-t SECONDS]
                                      [-Q PATH] [-R PATH]
                                      ALIAS REQUEST [OPTION ...]
```

Approve REQUEST on ALIAS by selecting one or more OPTIONs.

Options:

| Option                            | Description                                                                                                             | Default |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-f TEXT`, `--feedback TEXT`      | Optional feedback attached to the approval                                                                              | —       |
| `-h`, `--help`                    | show this help message and exit                                                                                         | —       |
| `-j`, `--json`                    | Emit a schema-versioned JSON result                                                                                     | `false` |
| `-Q PATH`, `--request-path PATH`  | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`   | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |
| `-t SECONDS`, `--timeout SECONDS` | Per-request gateway timeout in seconds                                                                                  | —       |

Arguments:

| Argument  | Description                                                                                               |
| --------- | --------------------------------------------------------------------------------------------------------- |
| `alias`   | Enrolled machine alias                                                                                    |
| `request` | Pending attention request identity                                                                        |
| `options` | Selected option IDs. Optional when sase's TUI supplies the selection through the durable request sidecar. |

## `sase machine bootstrap`

```text
usage: sase machine bootstrap [-h] [-e SECONDS] [-j] [-s SCOPE]
```

Issue a live single-use enrollment bundle on the target machine, as the same OS user and SASE home used by the gateway. The secret is written only to stdout and is never accepted as a command-line argument.

Options:

| Option                            | Description                                                          | Default |
| --------------------------------- | -------------------------------------------------------------------- | ------- |
| `-e SECONDS`, `--expires SECONDS` | Expire the bundle after SECONDS; omitted uses the store default      | —       |
| `-h`, `--help`                    | show this help message and exit                                      | —       |
| `-j`, `--json`                    | Emit the raw enrollment bundle JSON                                  | `false` |
| `-s SCOPE`, `--scope SCOPE`       | Allowed enrollment scope; repeatable, omitted uses the store default | —       |

## `sase machine discover`

```text
usage: sase machine discover [-h] [-j] [-p PROVIDER] [-t SECONDS]
```

Ask configured and explicitly selected dispatch providers for remote-machine enrollment candidates.

Options:

| Option                               | Description                               | Default |
| ------------------------------------ | ----------------------------------------- | ------- |
| `-h`, `--help`                       | show this help message and exit           | —       |
| `-j`, `--json`                       | Emit a schema-versioned JSON result       | `false` |
| `-p PROVIDER`, `--provider PROVIDER` | Provider ref to discover; repeatable      | —       |
| `-t SECONDS`, `--timeout SECONDS`    | Per-provider discovery timeout in seconds | —       |

## `sase machine init`

```text
usage: sase machine init [-h] [-B PATH] [-c] [-j] [-t SECONDS]
```

Canonical remote-machine initialization. Check and preview modes are offline. Explicit apply discovers configured providers, lists enrolled machines beside new candidates, and enrolls selected identities. The enrollment bundle is read from --bootstrap-file, piped stdin, or a hidden prompt; no secret value is accepted as a command-line option. Success is reported only after the applied config reloads and an authenticated hello succeeds.

Options:

| Option                             | Description                                                                    | Default |
| ---------------------------------- | ------------------------------------------------------------------------------ | ------- |
| `-B PATH`, `--bootstrap-file PATH` | Read the enrollment bundle from PATH instead of prompting                      | —       |
| `-c`, `--check`                    | Report whether remote-machine enrollment can be offered; performs no discovery | `false` |
| `-h`, `--help`                     | show this help message and exit                                                | —       |
| `-j`, `--json`                     | Emit a schema-versioned JSON result                                            | `false` |
| `-t SECONDS`, `--timeout SECONDS`  | Per-request gateway timeout in seconds                                         | —       |

## `sase machine list`

```text
usage: sase machine list [-h] [-j]
```

List configured remote machine aliases from local config only.

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a schema-versioned JSON result | `false` |

## `sase machine remove`

```text
usage: sase machine remove [-h] [-j] [-y] ALIAS
```

Remove ALIAS from local config and delete its local credential ref.

Options:

| Option         | Description                                       | Default |
| -------------- | ------------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                   | —       |
| `-j`, `--json` | Emit a schema-versioned JSON result               | `false` |
| `-y`, `--yes`  | Remove without an interactive confirmation prompt | `false` |

Arguments:

| Argument | Description     |
| -------- | --------------- |
| `alias`  | Alias to remove |

## `sase machine rename`

```text
usage: sase machine rename [-h] [-j] OLD_ALIAS NEW_ALIAS
```

Rename OLD_ALIAS to NEW_ALIAS without changing gateway identity or credential references.

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a schema-versioned JSON result | `false` |

Arguments:

| Argument    | Description   |
| ----------- | ------------- |
| `old_alias` | Current alias |
| `new_alias` | New alias     |

## `sase machine repair`

```text
usage: sase machine repair [-h] [-B PATH] [-j] [-t SECONDS] ALIAS
```

Re-enroll ALIAS using a fresh one-time bundle, deploy the updated record, and require an authenticated hello before retiring the still-applied credential.

Options:

| Option                             | Description                                               | Default |
| ---------------------------------- | --------------------------------------------------------- | ------- |
| `-B PATH`, `--bootstrap-file PATH` | Read the enrollment bundle from PATH instead of prompting | —       |
| `-h`, `--help`                     | show this help message and exit                           | —       |
| `-j`, `--json`                     | Emit a schema-versioned JSON result                       | `false` |
| `-t SECONDS`, `--timeout SECONDS`  | Per-request gateway timeout in seconds                    | —       |

Arguments:

| Argument | Description     |
| -------- | --------------- |
| `alias`  | Alias to repair |

## `sase machine show`

```text
usage: sase machine show [-h] [-j] ALIAS
```

Show the full local config record for one enrolled machine alias.

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a schema-versioned JSON result | `false` |

Arguments:

| Argument | Description              |
| -------- | ------------------------ |
| `alias`  | Configured alias to show |

## `sase machine status`

```text
usage: sase machine status [-h] [-j] [-t SECONDS] [ALIAS ...]
```

Check configured remote machines with bounded authenticated hello calls.

Options:

| Option                            | Description                            | Default |
| --------------------------------- | -------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit        | —       |
| `-j`, `--json`                    | Emit a schema-versioned JSON result    | `false` |
| `-t SECONDS`, `--timeout SECONDS` | Per-request gateway timeout in seconds | —       |

Arguments:

| Argument  | Description                                          |
| --------- | ---------------------------------------------------- |
| `aliases` | Aliases to check; defaults to all configured aliases |

Related: [CLI command groups](index.md).
