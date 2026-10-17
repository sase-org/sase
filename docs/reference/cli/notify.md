---
title: "sase notify"
description: "Create and inspect raw notifications."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase notify

Create or inspect notifications

Reference for `sase notify`. Run `sase notify --help` for the exact output on this checkout.

```text
usage: sase notify [-h] [-s SENDER] [-t TAG]
                   {+1,apply-state,apply-state-many,create,list,rules,show} ...
```

Create and inspect raw notifications. Privileged gate actions must be created with `sase gate create`. With no subcommand, delegates to `sase notify list`.

Bare `sase notify` defaults to `sase notify list`.

Options:

| Option                         | Description                                               | Default |
| ------------------------------ | --------------------------------------------------------- | ------- |
| `-h`, `--help`                 | show this help message and exit                           | —       |
| `-s SENDER`, `--sender SENDER` | Notification sender name (overrides sender in JSON input) | —       |
| `-t TAG`, `--tag TAG`          | Tag for a created notification; repeat to add more tags   | —       |

Subcommands:

| Subcommand                     | Summary                                                             |
| ------------------------------ | ------------------------------------------------------------------- |
| `sase notify +1`               | Append a +1 corroboration note to an existing notification          |
| `sase notify apply-state`      | Apply a durable notification state change                           |
| `sase notify apply-state-many` | Apply a durable notification state change to a private id set       |
| `sase notify create`           | Create a notification (reads JSON from stdin or uses flags)         |
| `sase notify list`             | List recent notifications (pretty output by default, JSON with -j)  |
| `sase notify rules`            | Show notification delivery rules and explain how a row is delivered |
| `sase notify show`             | Show one notification by id                                         |

## `sase notify +1`

```text
usage: sase notify +1 [-h] [id] note [-k DEDUP_KEY] [-s SENDER]
```

Append a +1 corroboration note to an existing notification, by id or by (sender, dedup key). A +1 never changes read/dismissed/muted/snooze state, order, or delivery.

Options:

| Option                                  | Description                                                       | Default |
| --------------------------------------- | ----------------------------------------------------------------- | ------- |
| `-k DEDUP_KEY`, `--dedup-key DEDUP_KEY` | Address the newest row matching (sender, dedup key) instead of id | —       |
| `-h`, `--help`                          | show this help message and exit                                   | —       |
| `-s SENDER`, `--sender SENDER`          | +1 sender (default: the resolved current agent/user identity)     | —       |

Arguments:

| Argument | Description                                           |
| -------- | ----------------------------------------------------- |
| `id`     | Notification id or unique prefix (omit when using -k) |
| `note`   | Corroboration note text                               |

## `sase notify apply-state`

```text
usage: sase notify apply-state [-h] notification_id
                               {dismiss,mute,read,snooze,undismiss,unmute}
                               [-Q PATH] [-R PATH]
```

Mark one notification read, dismissed, undismissed, muted, unmuted, or snoozed. The notification id and action are positional; snooze expiry may come from the private request sidecar.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument          | Description               |
| ----------------- | ------------------------- |
| `notification_id` | Notification id to update |
| `action`          | State change to apply     |

## `sase notify apply-state-many`

```text
usage: sase notify apply-state-many [-h]
                                    {dismiss,mute,read,snooze,undismiss,unmute}
                                    [-Q PATH] [-R PATH]
```

Apply a notification state update to ids carried in the private request sidecar. This command is intended for durable ACE procs.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description           |
| -------- | --------------------- |
| `action` | State change to apply |

## `sase notify create`

```text
usage: sase notify create [-h] [-k DEDUP_KEY] [-p PLUS_ONE_NOTE] [-s SENDER]
                          [-S SUPERSEDES] [-t TAG]
```

Create a raw notification from stdin JSON. Raw notifications accept sender, icon, color, notes, files, tags, action, action_data, and silent. The color is an '#RRGGBB' accent for the notification-panel tab this row lands in. Privileged gate actions cannot be created through this raw notification interface; use `sase gate create` instead.

Options:

| Option                                              | Description                                                                                                                                                  | Default |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| `-k DEDUP_KEY`, `--dedup-key DEDUP_KEY`             | Sender-scoped dedup key. No existing (sender, key) row: create it with this key. A match: append -p/--plus-one-note to it instead of creating (requires -p). | —       |
| `-h`, `--help`                                      | show this help message and exit                                                                                                                              | —       |
| `-p PLUS_ONE_NOTE`, `--plus-one-note PLUS_ONE_NOTE` | Note appended when -k/--dedup-key matches an existing row                                                                                                    | —       |
| `-s SENDER`, `--sender SENDER`                      | Notification sender name (overrides sender in JSON input)                                                                                                    | —       |
| `-S SUPERSEDES`, `--supersedes SUPERSEDES`          | Old dedup key to retire on create: matching rows get a superseding +1 and are dismissed                                                                      | —       |
| `-t TAG`, `--tag TAG`                               | Tag for the created notification; repeat to add more tags                                                                                                    | —       |

## `sase notify list`

```text
usage: sase notify list [-h] [-a] [-j] [-l LIMIT] [-q QUERY] [-s SENDER]
                        [-t TAG] [-u]
```

Options:

| Option                         | Description                                                | Default |
| ------------------------------ | ---------------------------------------------------------- | ------- |
| `-a`, `--all`                  | Include dismissed notifications                            | `false` |
| `-h`, `--help`                 | show this help message and exit                            | —       |
| `-j`, `--json`                 | Emit a machine-readable JSON array (stable schema)         | `false` |
| `-l LIMIT`, `--limit LIMIT`    | Maximum number of notifications to return (default: 20)    | `20`    |
| `-q QUERY`, `--query QUERY`    | Case-insensitive substring filter over notification fields | —       |
| `-s SENDER`, `--sender SENDER` | Only include notifications from this sender                | —       |
| `-t TAG`, `--tag TAG`          | Only include notifications with this tag                   | —       |
| `-u`, `--unread`               | Only include unread notifications                          | `false` |

## `sase notify rules`

```text
usage: sase notify rules [-h] [-e ID] [-j]
```

Show the merged `ace.notification_rules` in the order they are consulted, with the config layer each came from and the criteria and behaviors it sets. Rules only change how a new notification is announced (a TUI toast and a sound); the notification is still stored, unread, and listed.

Options:

| Option                  | Description                                                                                                                                           | Default |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-e ID`, `--explain ID` | Explain one stored notification (id or unique prefix): its match fields and, for toast and sound, which rule decides each or that the default applies | —       |
| `-h`, `--help`          | show this help message and exit                                                                                                                       | —       |
| `-j`, `--json`          | Emit machine-readable JSON instead of formatted text                                                                                                  | `false` |

## `sase notify show`

```text
usage: sase notify show [-h] [-f {markdown,json}] -i ID
```

Options:

| Option                         | Description                                                                 | Default    |
| ------------------------------ | --------------------------------------------------------------------------- | ---------- |
| `-f FORMAT`, `--format FORMAT` | Output format: 'markdown' (default) or 'json' (choices: `json`, `markdown`) | `markdown` |
| `-h`, `--help`                 | show this help message and exit                                             | —          |
| `-i ID`, `--id ID`             | Notification id to inspect (required)                                       | —          |

Related: [CLI command groups](index.md).
