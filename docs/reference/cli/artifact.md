---
title: "sase artifact"
description: "Create, discover, inspect, resolve, open, and repair indexed artifacts."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase artifact

Create, discover, inspect, resolve, open, and repair artifacts

Aliases: `sase artifact-file`.

Reference for `sase artifact`. Run `sase artifact --help` for the exact output on this checkout.

```text
usage: sase artifact [-h]
                     {create,doctor,link,list,open,pane,path,prune,prune-runs,read,reclaim,show,stats,trash} ...
```

Create, discover, inspect, resolve, open, and repair indexed artifacts. Bare `sase artifact` defaults to `sase artifact list`. `sase artifact link` writes typed edges; `sase artifact read` prints an artifact and records the read. Canonical prompt archives live in the agents sidecar and are inspected with `sase agent prompts`.

Bare `sase artifact` defaults to `sase artifact list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                 | Summary                                                         |
| -------------------------- | --------------------------------------------------------------- |
| `sase artifact create`     | Store a file as an explicit artifact for the current agent      |
| `sase artifact doctor`     | Inspect, repair, and verify the artifact index                  |
| `sase artifact link`       | Add, list, remove, and suggest typed artifact links             |
| `sase artifact list`       | List indexed artifacts (pretty table by default, JSON with -j)  |
| `sase artifact open`       | Open a resolved artifact reference with an appropriate viewer   |
| `sase artifact pane`       | Inspect compiled Artifacts pane contracts and capabilities      |
| `sase artifact path`       | Print the absolute filesystem path for an artifact reference    |
| `sase artifact prune`      | Plan retention and optionally move selected rows to trash       |
| `sase artifact prune-runs` | Plan retention and optionally remove old ace-run directories    |
| `sase artifact read`       | Print an artifact after recording an audited read               |
| `sase artifact reclaim`    | Replace stored automatic rows with verified VCS references      |
| `sase artifact show`       | Show artifact metadata, resolution details, and consumption     |
| `sase artifact stats`      | Report artifact-store economics and default retention selection |
| `sase artifact trash`      | List, permanently purge, or restore artifact trash              |

## `sase artifact create`

```text
usage: sase artifact create [-h] [-b [ID]]
                            [-k {chat,plan,image,markdown,pdf,file}]
                            [-l LABEL] [-m] -p PATH
```

Store a file as an explicit artifact for the current agent. On success prints: id: <explicit id> source: <absolute source path> path: <stored snapshot path> ref: file:<explicit id> var: artifacts[<index>] bead: <id> (only with --bead) The artifact is also recorded in the agent's `artifacts` output variable (shown in the Agents tab OUTPUT VARIABLES section, readable with `sase var get` from inside the agent and by later agents as `{{ agents["<name>"].artifacts }}`). Re-registering the same label and source replaces that entry with the newer snapshot.

Options:

| Option                      | Description                                                                                                          | Default |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------- |
| `-b ID`, `--bead ID`        | Attach the new file: reference to a bead (default when bare: the agent's SASE_BEAD_ID bead)                          | —       |
| `-h`, `--help`              | show this help message and exit                                                                                      | —       |
| `-k KIND`, `--kind KIND`    | Artifact kind (default: infer from the file extension) (choices: `chat`, `file`, `image`, `markdown`, `pdf`, `plan`) | —       |
| `-l LABEL`, `--label LABEL` | Display label (default: source file name)                                                                            | —       |
| `-m`, `--move`              | Remove the source file after storing it (default: copy)                                                              | `false` |
| `-p PATH`, `--path PATH`    | Source file to copy into durable artifact storage (required)                                                         | —       |

## `sase artifact doctor`

```text
usage: sase artifact doctor [-h] [-f] [-v]
```

Inspect, repair, and verify the artifact index. Exits 1 when the index is unhealthy. Byte-free version-control-backed rows are healthy, not missing: VCS reference rows how many rows carry provenance instead of stored bytes Incomplete VCS provenance rows with a partial vcs_repo / vcs_sha / vcs_relpath triple Unresolvable VCS references rows --verify could not materialize from any checkout Also reports dangling link rows, stale Links tables, missing companions, and rendered blocks whose links/ JSON is not in HEAD. --fix rebuilds the aggregate and projections from truth; it never parses Markdown for state.

Options:

| Option           | Description                                                                          | Default |
| ---------------- | ------------------------------------------------------------------------------------ | ------- |
| `-f`, `--fix`    | Backfill missing enrichment fields before inspecting                                 | `false` |
| `-h`, `--help`   | show this help message and exit                                                      | —       |
| `-v`, `--verify` | Re-hash live stored files and materialize VCS-backed rows to verify recorded digests | `false` |

## `sase artifact link`

```text
usage: sase artifact link [-h]
                          {add,import-indexes,list,migrate-notes,relation,rm,suggest} ...
