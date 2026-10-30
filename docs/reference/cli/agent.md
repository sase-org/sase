---
title: "sase agent"
description: "Inspect and manage agents across projects."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase agent

List, inspect, synchronize, and manage agents across projects

Reference for `sase agent`. Run `sase agent --help` for the exact output on this checkout.

```text
usage: sase agent [-h]
                  {archive,artifacts,auto-restart,drain,hold,index,kill,list,load,names,persist-cleanup,persist-directive,prompts,restart,revert,search,show,sync,tab,tribe,wait} ...
```

Inspect and manage agents across projects. Running bare `sase agent` delegates to `sase agent list`.

Bare `sase agent` defaults to `sase agent list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                     | Summary                                                                                                  |
| ------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `sase agent archive`           | Maintain dismissed-agent archive indexes                                                                 |
| `sase agent artifacts`         | Inspect and migrate agent artifact storage                                                               |
| `sase agent auto-restart`      | Relaunch agents broken by a live sase update (at most once each)                                         |
| `sase agent drain`             | Relaunch agents stranded by one hard-disabled provider                                                   |
| `sase agent hold`              | Arm and manage reverse-wait admission holds (blocks WAITING/QUEUED/future agents and undispatched procs) |
| `sase agent index`             | Manage the persistent agent artifact index                                                               |
| `sase agent kill`              | SIGTERM a running agent by name                                                                          |
| `sase agent list`              | List running agents (pretty table by default, JSON with -j)                                              |
| `sase agent load`              | Show this machine's runner capacity from the authoritative report                                        |
| `sase agent names`             | Maintain the permanent agent-name registry and migrations                                                |
| `sase agent persist-cleanup`   | Persist kill, dismiss, or save cleanup from a private request sidecar                                    |
| `sase agent persist-directive` | Persist an agent directive update from a private request sidecar                                         |
| `sase agent prompts`           | Inspect and validate canonical prompt persistence                                                        |
| `sase agent restart`           | Stop a named agent and immediately relaunch its stored prompt                                            |
| `sase agent revert`            | Execute a previously previewed agent commit revert                                                       |
| `sase agent search`            | Search the agent catalog or archive                                                                      |
| `sase agent show`              | Render a full detail panel for one agent                                                                 |
| `sase agent sync`              | Publish local agent hoods and inspect sidecar git status                                                 |
| `sase agent tab`               | Move agents between Agents-tab placements (used by the Agents tab)                                       |
| `sase agent tribe`             | Manage the user-defined tribe on an agent (used by the Agents tab)                                       |
| `sase agent wait`              | Block until named agents (or every running agent) reach a terminal state                                 |

## `sase agent archive`

```text
usage: sase agent archive [-h] {rebuild-index,verify} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                         | Summary                                    |
| ---------------------------------- | ------------------------------------------ |
| `sase agent archive rebuild-index` | Rebuild the dismissed bundle summary index |
| `sase agent archive verify`        | Verify the dismissed bundle summary index  |

### `sase agent archive rebuild-index`

