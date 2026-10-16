---
title: "sase migrate"
description: "Temporary offline migration kit for the canonical-only cutover."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase migrate

Temporary offline migration kit for canonical-only cutover operations

Reference for `sase migrate`. Run `sase migrate --help` for the exact output on this checkout.

```text
usage: sase migrate [-h]
                    {backup,list,plan,restore,resume,run,status,verify} ...
```

Temporary offline migration kit for the canonical-only cutover. Lists, plans, backs up, restores, applies, resumes, statuses, and verifies declared cutover operations outside every SASE runtime root; never runs automatically and is deleted in its entirety once the cutover completes. Bare `sase migrate` delegates to `sase migrate list`. Every subcommand is a dry run unless -a/--apply is given.

Bare `sase migrate` defaults to `sase migrate list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand             | Summary                                                        |
| ---------------------- | -------------------------------------------------------------- |
| `sase migrate backup`  | Capture a verified, checksummed backup of one declared root    |
| `sase migrate list`    | List the fixed migration operation catalog                     |
| `sase migrate plan`    | Dry-run one operation and persist its manifest                 |
| `sase migrate restore` | Verify and stage a restore of one backup; swap in with --apply |
| `sase migrate resume`  | Continue an interrupted migration run from its journal         |
| `sase migrate run`     | Execute a planned manifest                                     |
| `sase migrate status`  | Show migration runs, journal state, and resumability           |
| `sase migrate verify`  | Re-check post-conditions for one run                           |

## `sase migrate backup`

```text
usage: sase migrate backup [-h] [-a] [-j] [-s <dir>] <root>
```

Capture a quiescent-as-possible, checksummed, SQLite-consistent backup of <root> outside every SASE runtime root. Dry run unless -a/--apply, in which case it writes MANIFEST.json, SHA256SUMS, and provenance.json alongside the copied payload.

Options:

| Option                          | Description                                                | Default |
| ------------------------------- | ---------------------------------------------------------- | ------- |
| `-a`, `--apply`                 | Apply the backup (default: report what would be captured)  | `false` |
| `-h`, `--help`                  | show this help message and exit                            | —       |
| `-j`, `--json`                  | Emit a machine-readable JSON object                        | `false` |
| `-s <dir>`, `--secondary <dir>` | Also write a second durable copy of the backup under <dir> | —       |

Arguments:

| Argument | Description                                      |
| -------- | ------------------------------------------------ |
| `root`   | Filesystem path to the directory root to back up |

## `sase migrate list`

```text
usage: sase migrate list [-h] [-d <dir>] [-j] [-r <dir>]
```

List the four shipped migration operations and report whether their declared roots are present for the selected SASE home. Bare `sase migrate` delegates here.

Options:

| Option                     | Description                                                  | Default |
| -------------------------- | ------------------------------------------------------------ | ------- |
| `-h`, `--help`             | show this help message and exit                              | —       |
| `-d <dir>`, `--home <dir>` | Home directory used to resolve home-relative operation roots | —       |
| `-j`, `--json`             | Emit a machine-readable JSON object                          | `false` |
| `-r <dir>`, `--root <dir>` | SASE home root used to resolve operation roots               | —       |

## `sase migrate plan`

```text
usage: sase migrate plan [-h] [-b <id>] [-d <dir>] [-j] [-r <dir>] <operation>
```

Plan <operation>, write runs/<run-id>/manifest.json plus an initial journal record, mutate no source data, and print the manifest path. Apply later with `sase migrate run <manifest>`.

Options:

| Option                        | Description                                                  | Default |
| ----------------------------- | ------------------------------------------------------------ | ------- |
| `-b <id>`, `--backup-id <id>` | Verified backup id to bind into the manifest                 | —       |
| `-h`, `--help`                | show this help message and exit                              | —       |
| `-d <dir>`, `--home <dir>`    | Home directory used to resolve home-relative operation roots | —       |
| `-j`, `--json`                | Emit a machine-readable JSON object                          | `false` |
| `-r <dir>`, `--root <dir>`    | SASE home root used to resolve operation roots               | —       |

Arguments:

| Argument    | Description                                                                    |
| ----------- | ------------------------------------------------------------------------------ |
| `operation` | Operation to plan: import-purge, lock-residue, procs-residue, or state-residue |

## `sase migrate restore`

```text
usage: sase migrate restore [-h] [-a] [-j] [-r <dir>] <backup-id>
```

Verify a backup's SHA256SUMS before touching anything, restore it to a staging path, and report its diff and ownership deltas against the live root. Dry run unless -a/--apply, in which case the live root is moved aside (never deleted) and the staged copy is swapped into its place. The backup itself is never modified or deleted by a restore.

Options:

| Option                     | Description                                                          | Default |
| -------------------------- | -------------------------------------------------------------------- | ------- |
| `-a`, `--apply`            | Apply the restore (default: verify and stage only)                   | `false` |
| `-h`, `--help`             | show this help message and exit                                      | —       |
| `-j`, `--json`             | Emit a machine-readable JSON object                                  | `false` |
| `-r <dir>`, `--root <dir>` | Live root to diff and swap into (default: the backed-up source root) | —       |

Arguments:

| Argument    | Description                                               |
| ----------- | --------------------------------------------------------- |
| `backup_id` | Backup id to restore, as printed by `sase migrate backup` |

## `sase migrate resume`

```text
usage: sase migrate resume [-h] [-a] [-j] [-l <ms>] <run-id>
```

Replay a run journal, re-check source digests when the run has not started applying, and continue from the next resumable step. Dry run unless -a/--apply.

Options:

| Option                              | Description                                           | Default |
| ----------------------------------- | ----------------------------------------------------- | ------- |
| `-a`, `--apply`                     | Apply the resume (default: report the next step only) | `false` |
| `-h`, `--help`                      | show this help message and exit                       | —       |
| `-j`, `--json`                      | Emit a machine-readable JSON object                   | `false` |
| `-l <ms>`, `--lock-timeout-ms <ms>` | Bounded lock wait in milliseconds before refusing     | `5000`  |

Arguments:

| Argument | Description                            |
| -------- | -------------------------------------- |
| `run_id` | Run id whose journal should be resumed |

## `sase migrate run`

```text
usage: sase migrate run [-h] [-a] [-j] [-l <ms>] <manifest>
```

Run a manifest. Dry run checks digests, conflicts, and backup records without mutating data. -a/--apply executes the operation with a durable journal and receipt.

Options:

| Option                              | Description                                       | Default |
| ----------------------------------- | ------------------------------------------------- | ------- |
| `-a`, `--apply`                     | Apply the manifest (default: preflight only)      | `false` |
| `-h`, `--help`                      | show this help message and exit                   | —       |
| `-j`, `--json`                      | Emit a machine-readable JSON object               | `false` |
| `-l <ms>`, `--lock-timeout-ms <ms>` | Bounded lock wait in milliseconds before refusing | `5000`  |

Arguments:

| Argument   | Description                         |
| ---------- | ----------------------------------- |
| `manifest` | Path printed by `sase migrate plan` |

## `sase migrate status`

```text
usage: sase migrate status [-h] [-j]
```

Show every recorded migration run and its latest journal state.

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

## `sase migrate verify`

```text
usage: sase migrate verify [-h] [-j] <run-id>
```

Load one run manifest and re-check the operation's post-conditions and semantic fingerprints.

Options:

| Option         | Description                         | Default |
| -------------- | ----------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object | `false` |

Arguments:

| Argument | Description      |
| -------- | ---------------- |
| `run_id` | Run id to verify |

Related: [CLI command groups](index.md).