```

Typed, bidirectional artifact links. Bare `sase artifact link` defaults to `sase artifact link list`. `add` always takes an explicit source ref, a closed-registry relation, a target ref, and a one-line why. `blocks` and `depends-on` error with a pointer to `sase bead dep`. `suggest` prints hard-evidence candidates and writes nothing.

Bare `sase artifact link` defaults to `sase artifact link list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                          | Summary                                                         |
| ----------------------------------- | --------------------------------------------------------------- |
| `sase artifact link add`            | Add or rewrite one typed artifact link                          |
| `sase artifact link import-indexes` | Import legacy links/ indexes into immutable link events         |
| `sase artifact link list`           | List artifact links (pretty table by default, JSON with -j)     |
| `sase artifact link migrate-notes`  | Dry-run RELATED: bead-note migration (apply writes bead events) |
| `sase artifact link relation`       | Read the closed relation registry                               |
| `sase artifact link rm`             | Remove typed artifact links between a pair                      |
| `sase artifact link suggest`        | Suggest missing links from hard evidence without writing rows   |

### `sase artifact link add`

```text
usage: sase artifact link add [-h] SOURCE RELATION TARGET WHY
```

Add one typed link. Unchanged edges print `unchanged` and exit 0. Refs accept a leading `@`. The source ref is always required; do not default it to the current agent.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument     | Description                                                                   |
| ------------ | ----------------------------------------------------------------------------- |
| `source_ref` | Source artifact reference (leading @ is optional)                             |
| `relation`   | Closed-registry relation slug (related, supersedes, implements, derives-from) |
| `target_ref` | Target artifact reference (leading @ is optional)                             |
| `why`        | Single-line description, max 240 characters                                   |

### `sase artifact link import-indexes`

```text
usage: sase artifact link import-indexes [-h] [-a] [-j] [ATTESTATION]
```

Plan or apply the legacy artifact-link index cutover. Preview is the default and writes nothing. Applying requires the positional attestation token printed by preview, fences current SASE binaries with link-events/STORE.json, publishes one deterministic baseline import event to every document sidecar root, and then marks legacy links/ indexes imported. Older SASE binaries do not understand the marker.

Options:

| Option          | Description                                                             | Default |
| --------------- | ----------------------------------------------------------------------- | ------- |
| `-a`, `--apply` | Write cutover markers, baseline event objects, and aggregate projection | `false` |
| `-h`, `--help`  | show this help message and exit                                         | —       |
| `-j`, `--json`  | Emit a machine-readable import report                                   | `false` |

Arguments:

| Argument      | Description                                                         |
| ------------- | ------------------------------------------------------------------- |
| `attestation` | Fleet capability token printed by preview and required with --apply |

### `sase artifact link list`

```text
usage: sase artifact link list [-h] [-d {both,in,out}] [-j] [-l N] [-o ORIGIN]
                               [-R RELATION] [-s {index,store}]
                               [reference]
```

List links. Without a ref, show the current project's recent links (default limit 50, newest first). With a ref, show that artifact's neighborhood.

Options:

| Option                                  | Description                                                                                           | Default |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------- |
| `-d DIRECTION`, `--direction DIRECTION` | Neighborhood direction (default: both) (choices: `both`, `in`, `out`)                                 | `both`  |
| `-h`, `--help`                          | show this help message and exit                                                                       | —       |
| `-j`, `--json`                          | Emit a machine-readable JSON array (stable schema)                                                    | `false` |
| `-l N`, `--limit N`                     | Maximum rows to return (default: 50; 0 means unlimited)                                               | `50`    |
| `-o ORIGIN`, `--origin ORIGIN`          | Only show this origin (manual, migrated, prompt_ref, read, derived)                                   | —       |
| `-R RELATION`, `--relation RELATION`    | Only show this relation slug                                                                          | —       |
| `-s SOURCE`, `--source SOURCE`          | Read from the machine-local index or durable store truth (default: index) (choices: `index`, `store`) | `index` |

Arguments:

| Argument    | Description                                            |
| ----------- | ------------------------------------------------------ |
| `reference` | Optional artifact reference whose neighborhood to show |

### `sase artifact link migrate-notes`

```text
usage: sase artifact link migrate-notes [-h] [-a] [-j]
```

Scan bead notes matching `RELATED: <id> — <why>` and plan `related` edges with origin `migrated`. Dry-run by default. `--apply` writes bead link events and appends `MIGRATED:` notes immediately.

Options:

| Option          | Description                            | Default |
| --------------- | -------------------------------------- | ------- |
| `-a`, `--apply` | Write bead events and MIGRATED: notes  | `false` |
| `-h`, `--help`  | show this help message and exit        | —       |
| `-j`, `--json`  | Emit a machine-readable migration plan | `false` |

### `sase artifact link relation`

```text
usage: sase artifact link relation [-h] {list,show} ...
```

Read the closed-registry relation vocabulary: direction, worked examples, and recommended endpoint kinds. Bare `sase artifact link relation` defaults to `list`.

Bare `sase artifact link relation` defaults to `sase artifact link relation list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                         | Summary                                                               |
| ---------------------------------- | --------------------------------------------------------------------- |
| `sase artifact link relation list` | List every relation in the closed registry                            |
| `sase artifact link relation show` | Show one relation's direction, worked examples, and recommended kinds |

#### `sase artifact link relation list`

```text
usage: sase artifact link relation list [-h] [-j]
```

Options:

| Option         | Description                                        | Default |
| -------------- | -------------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                    | —       |
| `-j`, `--json` | Emit a machine-readable JSON array (stable schema) | `false` |

#### `sase artifact link relation show`

```text
usage: sase artifact link relation show [-h] [-j] SLUG
```

Options:

| Option         | Description                                         | Default |
| -------------- | --------------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                     | —       |
| `-j`, `--json` | Emit a machine-readable JSON object (stable schema) | `false` |

Arguments:

| Argument | Description                                                        |
| -------- | ------------------------------------------------------------------ |
| `slug`   | Relation slug (related, supersedes, implements, derives-from, ...) |

### `sase artifact link rm`

```text
usage: sase artifact link rm [-h] [-R RELATION] SOURCE TARGET
```

Remove stored edges between two artifacts. Without -R/--relation, every edge between the pair is removed. Refs accept a leading `@`.

Options:

| Option                               | Description                                                           | Default |
| ------------------------------------ | --------------------------------------------------------------------- | ------- |
| `-h`, `--help`                       | show this help message and exit                                       | —       |
| `-R RELATION`, `--relation RELATION` | Only remove this relation slug (default: every edge between the pair) | —       |

Arguments:

| Argument     | Description                                            |
| ------------ | ------------------------------------------------------ |
| `source_ref` | One endpoint of the pair (leading @ is optional)       |
| `target_ref` | The other endpoint of the pair (leading @ is optional) |

### `sase artifact link suggest`

```text
usage: sase artifact link suggest [-h] [-j] [-l N] [reference]
```

Suggest missing artifact links from hard evidence only: shared beads, shared epics, overlapping read sets, read-log candidates, and deterministic filename lineage. Suggestions are ephemeral; the command never writes store rows or companion files.

Options:

| Option              | Description                                                    | Default |
| ------------------- | -------------------------------------------------------------- | ------- |
| `-h`, `--help`      | show this help message and exit                                | —       |
| `-j`, `--json`      | Emit a machine-readable JSON array (stable schema)             | `false` |
| `-l N`, `--limit N` | Maximum suggestions to return (default: 50; 0 means unlimited) | `50`    |

Arguments:

| Argument    | Description                                                   |
| ----------- | ------------------------------------------------------------- |
| `reference` | Optional artifact reference whose suggestions should be shown |

## `sase artifact list`

```text
usage: sase artifact list [-h] [-a AGENT] [-e] [-j]
                          [-k {chat,plan,image,markdown,pdf,file}] [-l LIMIT]
                          [-p PROJECT] [-q QUERY] [-s DATE] [-u]