```text
usage: sase agent archive rebuild-index [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

### `sase agent archive verify`

```text
usage: sase agent archive verify [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase agent artifacts`

```text
usage: sase agent artifacts [-h] {layout} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                    | Summary                                     |
| ----------------------------- | ------------------------------------------- |
| `sase agent artifacts layout` | Manage the ace-run physical artifact layout |

### `sase agent artifacts layout`

```text
usage: sase agent artifacts layout [-h] {migrate,rollback,status,verify} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                             | Summary                                                  |
| -------------------------------------- | -------------------------------------------------------- |
| `sase agent artifacts layout migrate`  | Move flat ace-run artifact dirs into day shards          |
| `sase agent artifacts layout rollback` | Move migrated ace-run artifact dirs back from a manifest |
| `sase agent artifacts layout status`   | Report ace-run layout counts and index alias status      |
| `sase agent artifacts layout verify`   | Verify ace-run layout state against a manifest           |

#### `sase agent artifacts layout migrate`

```text
usage: sase agent artifacts layout migrate [-h] [-d] [-i INDEX_PATH] [-j]
                                           [-l LIMIT] [-m MANIFEST]
                                           [-P PROJECT] [-p PROJECTS_ROOT]
```

Options:

| Option                                              | Description                                                      | Default |
| --------------------------------------------------- | ---------------------------------------------------------------- | ------- |
| `-d`, `--dry-run`                                   | Write or print the migration manifest without moving dirs        | `false` |
| `-h`, `--help`                                      | show this help message and exit                                  | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH`          | SQLite index path (default: ~/.sase/agent_artifact_index.sqlite) | —       |
| `-j`, `--json`                                      | Emit a machine-readable JSON object                              | `false` |
| `-l LIMIT`, `--limit LIMIT`                         | Migrate at most N artifact dirs                                  | —       |
| `-m MANIFEST`, `--manifest MANIFEST`                | Manifest path for migration, verification, or rollback           | —       |
| `-P PROJECT`, `--project PROJECT`                   | Limit to one project                                             | —       |
| `-p PROJECTS_ROOT`, `--projects-root PROJECTS_ROOT` | Projects artifact root (default: ~/.sase/projects)               | —       |

#### `sase agent artifacts layout rollback`

```text
usage: sase agent artifacts layout rollback [-h] [-i INDEX_PATH] [-j]
                                            [-m MANIFEST] [-P PROJECT]
                                            [-p PROJECTS_ROOT]
```

Options:

| Option                                              | Description                                                      | Default |
| --------------------------------------------------- | ---------------------------------------------------------------- | ------- |
| `-h`, `--help`                                      | show this help message and exit                                  | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH`          | SQLite index path (default: ~/.sase/agent_artifact_index.sqlite) | —       |
| `-j`, `--json`                                      | Emit a machine-readable JSON object                              | `false` |
| `-m MANIFEST`, `--manifest MANIFEST`                | Manifest path for migration, verification, or rollback           | —       |
| `-P PROJECT`, `--project PROJECT`                   | Limit to one project                                             | —       |
| `-p PROJECTS_ROOT`, `--projects-root PROJECTS_ROOT` | Projects artifact root (default: ~/.sase/projects)               | —       |

#### `sase agent artifacts layout status`

```text
usage: sase agent artifacts layout status [-h] [-i INDEX_PATH] [-j]
                                          [-P PROJECT] [-p PROJECTS_ROOT]
```

Options:

| Option                                              | Description                                                      | Default |
| --------------------------------------------------- | ---------------------------------------------------------------- | ------- |
| `-h`, `--help`                                      | show this help message and exit                                  | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH`          | SQLite index path (default: ~/.sase/agent_artifact_index.sqlite) | —       |
| `-j`, `--json`                                      | Emit a machine-readable JSON object                              | `false` |
| `-P PROJECT`, `--project PROJECT`                   | Limit to one project                                             | —       |
| `-p PROJECTS_ROOT`, `--projects-root PROJECTS_ROOT` | Projects artifact root (default: ~/.sase/projects)               | —       |

#### `sase agent artifacts layout verify`

```text
usage: sase agent artifacts layout verify [-h] [-i INDEX_PATH] [-j]
                                          [-m MANIFEST] [-P PROJECT]
                                          [-p PROJECTS_ROOT]
```

Options:

| Option                                              | Description                                                      | Default |
| --------------------------------------------------- | ---------------------------------------------------------------- | ------- |
| `-h`, `--help`                                      | show this help message and exit                                  | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH`          | SQLite index path (default: ~/.sase/agent_artifact_index.sqlite) | —       |
| `-j`, `--json`                                      | Emit a machine-readable JSON object                              | `false` |
| `-m MANIFEST`, `--manifest MANIFEST`                | Manifest path for migration, verification, or rollback           | —       |
| `-P PROJECT`, `--project PROJECT`                   | Limit to one project                                             | —       |
| `-p PROJECTS_ROOT`, `--projects-root PROJECTS_ROOT` | Projects artifact root (default: ~/.sase/projects)               | —       |

## `sase agent auto-restart`

```text
usage: sase agent auto-restart [-h] {list,resume,run,scan,show} ...
```

Relaunch agents broken by a live sase update, once per lineage. Running `sase agent auto-restart` with no subcommand lists ledger records. `scan` is strictly read-only: it never writes the restart ledger or relaunches anything.

Bare `sase agent auto-restart` defaults to `sase agent auto-restart list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                       | Summary                                                       |
| -------------------------------- | ------------------------------------------------------------- |
| `sase agent auto-restart list`   | List restart ledger records, newest first, grouped by episode |
| `sase agent auto-restart resume` | Re-arm after the storm breaker trips                          |
| `sase agent auto-restart run`    | Claim the ledger and relaunch a failed agent once             |
| `sase agent auto-restart scan`   | Replay the classifier over recent failures (read-only)        |
| `sase agent auto-restart show`   | Show one ledger record with its verdict and witnesses         |

### `sase agent auto-restart list`

```text
usage: sase agent auto-restart list [-h] [-a] [-j]
```

List update-skew restart ledger records, newest first, grouped by episode. A bare `sase agent auto-restart` delegates here.

Options:

| Option         | Description                                                   | Default |
| -------------- | ------------------------------------------------------------- | ------- |
| `-a`, `--all`  | Include settled and declined records, not just in-flight ones | `false` |
| `-h`, `--help` | show this help message and exit                               | —       |
| `-j`, `--json` | Print ledger records as JSON instead of a table               | `false` |

### `sase agent auto-restart resume`

```text
usage: sase agent auto-restart resume [-h]
```

Clear the storm-breaker pause so the healer may act again.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

### `sase agent auto-restart run`

```text
usage: sase agent auto-restart run [-h] ([name] | -a DIR | -p) [-n] [-j]
```

Run the healer: claim the at-most-once ledger, verify the update-skew signature, witnesses, quiescence, and probe, then relaunch the failed agent under the same name. A manual run still honors the ledger.

Options:

| Option                          | Description                                             | Default |
| ------------------------------- | ------------------------------------------------------- | ------- |
| `-a DIR`, `--artifacts-dir DIR` | Heal the failed row at DIR                              | —       |
| `-n`, `--dry-run`               | Verify without claiming, relaunching, or notifying      | `false` |
| `-h`, `--help`                  | show this help message and exit                         | —       |
| `-j`, `--json`                  | Print healer outcomes as JSON instead of a table        | `false` |
| `-p`, `--pending`               | Heal every pending failure (the scheduler job's target) | `false` |

Arguments:

| Argument | Description        |
| -------- | ------------------ |
| `name`   | Agent name to heal |

### `sase agent auto-restart scan`

```text
usage: sase agent auto-restart scan [-h] [-j] [-l N] [-s DURATION]
```

Classify failed agents and dismissed bundles within --since through the update-skew classifier and print one row per failure with its signature, witnesses, and verdict. Never writes the ledger or relaunches anything.

Options:

| Option                            | Description                                                                                                          | Default |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                                                                      | —       |
| `-j`, `--json`                    | Print verdict wires as JSON instead of a table                                                                       | `false` |
| `-l N`, `--limit N`               | Show at most N rows (default: 50); the summary always covers the full set                                            | —       |
| `-s DURATION`, `--since DURATION` | Only include failures from the last DURATION: bare seconds or a duration like 90s / 45m / 2h / 7d / 2w (default: 7d) | `7d`    |

### `sase agent auto-restart show`

```text
usage: sase agent auto-restart show [-h] TARGET [-j]
```

Show one restart ledger record: the verdict, a checklist of witnesses, the state timeline, and the evidence bundle path.

Options:

| Option         | Description                                | Default |
| -------------- | ------------------------------------------ | ------- |
| `-h`, `--help` | show this help message and exit            | —       |
| `-j`, `--json` | Print the record as JSON instead of a card | `false` |

Arguments:

| Argument | Description                             |
| -------- | --------------------------------------- |
| `target` | Ledger key, lineage root, or agent name |

## `sase agent drain`

```text
usage: sase agent drain [-h] [-j] [-l N] [-m MODEL] [-n] [-y] [-Q PATH]
                        [-R PATH] PROVIDER
```

Plan and apply a provider drain. The provider must have an active hard disable; enabled and soft-disabled providers are refused so agents cannot relaunch straight back onto them. Planning finishes before anything is killed. Draining live agents discards their in-flight work; chat transcripts are kept. Exit 0 means drained or previewed, 2 means refused with nothing changed, and 1 means at least one move failed after execution started.

Options:

| Option                           | Description                                                                                                                     | Default |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`                | Print the preview and exit 0 without killing or launching                                                                       | `false` |
| `-h`, `--help`                   | show this help message and exit                                                                                                 | —       |
| `-j`, `--json`                   | Emit one stable JSON envelope on stdout and nothing else                                                                        | `false` |
| `-l N`, `--limit N`              | Most agents to move (default: 20)                                                                                               | `20`    |
| `-m MODEL`, `--model MODEL`      | Relaunch every moved agent on this model. Accepts [provider/]model[@effort], the same spelling `sase agent restart -m` accepts. | —       |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set.         | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.               | —       |
| `-y`, `--yes`                    | Skip the interactive confirmation before discarding live work                                                                   | `false` |

Arguments:

| Argument   | Description                     |
| ---------- | ------------------------------- |
| `provider` | Hard-disabled provider to drain |

## `sase agent hold`

```text
usage: sase agent hold [-h] {create,list,release,run,show} ...
```

Create, inspect, release, and wrap durable admission holds. Running bare `sase agent hold` delegates to `sase agent hold list`.

Bare `sase agent hold` defaults to `sase agent hold list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                | Summary                                                               |
| ------------------------- | --------------------------------------------------------------------- |
| `sase agent hold create`  | Arm a hold from name/@tribe selectors or -n/-t/-H/-f/-p               |
| `sase agent hold list`    | List active holds                                                     |
| `sase agent hold release` | Release a hold (defaults to the current agent/session's own hold)     |
| `sase agent hold run`     | Arm a hold around a command, releasing it when the command exits      |
| `sase agent hold show`    | Show full detail for one hold, including frozen pending artifact dirs |

### `sase agent hold create`

```text
usage: sase agent hold create [-h] [-n NAME] [-t TRIBE] [-H HOOD] [-f] [-p]
                              [-s {project,host}] [-T DURATION] [SELECTOR ...]
```

Options:

| Option                          | Description                                                                                                                                   | Default   |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| `-f`, `--future`                | Block agents and undispatched procs submitted after this hold is armed                                                                        | `false`   |
| `-h`, `--help`                  | show this help message and exit                                                                                                               | —         |
| `-H HOOD`, `--hood HOOD`        | Block agents in this hood, without a --role suffix (repeatable)                                                                               | —         |
| `-n NAME`, `--name NAME`        | Block this agent, agent session, clan, workflow, or named proc name (repeatable; role-suffixed names stay exact)                              | —         |
| `-p`, `--pending`               | Freeze the WAITING/QUEUED agents in scope right now and block only those (does not capture undispatched procs or agents/procs launched later) | `false`   |
| `-s SCOPE`, `--scope SCOPE`     | Limit the hold to the current project, or the whole host (default: project) (choices: `host`, `project`)                                      | `project` |
| `-t TRIBE`, `--tribe TRIBE`     | Block agents in this tribe, with or without '@' (repeatable)                                                                                  | —         |
| `-T DURATION`, `--ttl DURATION` | Hold TTL: bare seconds or a duration like 90s / 45m / 2h (default: the configured agent_hold_default_ttl)                                     | —         |

Arguments:

| Argument    | Description                                                                  |
| ----------- | ---------------------------------------------------------------------------- |
| `selectors` | Name or @tribe selectors to block; same expansion as %hold names and @tribes |

### `sase agent hold list`

```text
usage: sase agent hold list [-h] [-j]
```

Options:

| Option         | Description                                  | Default |
| -------------- | -------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit              | —       |
| `-j`, `--json` | Print a stable JSON array instead of a table | `false` |

### `sase agent hold release`

```text
usage: sase agent hold release [-h] [-k ARMER_KEY] [ARMER_KEY]
```

Options:

| Option                            | Description                                                       | Default |
| --------------------------------- | ----------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                   | —       |
| `-k ARMER_KEY`, `--key ARMER_KEY` | Armer key to release; alias for the optional positional ARMER_KEY | —       |

Arguments:

| Argument    | Description                                                          |
| ----------- | -------------------------------------------------------------------- |
| `armer_key` | Armer key to release (default: the current agent/session's own hold) |

### `sase agent hold run`

```text
usage: sase agent hold run [-h] [-n NAME] [-t TRIBE] [-H HOOD] [-f] [-p]
                           [-s {project,host}] [-T DURATION] ...
```

Arm a hold, run COMMAND, and release the hold in all cases -- success, failure, or interruption -- preserving COMMAND's exit status. With no selector flags, defaults to -f/--future plus -p/--pending (the documented selector-free quiesce recipe).

Options:

| Option                          | Description                                                                                                                                   | Default   |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| `-f`, `--future`                | Block agents and undispatched procs submitted after this hold is armed                                                                        | `false`   |
| `-h`, `--help`                  | show this help message and exit                                                                                                               | —         |
| `-H HOOD`, `--hood HOOD`        | Block agents in this hood, without a --role suffix (repeatable)                                                                               | —         |
| `-n NAME`, `--name NAME`        | Block this agent, agent session, clan, workflow, or named proc name (repeatable; role-suffixed names stay exact)                              | —         |
| `-p`, `--pending`               | Freeze the WAITING/QUEUED agents in scope right now and block only those (does not capture undispatched procs or agents/procs launched later) | `false`   |
| `-s SCOPE`, `--scope SCOPE`     | Limit the hold to the current project, or the whole host (default: project) (choices: `host`, `project`)                                      | `project` |
| `-t TRIBE`, `--tribe TRIBE`     | Block agents in this tribe, with or without '@' (repeatable)                                                                                  | —         |
| `-T DURATION`, `--ttl DURATION` | Hold TTL ceiling while COMMAND runs: bare seconds or a duration like 90s / 45m / 2h (default: the configured agent_hold_default_ttl)          | —         |

Arguments:

| Argument                 | Description                                         |
| ------------------------ | --------------------------------------------------- |
| `hold_run_command_words` | The command to run under the hold, introduced by -- |

### `sase agent hold show`

```text
usage: sase agent hold show [-h] [-k ARMER_KEY] [ARMER_KEY] [-j]
```

Options:

| Option                            | Description                                                 | Default |
| --------------------------------- | ----------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                             | —       |
| `-j`, `--json`                    | Print the raw hold record as JSON instead of a detail panel | `false` |
| `-k ARMER_KEY`, `--key ARMER_KEY` | Armer key to show; alias for the positional ARMER_KEY       | —       |

Arguments:

| Argument    | Description       |
| ----------- | ----------------- |
| `armer_key` | Armer key to show |

## `sase agent index`

```text
usage: sase agent index [-h] {gc,rebuild,status,vacuum,verify} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                 | Summary                                                           |
| -------------------------- | ----------------------------------------------------------------- |
| `sase agent index gc`      | Reconcile stale artifact-index rows and dismissed identities      |
| `sase agent index rebuild` | Rebuild the persistent agent artifact index from artifacts        |
| `sase agent index status`  | Inspect visible-inbox index health without scanning artifacts     |
| `sase agent index vacuum`  | Report or reclaim freelist space in the persistent artifact index |
| `sase agent index verify`  | Verify the persistent agent artifact index against artifacts      |

### `sase agent index gc`

```text
usage: sase agent index gc [-h] [-i INDEX_PATH] [-j] [--dry-run]
                           [-p PROJECTS_ROOT] [-r]
```

Options:

| Option                                              | Description                                                                                                                                                                | Default |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `--dry-run`                                         | Report index-gc reconciliation counts without mutating the index                                                                                                           | `false` |
| `-h`, `--help`                                      | show this help message and exit                                                                                                                                            | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH`          | SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)                                                                                                           | —       |
| `-j`, `--json`                                      | Emit a machine-readable JSON object                                                                                                                                        | `false` |
| `-p PROJECTS_ROOT`, `--projects-root PROJECTS_ROOT` | Projects artifact root (default: ~/.sase/projects)                                                                                                                         | —       |
| `-r`, `--purge-revived-bundles`                     | Before rebuilding, purge dismissed-bundle files and summary rows for already-revived agents (suffixes absent from dismissed_agents.json) so they stop re-hiding on rebuild | `false` |

### `sase agent index rebuild`

```text
usage: sase agent index rebuild [-h] [-i INDEX_PATH] [-j] [-p PROJECTS_ROOT]
```

Options:

| Option                                              | Description                                                      | Default |
| --------------------------------------------------- | ---------------------------------------------------------------- | ------- |
| `-h`, `--help`                                      | show this help message and exit                                  | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH`          | SQLite index path (default: ~/.sase/agent_artifact_index.sqlite) | —       |
| `-j`, `--json`                                      | Emit a machine-readable JSON object                              | `false` |
| `-p PROJECTS_ROOT`, `--projects-root PROJECTS_ROOT` | Projects artifact root (default: ~/.sase/projects)               | —       |

### `sase agent index status`

```text
usage: sase agent index status [-h] [-i INDEX_PATH] [-j] [-p PROJECTS_ROOT]
```

Options:

| Option                                              | Description                                                      | Default |
| --------------------------------------------------- | ---------------------------------------------------------------- | ------- |
| `-h`, `--help`                                      | show this help message and exit                                  | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH`          | SQLite index path (default: ~/.sase/agent_artifact_index.sqlite) | —       |
| `-j`, `--json`                                      | Emit a machine-readable JSON object                              | `false` |
| `-p PROJECTS_ROOT`, `--projects-root PROJECTS_ROOT` | Projects artifact root (default: ~/.sase/projects)               | —       |

### `sase agent index vacuum`

```text
usage: sase agent index vacuum [-h] [-a] [-i INDEX_PATH] [-j]
```

Report freelist pages left behind by deletes (never reclaimed by normal SQLite operation) and dismissed-identity row counts. The command is a dry-run report unless --apply is provided, in which case it runs VACUUM to compact the index file. VACUUM rebuilds the file losslessly; it never removes or alters a row.

Options:

| Option                                     | Description                                                      | Default |
| ------------------------------------------ | ---------------------------------------------------------------- | ------- |
| `-a`, `--apply`                            | Run VACUUM to reclaim freelist space (default: report only)      | `false` |
| `-h`, `--help`                             | show this help message and exit                                  | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH` | SQLite index path (default: ~/.sase/agent_artifact_index.sqlite) | —       |
| `-j`, `--json`                             | Emit a machine-readable JSON object                              | `false` |

### `sase agent index verify`

```text
usage: sase agent index verify [-h] [-i INDEX_PATH] [-j] [-p PROJECTS_ROOT]
```

Options:

| Option                                              | Description                                                      | Default |
| --------------------------------------------------- | ---------------------------------------------------------------- | ------- |
| `-h`, `--help`                                      | show this help message and exit                                  | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH`          | SQLite index path (default: ~/.sase/agent_artifact_index.sqlite) | —       |
| `-j`, `--json`                                      | Emit a machine-readable JSON object                              | `false` |
| `-p PROJECTS_ROOT`, `--projects-root PROJECTS_ROOT` | Projects artifact root (default: ~/.sase/projects)               | —       |

## `sase agent kill`

```text
usage: sase agent kill [-h] -n NAME
```

Options:

| Option                   | Description                          | Default |
| ------------------------ | ------------------------------------ | ------- |
| `-h`, `--help`           | show this help message and exit      | —       |
| `-n NAME`, `--name NAME` | Name of the agent to kill (required) | —       |

## `sase agent list`

```text
usage: sase agent list [-h] [-a] [-j] [-p PROJECT]
```

Options:

| Option                            | Description                                                                          | Default |
| --------------------------------- | ------------------------------------------------------------------------------------ | ------- |
| `-a`, `--all`                     | Include recently-completed DONE/FAILED agents (capped at 50 most-recent per project) | `false` |
| `-h`, `--help`                    | show this help message and exit                                                      | —       |
| `-j`, `--json`                    | Emit a machine-readable JSON array (stable schema)                                   | `false` |
| `-p PROJECT`, `--project PROJECT` | Only show agents for the given project name                                          | —       |

## `sase agent load`

```text
usage: sase agent load [-h] [-j] [-r]
```

Show this machine's runner capacity the way admission sees it: a verdict and gauge, who is using capacity, who is queued and why, live agents holding nothing, and inactive records counted rather than listed. Reads the same scan cache and Rust snapshot admission uses; display reads never take the admission lock. Exit 0 always: an invalid snapshot reads as blocked, never as free capacity.

Options:

| Option           | Description                                                   | Default |
| ---------------- | ------------------------------------------------------------- | ------- |
| `-h`, `--help`   | show this help message and exit                               | —       |
| `-j`, `--json`   | Emit the exact capacity report as JSON (stable schema)        | `false` |
| `-r`, `--rescan` | Force a fresh capacity scan instead of reusing the scan cache | `false` |

## `sase agent names`

```text
usage: sase agent names [-h] {migrate-auto,purge-local-state} ...
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                           | Summary                                                     |
| ------------------------------------ | ----------------------------------------------------------- |
| `sase agent names migrate-auto`      | Run the historical auto-name namespace migration            |
| `sase agent names purge-local-state` | Purge every locally materialized agents-sync import closure |

### `sase agent names migrate-auto`

```text
usage: sase agent names migrate-auto [-h] [-f] [-j]
```

Options:

| Option          | Description                                                  | Default |
| --------------- | ------------------------------------------------------------ | ------- |
| `-f`, `--force` | Run even when the migration marker says it already completed | `false` |
| `-h`, `--help`  | show this help message and exit                              | —       |
| `-j`, `--json`  | Emit a machine-readable JSON object                          | `false` |

### `sase agent names purge-local-state`

```text
usage: sase agent names purge-local-state [-h] [-a] [-j]
```

Remove every locally materialized import closure regardless of transport or source machine: imported artifacts, chat files, dismissed bundles, dismissed identities, import journals and staging, the incoming cache, and import receipts. The command is a dry run unless --apply is given, in which case it deletes that closure and rebuilds the agent-name registry.

Options:

| Option          | Description                                                          | Default |
| --------------- | -------------------------------------------------------------------- | ------- |
| `-a`, `--apply` | Apply the purge (default: report the closure without changing state) | `false` |
| `-h`, `--help`  | show this help message and exit                                      | —       |
| `-j`, `--json`  | Emit a machine-readable JSON object                                  | `false` |

## `sase agent persist-cleanup`

```text
usage: sase agent persist-cleanup [-h] [-Q PATH] [-R PATH]
```

Apply one JSON-shaped agent cleanup persistence spec. Identities and cleanup-plan details come from the private request sidecar.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

## `sase agent persist-directive`

```text
usage: sase agent persist-directive [-h] artifacts_dir [-Q PATH] [-R PATH]
```

Apply one JSON-shaped agent-directive persistence spec. The artifacts directory is positional; mutation details come from the private request sidecar.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument        | Description                                             |
| --------------- | ------------------------------------------------------- |
| `artifacts_dir` | Agent artifacts directory that owns the directive files |

## `sase agent prompts`

```text
usage: sase agent prompts [-h] {list,migrate,show,validate} ...
```

Inspect prompts published in the agents sidecar and validate their headers, artifact bytes, local manifests, and plan links. With no subcommand, `sase agent prompts` defaults to `sase agent prompts list`.

Bare `sase agent prompts` defaults to `sase agent prompts list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                    | Summary                                                          |
| ----------------------------- | ---------------------------------------------------------------- |
| `sase agent prompts list`     | List canonical archived prompts                                  |
| `sase agent prompts migrate`  | Migrate historical prompts from the plans sidecar                |
| `sase agent prompts show`     | Show one canonical archived prompt                               |
| `sase agent prompts validate` | Validate canonical prompts, artifacts, manifests, and plan links |

### `sase agent prompts list`

```text
usage: sase agent prompts list [-h] [-j] [-m YYYYMM] [-p PROJECT]
```

List prompts from the selected project's agents sidecar.

Options:

| Option                            | Description                                                  | Default |
| --------------------------------- | ------------------------------------------------------------ | ------- |
| `-h`, `--help`                    | show this help message and exit                              | —       |
| `-j`, `--json`                    | Emit stable machine-readable JSON                            | `false` |
| `-m YYYYMM`, `--month YYYYMM`     | Limit the operation to one archive month                     | —       |
| `-p PROJECT`, `--project PROJECT` | Select a project by name or alias (default: current project) | —       |

### `sase agent prompts migrate`

```text
usage: sase agent prompts migrate [-h] [-j] [-m YYYYMM] [-p PROJECT] [-w]
```

Report historical plans-sidecar prompts by default; use --write to move them into the canonical agents-sidecar archive. Migrated prompt text is scanned through publication protection before staging; withheld files stay in the plans sidecar, and a secret-scan push rejection never recommends replaying the rejected commit.

Options:

| Option                            | Description                                                          | Default |
| --------------------------------- | -------------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                      | —       |
| `-j`, `--json`                    | Emit stable machine-readable JSON                                    | `false` |
| `-m YYYYMM`, `--month YYYYMM`     | Limit the operation to one archive month                             | —       |
| `-p PROJECT`, `--project PROJECT` | Select a project by name or alias (default: current project)         | —       |
| `-w`, `--write`                   | Apply, commit, and publish both sidecars (default: read-only report) | `false` |

### `sase agent prompts show`

```text
usage: sase agent prompts show [-h] PROMPT [-j] [-p PROJECT]
```

Options:

| Option                            | Description                                                  | Default |
| --------------------------------- | ------------------------------------------------------------ | ------- |
| `-h`, `--help`                    | show this help message and exit                              | —       |
| `-j`, `--json`                    | Emit stable machine-readable JSON                            | `false` |
| `-p PROJECT`, `--project PROJECT` | Select a project by name or alias (default: current project) | —       |

Arguments:

| Argument | Description                                         |
| -------- | --------------------------------------------------- |
| `prompt` | Prompt name, YYYYMM/name, or prompts/YYYYMM/name.md |

### `sase agent prompts validate`

```text
usage: sase agent prompts validate [-h] [-j] [-m YYYYMM] [-p PROJECT] [-s]
```

Options:

| Option                            | Description                                                  | Default |
| --------------------------------- | ------------------------------------------------------------ | ------- |
| `-h`, `--help`                    | show this help message and exit                              | —       |
| `-j`, `--json`                    | Emit stable machine-readable JSON                            | `false` |
| `-m YYYYMM`, `--month YYYYMM`     | Limit the operation to one archive month                     | —       |
| `-p PROJECT`, `--project PROJECT` | Select a project by name or alias (default: current project) | —       |
| `-s`, `--show-warnings`           | Show warning-severity diagnostics (hidden by default)        | `false` |

## `sase agent restart`

```text
usage: sase agent restart [-h] [-j] [-m MODEL] [-n] [-y] NAME
```

Stop the named agent and immediately relaunch its stored prompt under the same name. Planning finishes before anything is killed. Restart deletes the previous run's artifacts; the chat transcript is kept. A live agent or a wipe that reaches related agents asks for confirmation unless -y is given; --dry-run prints the preview and exits 0. Exit 0 means restarted or previewed, 2 means refused with nothing changed, and 1 means the old run was stopped but the name wipe or relaunch failed.

Options:

| Option                      | Description                                                                                                                                                                                                                                                                                    | Default |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`           | Print the preview and exit 0 without killing or launching                                                                                                                                                                                                                                      | `false` |
| `-h`, `--help`              | show this help message and exit                                                                                                                                                                                                                                                                | —       |
| `-j`, `--json`              | Emit one stable JSON envelope on stdout and nothing else                                                                                                                                                                                                                                       | `false` |
| `-m MODEL`, `--model MODEL` | Relaunch under a different model. Accepts [provider/]model[@effort], the same spelling %model: accepts. -m opus replaces the model only and leaves a standalone %effort: in place. -m opus@high replaces the model and removes %effort: so the combined directive is the only source of truth. | —       |
| `-y`, `--yes`               | Skip the interactive confirmation for a live agent or a wipe that deletes related agents' artifacts                                                                                                                                                                                            | `false` |

Arguments:

| Argument | Description                  |
| -------- | ---------------------------- |
| `name`   | Name of the agent to restart |

## `sase agent revert`

```text
usage: sase agent revert [-h] name [-Q PATH] [-R PATH]
```

Revert an agent's commits using identifiers from the command line and optional SHA/workspace details from the request sidecar.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument | Description                                 |
| -------- | ------------------------------------------- |
| `name`   | Agent name whose commits should be reverted |

## `sase agent search`

```text
usage: sase agent search [-h] [-j] [-l LIMIT] [-p PROJECT] [QUERY ...]
```

Search the historical agent catalog using the same boolean query dialect as the Agents tab Archive (in:archive). Without an in: token, search keeps the catalog behavior. Use in:inbox for non-dismissed catalog rows or in:archive for the shared dismissed archive corpus.

Options:

| Option                            | Description                                                  | Default |
| --------------------------------- | ------------------------------------------------------------ | ------- |
| `-h`, `--help`                    | show this help message and exit                              | —       |
| `-j`, `--json`                    | Emit a stable machine-readable JSON array                    | `false` |
| `-l LIMIT`, `--limit LIMIT`       | Cap rendered rows; 0 means all (default: 40)                 | —       |
| `-p PROJECT`, `--project PROJECT` | Scope the catalog to one project key, alias, or display name | —       |

Arguments:

| Argument | Description                                             |
| -------- | ------------------------------------------------------- |
| `query`  | Boolean agent-catalog query; may include a limit: token |

## `sase agent show`

```text
usage: sase agent show [-h] NAME
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description               |
| -------- | ------------------------- |
| `name`   | Name of the agent to show |

## `sase agent sync`

```text
usage: sase agent sync [-h] [-a] [-c] [-d] [-j] [-p PROJECT] [-r] [-g] [-m]
                       [-R] [-s] [-e CLASS] [-k KEY] [-l N] [-q] [-t]
                       [-A CURSOR] [-L N]
```

Without flags, pull enabled agents sidecars, publish locally commit-eligible hoods, restore deferred prompt archives, push, and drain publication retries. --check is local and network-free; --check --refresh fetches remote refs before computing ahead/behind.

Options:

| Option                                  | Description                                                                                                                                                                                                                         | Default |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a`, `--apply`                         | With --repair-revisions, write the reported repair to the outbox and audit it; with --repair-states, publish the reported state window; without either, report only and write nothing                                               | `false` |
| `-c`, `--check`                         | Read cached sidecar status and publication diagnostics without network, publication, commit, or push                                                                                                                                | `false` |
| `-d`, `--drop-retired`                  | Drop publication requests that were retired as unpublishable, reporting how many were dropped and why                                                                                                                               | `false` |
| `-h`, `--help`                          | show this help message and exit                                                                                                                                                                                                     | —       |
| `-j`, `--json`                          | Emit stable machine-readable JSON instead of a colored table                                                                                                                                                                        | `false` |
| `-p PROJECT`, `--project PROJECT`       | Limit to a project name or alias (repeatable)                                                                                                                                                                                       | —       |
| `-r`, `--refresh`                       | With --check, fetch remote refs before computing sidecar ahead/behind counts                                                                                                                                                        | `false` |
| `-g`, `--repair-digests`                | Re-sign locally owned hood-snapshot file references that have drifted from their on-disk payload, instead of running a normal sync                                                                                                  | `false` |
| `-m`, `--repair-manifest`               | Restore missing owner-manifest hoods and normalize verified stale explicit file lists, instead of running a normal sync                                                                                                             | `false` |
| `-R`, `--repair-revisions`              | Map stale pre-commit outbox revisions to the agent's committed revision or linked scope, reporting by default and writing only with --apply; runs one project per call                                                              | `false` |
| `-s`, `--repair-states`                 | Report a bounded window of already-published runs whose terminal state drifted from local evidence, reporting by default and publishing only with --apply; runs one project per call                                                | `false` |
| `-e CLASS`, `--retry-error-class CLASS` | With --retry-limit, select stopped requests with this error class; repeat to accept several classes (choices: `index_lock`, `lock_busy`, `manifest_mismatch`, `other`, `rebase_conflict`, `timeout`, `unknown`, `unstaged_changes`) | —       |
| `-k KEY`, `--retry-key KEY`             | Retry exactly one hood request identified as GLOBAL_AGENT@REVISION using the full outbox SHA; requires --retry-limit 1, exactly one --project, and --retry-quarantined or --retry-retired                                           | —       |
| `-l N`, `--retry-limit N`               | Retry at most N distinct hood requests for exactly one project without full reconciliation; requires --retry-quarantined or --retry-retired                                                                                         | —       |
| `-q`, `--retry-quarantined`             | Clear quarantined requests for full sync; with --retry-limit, select a bounded hood-request batch                                                                                                                                   | `false` |
| `-t`, `--retry-retired`                 | Revive this project's retired hood requests for full reconciliation, or select a bounded batch with --retry-limit; requires --project                                                                                               | `false` |
| `-A CURSOR`, `--state-after CURSOR`     | Resume a state repair pass after this report's opaque cursor; only valid with --repair-states and empty to start a pass                                                                                                             | —       |
| `-L N`, `--state-limit N`               | Examine at most N published runs per state repair report across at most five hoods (1-500, default 100); only valid with --repair-states                                                                                            | —       |

## `sase agent tab`

```text
usage: sase agent tab [-h] {list,set,unset} ...
```

Move an agent's whole presentation root between Agents-tab placements. With no subcommand, `sase agent tab` defaults to `sase agent tab list`.

Bare `sase agent tab` defaults to `sase agent tab list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand             | Summary                                                   |
| ---------------------- | --------------------------------------------------------- |
| `sase agent tab list`  | Print the local agent-tab catalog with root counts        |
| `sase agent tab set`   | Move an agent's presentation root onto a named tab        |
| `sase agent tab unset` | Move an agent's presentation root back to the default tab |

### `sase agent tab list`

```text
usage: sase agent tab list [-h] [-n NAME] [-j]
```

Options:

| Option                   | Description                                    | Default |
| ------------------------ | ---------------------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit                | —       |
| `-j`, `--json`           | Emit a stable, machine-readable JSON envelope  | `false` |
| `-n NAME`, `--name NAME` | Limit output to the tab holding a single agent | —       |

### `sase agent tab set`

```text
usage: sase agent tab set [-h] -n NAME -t TAB
```

Options:

| Option                   | Description                                               | Default |
| ------------------------ | --------------------------------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit                           | —       |
| `-n NAME`, `--name NAME` | Name of the agent to move (required)                      | —       |
| `-t TAB`, `--tab TAB`    | Destination tab name (canonicalized like %tab) (required) | —       |

### `sase agent tab unset`

```text
usage: sase agent tab unset [-h] -n NAME
```

Options:

| Option                   | Description                                                  | Default |
| ------------------------ | ------------------------------------------------------------ | ------- |
| `-h`, `--help`           | show this help message and exit                              | —       |
| `-n NAME`, `--name NAME` | Name of the agent to move back to the default tab (required) | —       |

## `sase agent tribe`

```text
usage: sase agent tribe [-h] {list,set,unset} ...
```

Bare `sase agent tribe` defaults to `sase agent tribe list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand               | Summary                                                  |
| ------------------------ | -------------------------------------------------------- |
| `sase agent tribe list`  | Print tribes as JSON (all agents, or filtered by --name) |
| `sase agent tribe set`   | Set the tribe on an agent (replaces any previous tribe)  |
| `sase agent tribe unset` | Clear the tribe on an agent                              |

### `sase agent tribe list`

```text
usage: sase agent tribe list [-h] [-n NAME]
```

Options:

| Option                   | Description                     | Default |
| ------------------------ | ------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit | —       |
| `-n NAME`, `--name NAME` | Limit output to a single agent  | —       |

### `sase agent tribe set`

```text
usage: sase agent tribe set [-h] -n NAME -t TRIBE
```

Options:

| Option                      | Description                                       | Default |
| --------------------------- | ------------------------------------------------- | ------- |
| `-h`, `--help`              | show this help message and exit                   | —       |
| `-n NAME`, `--name NAME`    | Name of the agent to assign to a tribe (required) | —       |
| `-t TRIBE`, `--tribe TRIBE` | Tribe name (without '@') (required)               | —       |

### `sase agent tribe unset`

```text
usage: sase agent tribe unset [-h] -n NAME
```

Options:

| Option                   | Description                                           | Default |
| ------------------------ | ----------------------------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit                       | —       |
| `-n NAME`, `--name NAME` | Name of the agent to remove from its tribe (required) | —       |

## `sase agent wait`

```text
usage: sase agent wait [-h] [-a] [-i DURATION] [-j] [-p NAME] [-q]
                       [-t DURATION] [-w] [NAME ...]
```

Block until the agents you name (or every agent running right now, with -a) reach a terminal state, then exit with a status code that says what happened. NAME is resolved the same way %wait resolves it: clan, then agent session, then workflow, then exact agent name. Exit codes: 0 every target succeeded, 1 at least one failed, 2 a usage error, 3 at least one target is blocked on a human (without -w), 4 the timeout expired, 130/143 interrupted by SIGINT/SIGTERM. Precedence when more than one applies: 1 > 3 > 4. Progress goes to stderr; the settle summary and the -j envelope go to stdout.

Options:

| Option                               | Description                                                         | Default |
| ------------------------------------ | ------------------------------------------------------------------- | ------- |
| `-a`, `--all`                        | Wait for every agent running when the command starts (rejects NAME) | `false` |
| `-h`, `--help`                       | show this help message and exit                                     | —       |
| `-i DURATION`, `--interval DURATION` | Fixed poll interval, e.g. 90, 90s, 45m, 2h (default: adaptive)      | —       |
| `-j`, `--json`                       | Emit one JSON envelope on settle; suppresses progress output        | `false` |
| `-p NAME`, `--project NAME`          | Limit --all targets, and scope name resolution, to one project      | —       |
| `-q`, `--quiet`                      | Suppress progress; print only the final summary line                | `false` |
| `-t DURATION`, `--timeout DURATION`  | Give up after DURATION, e.g. 90, 90s, 45m, 2h (default: no timeout) | —       |
| `-w`, `--wait-blocked`               | Keep waiting through pauses that need a human instead of exiting 3  | `false` |

Arguments:

| Argument | Description                                                           |
| -------- | --------------------------------------------------------------------- |
| `names`  | Agent, agent session, clan, or workflow name to wait for (repeatable) |

Related: [CLI command groups](index.md).