```

Options:

| Option                            | Description                                                                                             | Default |
| --------------------------------- | ------------------------------------------------------------------------------------------------------- | ------- |
| `-a AGENT`, `--agent AGENT`       | Only show artifacts associated with this agent name                                                     | —       |
| `-e`, `--explicit`                | Only show explicitly created artifacts                                                                  | `false` |
| `-h`, `--help`                    | show this help message and exit                                                                         | —       |
| `-j`, `--json`                    | Emit a machine-readable JSON array (stable schema)                                                      | `false` |
| `-k KIND`, `--kind KIND`          | Only show this artifact kind (repeatable) (choices: `chat`, `file`, `image`, `markdown`, `pdf`, `plan`) | —       |
| `-l LIMIT`, `--limit LIMIT`       | Maximum artifacts to return (default: 50; 0 means unlimited)                                            | `50`    |
| `-p PROJECT`, `--project PROJECT` | Only show a project by display name, alias, or canonical key                                            | —       |
| `-q QUERY`, `--query QUERY`       | Case-insensitive substring filter over label and paths                                                  | —       |
| `-s DATE`, `--since DATE`         | Only show artifacts created on or after DATE                                                            | —       |
| `-u`, `--unused`                  | Only show artifacts no agent has ever referenced                                                        | `false` |

## `sase artifact open`

```text
usage: sase artifact open [-h] reference
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument    | Description                                             |
| ----------- | ------------------------------------------------------- |
| `reference` | Artifact reference or a bare default:/explicit: file id |

## `sase artifact pane`

```text
usage: sase artifact pane [-h] {show} ...
```

Inspect compiled Artifacts pane contracts. Capabilities are derived from declared facts by named host rules. Unknown pane ids fail and list the configured ids. They never fall back to another pane.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                | Summary                                                      |
| ------------------------- | ------------------------------------------------------------ |
| `sase artifact pane show` | Explain one pane's compiled contract and capability verdicts |

### `sase artifact pane show`

```text
usage: sase artifact pane show [-h] [-j] pane_id
```

Show the compiled Artifacts pane contract and every closed capability as ON or OFF with its named rule, declared fact, and suppression reason.

Options:

| Option         | Description                                    | Default |
| -------------- | ---------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                | —       |
| `-j`, `--json` | Emit one machine-readable contract explanation | `false` |

Arguments:

| Argument  | Description                                                     |
| --------- | --------------------------------------------------------------- |
| `pane_id` | Configured Artifacts pane id (for example stitches or ref:plan) |

## `sase artifact path`

```text
usage: sase artifact path [-h] reference
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument    | Description                                             |
| ----------- | ------------------------------------------------------- |
| `reference` | Artifact reference or a bare default:/explicit: file id |

## `sase artifact prune`

```text
usage: sase artifact prune [-h] [-a] [-b DATE] [-g N] [-j]
                           [-k {chat,plan,image,markdown,pdf,file}] [-l N]
                           [-m BYTES] [-p PROJECT]
```

Plan removal of old automatic artifact captures. This command is a dry run unless --apply is passed; explicit, referenced, and consumed artifacts and every label's newest generation are protected.

Options:

| Option                            | Description                                                                                           | Default |
| --------------------------------- | ----------------------------------------------------------------------------------------------------- | ------- |
| `-a`, `--apply`                   | Move planned rows into restorable trash                                                               | `false` |
| `-b DATE`, `--before DATE`        | Require selected rows to be older than DATE (YYYY-MM-DD, YYYY-MM, YYYYMM, or relative 14d / 3w / 2m)  | —       |
| `-h`, `--help`                    | show this help message and exit                                                                       | —       |
| `-j`, `--json`                    | Emit one machine-readable plan and execution envelope                                                 | `false` |
| `-g N`, `--keep-generations N`    | Keep the newest N captures per label (default: artifacts.retention.keep_per_label)                    | —       |
| `-k KIND`, `--kind KIND`          | Require this artifact kind (repeatable) (choices: `chat`, `file`, `image`, `markdown`, `pdf`, `plan`) | —       |
| `-l N`, `--limit N`               | Maximum rows to select (0 means unlimited)                                                            | —       |
| `-m BYTES`, `--min-size BYTES`    | Require at least this many stored bytes                                                               | —       |
| `-p PROJECT`, `--project PROJECT` | Only prune a project by display name, alias, or canonical key                                         | —       |

## `sase artifact prune-runs`

```text
usage: sase artifact prune-runs [-h] [-a] [-i INDEX_PATH] [-j] [-m N] [-l N]
                                [-p PROJECT] [-r PROJECTS_ROOT]
```

Plan removal of old per-run ace-run artifact directories and empty out-of-range month/day shards. This command is a dry run unless --apply is passed; recent months, referenced agents, incomplete runs, and runs tied to non-closed beads are protected.

Options:

| Option                                              | Description                                                                                   | Default |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------- |
| `-a`, `--apply`                                     | Remove selected run directories and empty out-of-range shards                                 | `false` |
| `-h`, `--help`                                      | show this help message and exit                                                               | —       |
| `-i INDEX_PATH`, `--index-path INDEX_PATH`          | Agent artifact SQLite index to de-index after deletion                                        | —       |
| `-j`, `--json`                                      | Emit one machine-readable plan and execution envelope                                         | `false` |
| `-m N`, `--keep-recent-months N`                    | Keep the newest N calendar months whole (default: artifacts.retention.keep_recent_run_months) | —       |
| `-l N`, `--limit N`                                 | Maximum run directories to select (0 means unlimited)                                         | —       |
| `-p PROJECT`, `--project PROJECT`                   | Only prune a project by display name, alias, or canonical key                                 | —       |
| `-r PROJECTS_ROOT`, `--projects-root PROJECTS_ROOT` | SASE projects root to scan (default: ~/.sase/projects)                                        | —       |

## `sase artifact read`

```text
usage: sase artifact read [-h] [-f {json,markdown,rich}] [-n LINES]
                          reference reason
```

Resolve an artifact reference, strip leading frontmatter and managed Links / Referenced By tables, print the body, and record an audited read. A non-empty reason is required (positional). Markdown prints to stdout; a TTY pages, a pipe stays raw. Images, PDFs, and video print a metadata card and point at `sase artifact open`. `stitch:` prints the show payload plus the commit subject. The read is refused if the audit row cannot be recorded. Inside a SASE agent run with an identity, a `read` graph edge is also stored. `show`, `path`, and `open` stay silent.

Options:

| Option                         | Description                                                             | Default    |
| ------------------------------ | ----------------------------------------------------------------------- | ---------- |
| `-f FORMAT`, `--format FORMAT` | Output format (default: markdown) (choices: `json`, `markdown`, `rich`) | `markdown` |
| `-h`, `--help`                 | show this help message and exit                                         | —          |
| `-n LINES`, `--lines LINES`    | Print only the first LINES of stripped text                             | —          |

Arguments:

| Argument    | Description                                             |
| ----------- | ------------------------------------------------------- |
| `reference` | Artifact reference or a bare default:/explicit: file id |
| `reason`    | Why this artifact is being read (required, non-empty)   |

## `sase artifact reclaim`

```text
usage: sase artifact reclaim [-h] [-a] [-d N] [-j] [-l N] [-p PROJECT]
```

Find automatic artifact rows whose exact bytes are reproducible from durable remote-tracking history. This command is a dry run unless --apply is passed. Applied bytes move to restorable trash and consume disk space until that trash is purged. Explicit, referenced, and consumed artifacts are protected.

Options:

| Option                            | Description                                                     | Default |
| --------------------------------- | --------------------------------------------------------------- | ------- |
| `-a`, `--apply`                   | Write VCS-backed rows and move redundant stored bytes to trash  | `false` |
| `-h`, `--help`                    | show this help message and exit                                 | —       |
| `-j`, `--json`                    | Emit one machine-readable plan and execution envelope           | `false` |
| `-l N`, `--limit N`               | Maximum verified rows to convert (0 means unlimited)            | —       |
| `-d N`, `--max-history-scan N`    | Maximum durable commits to inspect per path (default: 100)      | `100`   |
| `-p PROJECT`, `--project PROJECT` | Only reclaim a project by display name, alias, or canonical key | —       |

## `sase artifact show`

```text
usage: sase artifact show [-h] [-j] reference
```

Show artifact metadata, reference-resolution details, and the recorded consumption summary.

Options:

| Option         | Description                                   | Default |
| -------------- | --------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit               | —       |
| `-j`, `--json` | Emit one machine-readable resolution envelope | `false` |

Arguments:

| Argument    | Description                                             |
| ----------- | ------------------------------------------------------- |
| `reference` | Artifact reference or a bare default:/explicit: file id |

## `sase artifact stats`

```text
usage: sase artifact stats [-h] [-j] [-p PROJECT] [-t N]
```

Report artifact-store economics, durable-reference and consumption protections, trash occupancy, and what the default retention policy would select. This command is read-only.

Options:

| Option                            | Description                                                    | Default |
| --------------------------------- | -------------------------------------------------------------- | ------- |
| `-h`, `--help`                    | show this help message and exit                                | —       |
| `-j`, `--json`                    | Emit one machine-readable statistics envelope                  | `false` |
| `-p PROJECT`, `--project PROJECT` | Only report a project by display name, alias, or canonical key | —       |
| `-t N`, `--top N`                 | Maximum agent groups to show (default: 10)                     | `10`    |

## `sase artifact trash`

```text
usage: sase artifact trash [-h] {list,purge,restore} ...
```

Manage restorable artifact trash. Bare `sase artifact trash` defaults to `sase artifact trash list`.

Bare `sase artifact trash` defaults to `sase artifact trash list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                    | Summary                                                  |
| ----------------------------- | -------------------------------------------------------- |
| `sase artifact trash list`    | List restorable trash entries                            |
| `sase artifact trash purge`   | Permanently delete trash entries past the grace period   |
| `sase artifact trash restore` | Restore one trash entry's payload and complete index row |

### `sase artifact trash list`

```text
usage: sase artifact trash list [-h] [-j] [-l N]
```

Options:

| Option              | Description                                              | Default |
| ------------------- | -------------------------------------------------------- | ------- |
| `-h`, `--help`      | show this help message and exit                          | —       |
| `-j`, `--json`      | Emit one machine-readable trash listing                  | `false` |
| `-l N`, `--limit N` | Maximum entries to show (default: 50; 0 means unlimited) | `50`    |

### `sase artifact trash purge`

```text
usage: sase artifact trash purge [-h] [-a] [-j]
```

Permanently delete trash entries. This is the only irreversible artifact operation: purged entries cannot be restored. Without --all, only entries older than artifacts.retention.trash_grace_days are deleted.

Options:

| Option         | Description                                                | Default |
| -------------- | ---------------------------------------------------------- | ------- |
| `-a`, `--all`  | Ignore the grace period and permanently delete every entry | `false` |
| `-h`, `--help` | show this help message and exit                            | —       |
| `-j`, `--json` | Emit one machine-readable purge result                     | `false` |

### `sase artifact trash restore`

```text
usage: sase artifact trash restore [-h] [-j] reference
```

Options:

| Option         | Description                              | Default |
| -------------- | ---------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit          | —       |
| `-j`, `--json` | Emit one machine-readable restore result | `false` |

Arguments:

| Argument    | Description                               |
| ----------- | ----------------------------------------- |
| `reference` | Trash entry id or file artifact reference |

Related: [CLI command groups](index.md).
