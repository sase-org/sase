---
title: "sase bead"
description: "Lightweight git-native issue tracking"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase bead

Lightweight git-native issue tracking

Reference for `sase bead`. Run `sase bead --help` for the exact output on this checkout.

```text
usage: sase bead [-h]
                 {+1,apply-status,attach,attachment,blocked,close,create,dep,doctor,epic-symbols,export,history,init,list,note,onboard,open,pages,read,ready,ref,resolve-conflicts,rm,search,show,snooze,stats,sync,sync-external,task-type,touched,update,work} ...
```

Bare `sase bead` defaults to `sase bead list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                    | Summary                                                                          |
| ----------------------------- | -------------------------------------------------------------------------------- |
| `sase bead +1`                | Corroborate an existing task with independent evidence                           |
| `sase bead apply-status`      | Set one bead's status through the bead store mutation path                       |
| `sase bead attach`            | Attach file snapshots to a bead note                                             |
| `sase bead attachment`        | List, open, path, prune, publish, purge, push, or unpublish attachment snapshots |
| `sase bead blocked`           | Show blocked issues                                                              |
| `sase bead close`             | Close one or more issues                                                         |
| `sase bead create`            | Create a new issue                                                               |
| `sase bead dep`               | Inspect and manage dependencies                                                  |
| `sase bead doctor`            | Validate bead-store health, design links, and artifact references                |
| `sase bead epic-symbols`      | List Justfile --epic-symbol whitelist entries                                    |
| `sase bead export`            | Export current bead state to issues.jsonl                                        |
| `sase bead history`           | Show event history or find overwritten notes                                     |
| `sase bead init`              | Create the effective SDD bead store                                              |
| `sase bead list`              | List issues                                                                      |
| `sase bead note`              | Append, edit, or retract an attributed note entry                                |
| `sase bead onboard`           | Show quick-start guide                                                           |
| `sase bead open`              | Reopen an issue                                                                  |
| `sase bead pages`             | Refresh generated bead pages or print a page URL                                 |
| `sase bead read`              | Read one or more beads after recording an audited read                           |
| `sase bead ready`             | Show unblocked task beads awaiting triage                                        |
| `sase bead ref`               | Inspect and manage artifact references                                           |
| `sase bead resolve-conflicts` | Resolve mechanical git conflicts in sdd/beads event streams                      |
| `sase bead rm`                | Remove issues and all their children                                             |
| `sase bead search`            | Search issues by text                                                            |
| `sase bead show`              | Show one or more issues                                                          |
| `sase bead snooze`            | Defer a task bead until a wake time or a +1 threshold                            |
| `sase bead stats`             | Show project statistics                                                          |
| `sase bead sync`              | Sync with git                                                                    |
| `sase bead sync-external`     | Mirror external tracker issues into task beads                                   |
| `sase bead task-type`         | Inspect the effective task-type catalog                                          |
| `sase bead touched`           | List beads one agent touched                                                     |
| `sase bead update`            | Update one or more issues                                                        |
| `sase bead work`              | Create or launch one or more epic plan or task bead targets                      |

## `sase bead +1`

```text
usage: sase bead +1 [-h] id [-a NAME] -n TEXT [-R REF] [-S] [-L] [-K] [-W]
                    [-y] [--verified-after-close]
```

Record one independently attributed report on an existing task bead. Each reporter counts at most once; later details belong in `sase bead note`. Draft tasks promote to ready; closed tasks promote only when the report's observation window starts after the current close.

Options:

| Option                     | Description                                                                                                                                                                     | Default |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-S`, `--allow-sensitive`  | Attach files from sensitive paths                                                                                                                                               | `false` |
| `-a NAME`, `--author NAME` | Reporter recorded on the evidence (default: current agent, else owner)                                                                                                          | —       |
| `-h`, `--help`             | show this help message and exit                                                                                                                                                 | —       |
| `-L`, `--local-only`       | Keep new attachments on this machine without uploading                                                                                                                          | `false` |
| `-n TEXT`, `--note TEXT`   | Required independent reproduction or impact evidence; @<path> reads it from that file, @@ escapes a literal leading @ (required)                                                | —       |
| `-K`, `--private`          | Store new attachments privately                                                                                                                                                 | `false` |
| `-W`, `--public`           | Request public attachments (needs confirmation)                                                                                                                                 | `false` |
| `-R REF`, `--ref REF`      | Artifact reference supporting the evidence (repeatable)                                                                                                                         | —       |
| `--verified-after-close`   | Assert this was reproduced on a tree that already contains the close, so the observation window is now instead of this runtime's start. Requires the bead to already be closed. | `false` |
| `-y`, `--yes`              | Confirm a human public widening without a prompt                                                                                                                                | `false` |

Arguments:

| Argument | Description                    |
| -------- | ------------------------------ |
| `id`     | Full or shorthand task bead ID |

## `sase bead apply-status`

```text
usage: sase bead apply-status [-h] bead_id status [-Q PATH] [-R PATH]
```

Apply a status update to one bead. The bead id and status are positional. When run as a durable proc, the typed result is written to the configured result sidecar.

Options:

| Option                           | Description                                                                                                             | Default |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                   | show this help message and exit                                                                                         | —       |
| `-Q PATH`, `--request-path PATH` | Private versioned operation request sidecar. Defaults to $SASE_PROC_REQUEST_PATH when that environment variable is set. | —       |
| `-R PATH`, `--result-path PATH`  | Private versioned typed result sidecar. Defaults to $SASE_PROC_RESULT_PATH when that environment variable is set.       | —       |

Arguments:

| Argument  | Description               |
| --------- | ------------------------- |
| `bead_id` | Full or shorthand bead id |
| `status`  | New bead status           |

## `sase bead attach`

```text
usage: sase bead attach [-h] id FILE [FILE ...] [-a NAME] [-n TEXT] [-N NAME]
                        [-S] [-L] [-K] [-W] [-y]
```

Attach snapshots of files to a bead as a new attributed note. The bead keeps the exact bytes on every machine, even after the file is gone. Use - to read one attachment from stdin (with -N/--name).

Options:

| Option                     | Description                                                                                | Default |
| -------------------------- | ------------------------------------------------------------------------------------------ | ------- |
| `-S`, `--allow-sensitive`  | Attach files from sensitive paths                                                          | `false` |
| `-a NAME`, `--author NAME` | Author recorded on the entry (default: current agent, else store owner)                    | —       |
| `-h`, `--help`             | show this help message and exit                                                            | —       |
| `-L`, `--local-only`       | Keep new attachments on this machine without uploading                                     | `false` |
| `-N NAME`, `--name NAME`   | Attachment name; valid only with one file, and required when the file is - (stdin)         | —       |
| `-n TEXT`, `--note TEXT`   | Optional prose stored above the attachment tokens; @<path> references inside it attach too | —       |
| `-K`, `--private`          | Store new attachments privately                                                            | `false` |
| `-W`, `--public`           | Request public attachments (needs confirmation)                                            | `false` |
| `-y`, `--yes`              | Confirm a human public widening without a prompt                                           | `false` |

Arguments:

| Argument | Description                                              |
| -------- | -------------------------------------------------------- |
| `id`     | Full or shorthand issue ID                               |
| `files`  | Files to attach; use - to read one attachment from stdin |

## `sase bead attachment`

```text
usage: sase bead attachment [-h]
                            {list,open,path,prune,publish,purge,push,unpublish} ...
```

List content-addressed attachment snapshots on a bead, open one in the terminal viewer, print the absolute local view path for one attachment, publish one note attachment to the public store, unpublish one note attachment back to private, push queued uploads to the shared store, purge one attachment behind tombstones, or prune the local cache. Invoking 'sase bead attachment' without a subcommand delegates to 'sase bead attachment list'. List and open never fetch; path always fetches from the shared store when needed, even above the auto-fetch cap. Push drains the upload outbox and never authors notes. Publish and unpublish edit manifests through NoteEdited with the note text unchanged.

Bare `sase bead attachment` defaults to `sase bead attachment list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                       | Summary                                               |
| -------------------------------- | ----------------------------------------------------- |
| `sase bead attachment list`      | List attachment snapshots                             |
| `sase bead attachment open`      | Open one attachment in the terminal viewer            |
| `sase bead attachment path`      | Print the absolute local view path for one attachment |
| `sase bead attachment prune`     | Prune the local attachment cache to its budget        |
| `sase bead attachment publish`   | Publish one note attachment to the public store       |
| `sase bead attachment purge`     | Purge one attachment behind tombstones                |
| `sase bead attachment push`      | Push queued attachment uploads to the shared store    |
| `sase bead attachment unpublish` | Unpublish one note attachment back to private         |

### `sase bead attachment list`

```text
usage: sase bead attachment list [-h] [id] [-j]
```

List attachment snapshots on one bead, or on every bead when no ID is given. Text output shows one descriptor per attachment plus the cached view path or an unavailable marker.

Options:

| Option         | Description                           | Default |
| -------------- | ------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit       | —       |
| `-j`, `--json` | Emit machine-readable attachment data | `false` |

Arguments:

| Argument | Description                |
| -------- | -------------------------- |
| `id`     | Full or shorthand issue ID |

### `sase bead attachment open`

```text
usage: sase bead attachment open [-h] id [name]
```

Materialize the extension-preserving local view and open it in the terminal viewer, with n/p across all viewable attachments on the bead. With no name, open the only viewable attachment or list candidates. Fails with a clear unavailable error when no local object exists; it never fetches.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                                                |
| -------- | ---------------------------------------------------------- |
| `id`     | Full or shorthand issue ID                                 |
| `name`   | Attachment name; omit to open the only viewable attachment |

### `sase bead attachment path`

```text
usage: sase bead attachment path [-h] id name
```

Materialize the extension-preserving local view and print its absolute path. Fetches the object from the shared store when needed, even above the auto-fetch cap. Fails with a clear unavailable error when the object cannot be fetched.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                |
| -------- | -------------------------- |
| `id`     | Full or shorthand issue ID |
| `name`   | Attachment name            |

### `sase bead attachment prune`

```text
usage: sase bead attachment prune [-h] [-y]
```

Evict cached objects confirmed present in a shared store, oldest views first, to fit under bead.attachments.local_cache_max_bytes. A dry-run plan prints by default; -y applies it. Pending-upload and local-only objects are never evicted.

Options:

| Option         | Description                                    | Default |
| -------------- | ---------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit                | —       |
| `-y`, `--yes`  | Evict the planned objects instead of a dry run | `false` |

### `sase bead attachment publish`

```text
usage: sase bead attachment publish [-h] id name [-y]
```

Widen one note attachment to public: rescan with the current scanner rules, upload the bytes to the public attachments sidecar, and append NoteEdited with visibility public and the note text unchanged. Human-only: refused inside an agent run except as an approved gate option. Note attachments only; +1 evidence is refused.

Options:

| Option         | Description                                 | Default |
| -------------- | ------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit             | —       |
| `-y`, `--yes`  | Publish without an interactive confirmation | `false` |

Arguments:

| Argument | Description                |
| -------- | -------------------------- |
| `id`     | Full or shorthand issue ID |
| `name`   | Attachment name to publish |

### `sase bead attachment purge`

```text
usage: sase bead attachment purge [-h] id name -r REASON [-y]
```

Remove one attachment's bytes everywhere while leaving every bead event untouched: a tombstone goes to each configured shared store, the local object and its views are deleted, and a local tombstone is recorded. Notes keep their text and render (purged); fetches refuse the digest. Prints the manual history-erasure procedure; it is never automated. It never authors notes.

Options:

| Option                         | Description                                                     | Default |
| ------------------------------ | --------------------------------------------------------------- | ------- |
| `-h`, `--help`                 | show this help message and exit                                 | —       |
| `-r REASON`, `--reason REASON` | Why the bytes are purged (recorded in the tombstone) (required) | —       |
| `-y`, `--yes`                  | Purge without an interactive confirmation                       | `false` |

Arguments:

| Argument | Description                |
| -------- | -------------------------- |
| `id`     | Full or shorthand issue ID |
| `name`   | Attachment name to purge   |

### `sase bead attachment push`

```text
usage: sase bead attachment push [-h] [id]
```

Drain the project attachment-upload outbox through the shared git store, then promote local-only objects that the store now accepts. With an ID, drain only digests referenced by that bead; without one, drain the project outbox. It never authors notes.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                                   |
| -------- | --------------------------------------------- |
| `id`     | Full or shorthand issue ID to scope the drain |

### `sase bead attachment unpublish`

```text
usage: sase bead attachment unpublish [-h] id name [-y]
```

Narrow one note attachment to private: ensure a private copy exists, remove the object from the public tree with a withdraw commit (no tombstone), and append NoteEdited with visibility private and the note text unchanged. Narrowing, so agents may run it. Note attachments only; +1 evidence is refused.

Options:

| Option         | Description                                   | Default |
| -------------- | --------------------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit               | —       |
| `-y`, `--yes`  | Unpublish without an interactive confirmation | `false` |

Arguments:

| Argument | Description                  |
| -------- | ---------------------------- |
| `id`     | Full or shorthand issue ID   |
| `name`   | Attachment name to unpublish |

## `sase bead blocked`

```text
usage: sase bead blocked [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase bead close`

```text
usage: sase bead close [-h] ID [ID ...] [-f] [-P] [-n NOTE] [-S] [-L] [-K]
                       [-W] [-y] [-p SPEC] [-r REASON]
                       [-R {canceled,done,superseded}]
```

Close one or more issues atomically. With --phases, the single target is an epic whose numbered phase beads are closed instead. Full IDs can route to another enabled project's owning store; mixed-store close batches are rejected before mutation. Free-text values accept @<path>.

Options:

| Option                                     | Description                                                                                                                                                                 | Default |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-S`, `--allow-sensitive`                  | Attach files from sensitive paths                                                                                                                                           | `false` |
| `-f`, `--force`                            | Close unfinished descendants; requires --reason and a non-done --resolution                                                                                                 | `false` |
| `-h`, `--help`                             | show this help message and exit                                                                                                                                             | —       |
| `-L`, `--local-only`                       | Keep new attachments on this machine without uploading                                                                                                                      | `false` |
| `-P`, `--no-push`                          | Commit the close locally but skip the post-commit push                                                                                                                      | `false` |
| `-n NOTE`, `--note NOTE`                   | Append this attributed note to each issue before closing it; @<path> reads it from that file, @@ escapes a literal leading @                                                | —       |
| `-p SPEC`, `--phases SPEC`                 | Close these phase beads of the target epic; comma-separated numbers and ranges (e.g. 1,3,5-7)                                                                               | —       |
| `-K`, `--private`                          | Store new attachments privately                                                                                                                                             | `false` |
| `-W`, `--public`                           | Request public attachments (needs confirmation)                                                                                                                             | `false` |
| `-r REASON`, `--reason REASON`             | Close reason; @<path> reads it from that file, @@ escapes a literal leading @                                                                                               | —       |
| `-R RESOLUTION`, `--resolution RESOLUTION` | How this bead was resolved; a real close defaults to done, while an already-closed bead is not compared unless this is supplied (choices: `canceled`, `done`, `superseded`) | —       |
| `-y`, `--yes`                              | Confirm a human public widening without a prompt                                                                                                                            | `false` |

Arguments:

| Argument | Description                                                                      |
| -------- | -------------------------------------------------------------------------------- |
| `ids`    | Full or shorthand issue IDs to close (exactly one epic ID when --phases is used) |

## `sase bead create`

```text
usage: sase bead create [-h] [-a ASSIGNEE] [-b BUG_ID] [-c PATCH]
                        [-d DESCRIPTION] [-x EXTERNAL_REF] [-f K=V] [-m MODEL]
                        [-R REF] [-z {xsmall,small,medium,large,xlarge}]
                        [-r {plan,epic}] -t TITLE -T TYPE -w REASON
```

Create a plan, phase, or standalone task bead. New task beads require an explicit size and -T 'task(<slug>)'; plan beads reject size, while raw phase creation accepts it optionally. Every create requires -w/--reason explaining why the bead was filed. Typed tasks take repeatable -f/--field values for the type's declared fields. A full parent ID in plan(...,<parent>) or phase(<parent>) creates the child in that parent's owning enabled project. Free-text values accept @<path>.

Options:

| Option                                            | Description                                                                                                                                                                                                                                                                                            | Default |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| `-a ASSIGNEE`, `--assignee ASSIGNEE`              | Assignee                                                                                                                                                                                                                                                                                               | —       |
| `-b BUG_ID`, `--bug-id BUG_ID`                    | Bug ID to pass when creating the attached Patch                                                                                                                                                                                                                                                        | —       |
| `-c PATCH`, `--patch PATCH`, `--changespec PATCH` | Attach a Patch name to a plan bead                                                                                                                                                                                                                                                                     | —       |
| `-d DESCRIPTION`, `--description DESCRIPTION`     | Issue description; @<path> reads it from that file, @@ escapes a literal leading @                                                                                                                                                                                                                     | —       |
| `-x EXTERNAL_REF`, `--external-ref EXTERNAL_REF`  | Project-qualified external issue identity, e.g. bug:sase#42                                                                                                                                                                                                                                            | —       |
| `-f K=V`, `--field K=V`                           | Task-type field value (repeatable). A value of @<path> is read from that file                                                                                                                                                                                                                          | —       |
| `-h`, `--help`                                    | show this help message and exit                                                                                                                                                                                                                                                                        | —       |
| `-m MODEL`, `--model MODEL`                       | Model to use when this bead is launched. Provider-qualified (e.g. codex/gpt-6.1-sol) or local alias (e.g. #pro). For epic plan beads this becomes the land-agent model; for phase beads it is the per-phase work model; for task beads it is the task-worker model.                                    | —       |
| `-w REASON`, `--reason REASON`                    | Why this bead was filed (one or two sentences, not the title); @<path> reads it from that file, @@ escapes a literal leading @. Required; blank or over-2000-character reasons are rejected before mutation. Example: -w 'A second agent reproduced dropped retries after the queue change' (required) | —       |
| `-R REF`, `--ref REF`                             | Artifact reference to attach (repeatable)                                                                                                                                                                                                                                                              | —       |
| `-z SIZE`, `--size SIZE`                          | Phase/task size; read sase/memory/sase_sizes.md for guidance (choices: `large`, `medium`, `small`, `xlarge`, `xsmall`)                                                                                                                                                                                 | —       |
| `-r TIER`, `--tier TIER`                          | Plan-bead tier (plan or epic) (choices: `epic`, `plan`)                                                                                                                                                                                                                                                | —       |
| `-t TITLE`, `--title TITLE`                       | Issue title (required)                                                                                                                                                                                                                                                                                 | —       |
| `-T TYPE`, `--type TYPE`                          | Bead type: plan(<plan_file>), plan(<plan_file>,<parent_id>), phase(<parent_id>), or task(<slug>); parent IDs may be full or shorthand. New tasks require a catalog slug; list them with `sase bead task-type` (required)                                                                               | —       |

## `sase bead dep`

```text
usage: sase bead dep [-h] {add,list,rm,tree} ...
```

Inspect and manage dependency edges. Invoking 'sase bead dep' without a subcommand delegates to 'sase bead dep list'. Full IDs can route to another enabled project's owning store; dependency mutations reject cross-store edges before writing.

Bare `sase bead dep` defaults to `sase bead dep list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                             |
| -------------------- | ----------------------------------- |
| `sase bead dep add`  | Add a dependency                    |
| `sase bead dep list` | List dependency edges               |
| `sase bead dep rm`   | Remove dependencies                 |
| `sase bead dep tree` | Walk the dependency graph as a tree |

### `sase bead dep add`

```text
usage: sase bead dep add [-h] issue depends_on
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument     | Description                                     |
| ------------ | ----------------------------------------------- |
| `issue`      | Full or shorthand issue that depends on another |
| `depends_on` | Full or shorthand issue being depended on       |

### `sase bead dep list`

```text
usage: sase bead dep list [-h] [id] [-c {always,auto,never}]
                          [-d {both,in,out}] [-f {compact,full,json}]
                          [-n LIMIT] [-s {claimed,closed,in_progress,open}]
```

List dependency edges with blocking state and recorded provenance. A scoped read includes every status by default; a store-wide read defaults to open, claimed, and in-progress beads.

Options:

| Option                                  | Description                                                                                   | Default   |
| --------------------------------------- | --------------------------------------------------------------------------------------------- | --------- |
| `-c COLOR`, `--color COLOR`             | Color output: always, auto, or never (default: auto) (choices: `always`, `auto`, `never`)     | `auto`    |
| `-d DIRECTION`, `--direction DIRECTION` | Edges to show: both, in, or out (default: both) (choices: `both`, `in`, `out`)                | `both`    |
| `-f FORMAT`, `--format FORMAT`          | Output format: compact, full, or json (default: compact) (choices: `compact`, `full`, `json`) | `compact` |
| `-h`, `--help`                          | show this help message and exit                                                               | —         |
| `-n LIMIT`, `--limit LIMIT`             | Maximum beads to print; 0 means unlimited                                                     | `0`       |
| `-s STATUS`, `--status STATUS`          | Filter by status (repeatable) (choices: `claimed`, `closed`, `in_progress`, `open`)           | —         |

Arguments:

| Argument | Description                |
| -------- | -------------------------- |
| `id`     | Full or shorthand issue ID |

### `sase bead dep rm`

```text
usage: sase bead dep rm [-h] issue depends_on [depends_on ...]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument     | Description                                    |
| ------------ | ---------------------------------------------- |
| `issue`      | Full or shorthand issue that depends on others |
| `depends_on` | Full or shorthand issues no longer depended on |

### `sase bead dep tree`

```text
usage: sase bead dep tree [-h] [id] [-c {always,auto,never}]
                          [-d {both,in,out}] [-f {compact,full,json}]
                          [-L LEVELS] [-s {claimed,closed,in_progress,open}]
```

Walk dependencies, blockers, or both as a deterministic tree. A scoped tree includes every status by default; a store-wide tree defaults to open, claimed, and in-progress beads.

Options:

| Option                                  | Description                                                                                   | Default   |
| --------------------------------------- | --------------------------------------------------------------------------------------------- | --------- |
| `-c COLOR`, `--color COLOR`             | Color output: always, auto, or never (default: auto) (choices: `always`, `auto`, `never`)     | `auto`    |
| `-d DIRECTION`, `--direction DIRECTION` | Direction to walk: both, in, or out (default: out) (choices: `both`, `in`, `out`)             | `out`     |
| `-f FORMAT`, `--format FORMAT`          | Output format: compact, full, or json (default: compact) (choices: `compact`, `full`, `json`) | `compact` |
| `-h`, `--help`                          | show this help message and exit                                                               | —         |
| `-L LEVELS`, `--levels LEVELS`          | Maximum levels to descend; 0 means unlimited                                                  | `0`       |
| `-s STATUS`, `--status STATUS`          | Filter by status (repeatable) (choices: `claimed`, `closed`, `in_progress`, `open`)           | —         |

Arguments:

| Argument | Description                |
| -------- | -------------------------- |
| `id`     | Full or shorthand issue ID |

## `sase bead doctor`

```text
usage: sase bead doctor [-h] [-F] [-I] [-A] [-P] [-T] [-C] [-y]
```

Options:

| Option                     | Description                                                                                                            | Default |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ------- |
| `-T`, `--fix-attachments`  | Preview and, after confirmation, repair attachment orphans, re-drain the upload outbox, and quarantine corrupt objects | `false` |
| `-F`, `--fix-design-refs`  | Preview and, after confirmation, repair recoverable bead design references                                             | `false` |
| `-I`, `--fix-issue-prefix` | Preview and, after confirmation, reset the store's issue prefix to the project name                                    | `false` |
| `-A`, `--fix-plan-archive` | Preview and, after confirmation, archive recoverable missing plans                                                     | `false` |
| `-P`, `--fix-projection`   | Preview and, after confirmation, rewrite issues.jsonl from canonical events                                            | `false` |
| `-h`, `--help`             | show this help message and exit                                                                                        | —       |
| `-C`, `--verify-cache`     | Compare the bead read-model cache against a forced full replay and report drift                                        | `false` |
| `-y`, `--yes`              | Apply requested repairs without an interactive confirmation                                                            | `false` |

## `sase bead epic-symbols`

```text
usage: sase bead epic-symbols [-h] [-c {auto,always,never}]
                              [-f {compact,json}] [id]
```

List --epic-symbol entries from the working tree's Justfile and the default branch's Justfile, tagging each row with the source it came from. With an ID, only entries keyed to that bead or its descendant suffixes are shown. Land and phase agents should run this before closing: leftover entries go stale the instant the bead closes, and sase bead close refuses while any remain.

Options:

| Option                         | Description                                                                               | Default   |
| ------------------------------ | ----------------------------------------------------------------------------------------- | --------- |
| `-c COLOR`, `--color COLOR`    | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`) | `auto`    |
| `-f FORMAT`, `--format FORMAT` | Output format: compact or json (default: compact) (choices: `compact`, `json`)            | `compact` |
| `-h`, `--help`                 | show this help message and exit                                                           | —         |

Arguments:

| Argument | Description                                          |
| -------- | ---------------------------------------------------- |
| `id`     | Full or shorthand issue ID; omit to list every entry |

## `sase bead export`

```text
usage: sase bead export [-h] [-o PATH]
```

Regenerate the issues.jsonl compatibility projection from the canonical event streams. Mutations never rewrite the projection; run this command when an external tool needs a fresh copy. The projection is git-ignored and never committed.

Options:

| Option                     | Description                                                                                      | Default |
| -------------------------- | ------------------------------------------------------------------------------------------------ | ------- |
| `-h`, `--help`             | show this help message and exit                                                                  | —       |
| `-o PATH`, `--output PATH` | Write the export to PATH instead of the store's issues.jsonl (default: the store's issues.jsonl) | —       |

## `sase bead history`

```text
usage: sase bead history [-h] [id] [-F FIELD] [-f {compact,full,json}]
                         [-n LIMIT] [-l] [-R] [-y]
```

Replay the canonical event streams for one bead, or find note revisions that no longer appear in current notes. Compact history output shows one row per event; full output shows the prior and new value for every changed field. A scoped full ID uses that bead's owning enabled project.

Options:

| Option                         | Description                                                                                   | Default   |
| ------------------------------ | --------------------------------------------------------------------------------------------- | --------- |
| `-F FIELD`, `--field FIELD`    | Restrict to events changing this field (repeatable)                                           | —         |
| `-f FORMAT`, `--format FORMAT` | Output format: compact, full, or json (default: compact) (choices: `compact`, `full`, `json`) | `compact` |
| `-h`, `--help`                 | show this help message and exit                                                               | —         |
| `-n LIMIT`, `--limit LIMIT`    | Newest entries to print; 0 means unlimited                                                    | `0`       |
| `-l`, `--lost-notes`           | Report beads whose current notes dropped an earlier revision                                  | `false`   |
| `-R`, `--restore`              | With --lost-notes, re-append dropped revisions after confirmation                             | `false`   |
| `-y`, `--yes`                  | With --restore, skip the confirmation prompt                                                  | `false`   |

Arguments:

| Argument | Description                |
| -------- | -------------------------- |
| `id`     | Full or shorthand issue ID |

## `sase bead init`

```text
usage: sase bead init [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase bead list`

```text
usage: sase bead list [-h] [-c {auto,always,never}] [-f {compact,json,full}]
                      [-n LIMIT] [-S DATE]
                      [-s {all,open,claimed,ready,snoozed,in_progress,closed}]
                      [-T SLUG] [-r {plan,epic}] [-t {plan,phase,task}]
                      [-u DATE]
```

List open, claimed, ready, snoozed, and in-progress beads by default. If none match and --status was not provided, list closed beads instead. --since and --until bound bead creation time. Closed listings default to the newest 20 beads unless --limit 0 is used or a creation-date bound is present. Compact rows include a size column when any listed bead has a stored size. Compact and full listings end with a summary line that describes only the printed rows and names how many matching beads a limit hid. Bare 'sase bead' defaults to this command.

Options:

| Option                         | Description                                                                                                                                | Default   |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ | --------- |
| `-c COLOR`, `--color COLOR`    | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                                  | `auto`    |
| `-f FORMAT`, `--format FORMAT` | Output format: compact, json, or full (default: compact) (choices: `compact`, `full`, `json`)                                              | `compact` |
| `-h`, `--help`                 | show this help message and exit                                                                                                            | —         |
| `-n LIMIT`, `--limit LIMIT`    | Maximum beads to print; closed listings default to 20, 0 means unlimited                                                                   | —         |
| `-S DATE`, `--since DATE`      | Only beads created at/after DATE                                                                                                           | —         |
| `-s STATUS`, `--status STATUS` | Filter by status; 'all' selects every status (repeatable) (choices: `all`, `claimed`, `closed`, `in_progress`, `open`, `ready`, `snoozed`) | —         |
| `-T SLUG`, `--task-type SLUG`  | Filter by task type slug; 'untyped' selects legacy beads (repeatable)                                                                      | —         |
| `-r TIER`, `--tier TIER`       | Filter by plan-bead tier (repeatable) (choices: `epic`, `plan`)                                                                            | —         |
| `-t TYPE`, `--type TYPE`       | Filter by issue type (repeatable). Flag beads are task beads; use -T flag (choices: `phase`, `plan`, `task`)                               | —         |
| `-u DATE`, `--until DATE`      | Only beads created at/before DATE                                                                                                          | —         |

## `sase bead note`

```text
usage: sase bead note [-h] id [text ...] [-a NAME] [-S] [-L] [-K] [-W] [-y]
                      [-e N | -x N]
```

Options:

| Option                     | Description                                                                                                             | Default |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------- |
| `-S`, `--allow-sensitive`  | Attach files from sensitive paths                                                                                       | `false` |
| `-a NAME`, `--author NAME` | Author recorded on the entry (default: current agent, else store owner)                                                 | —       |
| `-e N`, `--edit N`         | Rewrite note #N (the ordinal shown by `sase bead read`); re-read `read` after any edit or removal, since ordinals shift | —       |
| `-h`, `--help`             | show this help message and exit                                                                                         | —       |
| `-L`, `--local-only`       | Keep new attachments on this machine without uploading                                                                  | `false` |
| `-K`, `--private`          | Store new attachments privately                                                                                         | `false` |
| `-W`, `--public`           | Request public attachments (needs confirmation)                                                                         | `false` |
| `-x N`, `--remove N`       | Retract note #N (the ordinal shown by `sase bead read`); `sase bead history` keeps the retracted record                 | —       |
| `-y`, `--yes`              | Confirm a human public widening without a prompt                                                                        | `false` |

Arguments:

| Argument | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`     | Full or shorthand issue ID                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `text`   | Note text to append. Inside note text, @<path> attaches a snapshot of that file (the bead keeps the exact bytes on every machine). Accepted forms: @./shot.png, @~/logs/crash.log, @/tmp/trace.json, @docs/plan.md, @"name with spaces.png", or a bare @name.ext for a known file type. Write @@ where you need a literal @ that would otherwise start a reference. me@host, @large, and @research:… citations never need escaping. A note argument that is only @<file> still reads the note's text from that file. To attach files without prose, use `sase bead attach`. Required to append or with --edit; omit with --remove |

## `sase bead onboard`

```text
usage: sase bead onboard [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase bead open`

```text
usage: sase bead open [-h] id
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                          |
| -------- | ------------------------------------ |
| `id`     | Full or shorthand issue ID to reopen |

## `sase bead pages`

```text
usage: sase bead pages [-h] {refresh,url} ...
```

Reconcile generated Markdown pages in the project's beads sidecar or resolve one bead's hosted page URL. A bare 'sase bead pages' invocation prints this help.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                | Summary                                           |
| ------------------------- | ------------------------------------------------- |
| `sase bead pages refresh` | Reconcile generated pages from durable bead state |
| `sase bead pages url`     | Print one bead's hosted page URL                  |

### `sase bead pages refresh`

```text
usage: sase bead pages refresh [-h] [-b ID] [-j] [-w]
```

Rebuild bead lineage pages from durable state and repository history. The default is a read-only dry run; --write applies changes, removes orphaned pages, and commits one beads-store batch.

Options:

| Option               | Description                                                     | Default |
| -------------------- | --------------------------------------------------------------- | ------- |
| `-b ID`, `--bead ID` | Refresh only the lineage containing a full or shorthand bead ID | —       |
| `-h`, `--help`       | show this help message and exit                                 | —       |
| `-j`, `--json`       | Emit a machine-readable refresh report                          | `false` |
| `-w`, `--write`      | Write and commit changed pages (default: dry run)               | `false` |

### `sase bead pages url`

```text
usage: sase bead pages url [-h] bead_id
```

Resolve one bead's deterministic page address against the local beads-sidecar remote and branch. This command never uses the network.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument  | Description               |
| --------- | ------------------------- |
| `bead_id` | Full or shorthand bead ID |

## `sase bead read`

```text
usage: sase bead read [-h] [-c {auto,always,never}] [-d]
                      [-f {compact,json,full}] [-N] [-p {auto,always,never}]
                      [-P PROJECT] -r REASON [-s {auto,plain,rich}] [-w WIDTH]
                      ID [ID ...]
```

Read one or more beads after recording an audited, agent-attributed read per resolved bead before printing. The output is identical to `sase bead show`. Agents consulting beads to do work must use this command, while `show` is the human command.

Options:

| Option                            | Description                                                                                                                                                                                      | Default |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| `-c COLOR`, `--color COLOR`       | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                                                                                        | `auto`  |
| `-d`, `--download`                | Download every attachment on the shown beads from the shared store, lifting the bead.attachments.auto_fetch_max_bytes cap for this invocation                                                    | `false` |
| `-f FORMAT`, `--format FORMAT`    | Output format: compact, json, or full (default: full) (choices: `compact`, `full`, `json`)                                                                                                       | `full`  |
| `-h`, `--help`                    | show this help message and exit                                                                                                                                                                  | —       |
| `-N`, `--no-links`                | Skip artifact-link neighborhood resolution and omit LINKS / REFERENCED BY (and the JSON artifact_links array plus issue.links). Compact format never expands links, with or without this option  | `false` |
| `-p PAGER`, `--pager PAGER`       | Page long terminal output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                                                                           | `auto`  |
| `-P PROJECT`, `--project PROJECT` | Resolve every ID against one enabled project's bead store, by key, name, or alias (default: current project, falling back to each full ID's project prefix)                                      | —       |
| `-r REASON`, `--reason REASON`    | Non-empty reason for the audited bead read (required)                                                                                                                                            | —       |
| `-s STYLE`, `--style STYLE`       | Styling level for --format full: auto, plain, or rich (default: auto). --color decides whether ANSI may be emitted; --style decides how much styling to apply (choices: `auto`, `plain`, `rich`) | `auto`  |
| `-w WIDTH`, `--wrap WIDTH`        | Wrap DESCRIPTION, NOTES, and +1 evidence prose at WIDTH columns: integer >= 20, 'auto', 'none', or 0 (default: 88)                                                                               | `88`    |

Arguments:

| Argument | Description                                                                                                                           |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `ids`    | Full or shorthand issue IDs to read (rendered in the order given); an ID ending in '..' expands to that bead plus its direct children |

## `sase bead ready`

```text
usage: sase bead ready [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase bead ref`

```text
usage: sase bead ref [-h] {add,list,rm} ...
```

Inspect and manage artifact references. Invoking 'sase bead ref' without a subcommand delegates to 'sase bead ref list'. A scoped full bead ID uses that bead's owning project for storage and reference resolution.

Bare `sase bead ref` defaults to `sase bead ref list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                    |
| -------------------- | -------------------------- |
| `sase bead ref add`  | Attach artifact references |
| `sase bead ref list` | List artifact references   |
| `sase bead ref rm`   | Detach artifact references |

### `sase bead ref add`

```text
usage: sase bead ref add [-h] id refs [refs ...]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                   |
| -------- | ----------------------------- |
| `id`     | Full or shorthand issue ID    |
| `refs`   | Artifact references to attach |

### `sase bead ref list`

```text
usage: sase bead ref list [-h] [id] [-j] [-r]
```

Options:

| Option            | Description                                      | Default |
| ----------------- | ------------------------------------------------ | ------- |
| `-h`, `--help`    | show this help message and exit                  | —       |
| `-j`, `--json`    | Emit machine-readable reference data             | `false` |
| `-r`, `--resolve` | Resolve references against the current workspace | `false` |

Arguments:

| Argument | Description                |
| -------- | -------------------------- |
| `id`     | Full or shorthand issue ID |

### `sase bead ref rm`

```text
usage: sase bead ref rm [-h] id refs [refs ...]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                   |
| -------- | ----------------------------- |
| `id`     | Full or shorthand issue ID    |
| `refs`   | Artifact references to detach |

## `sase bead resolve-conflicts`

```text
usage: sase bead resolve-conflicts [-h]
```

Resolve merge or rebase conflicts in generated bead state. Only sdd/beads/issues.jsonl, events/manifest.json, config.json (next_counter-only), and events/streams/*.jsonl conflicts are auto-merged.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase bead rm`

```text
usage: sase bead rm [-h] ids [ids ...]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument | Description                                       |
| -------- | ------------------------------------------------- |
| `ids`    | One or more full or shorthand issue IDs to remove |

## `sase bead search`

```text
usage: sase bead search [-h] query [-c {auto,always,never}]
                        [-f {compact,json,full}] [-n LIMIT] [-e]
                        [-s {open,claimed,ready,snoozed,in_progress,closed}]
                        [-T SLUG] [-r {plan,epic}] [-t {plan,phase,task}]
```

Find beads whose human-readable fields contain a case-insensitive literal substring by default. With --regex, interpret the query as a regular expression that is case-insensitive unless the pattern starts with (?-i). Searches every bead status by default.

Options:

| Option                         | Description                                                                                                  | Default   |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------ | --------- |
| `-c COLOR`, `--color COLOR`    | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                    | `auto`    |
| `-f FORMAT`, `--format FORMAT` | Output format: compact, json, or full (default: compact) (choices: `compact`, `full`, `json`)                | `compact` |
| `-h`, `--help`                 | show this help message and exit                                                                              | —         |
| `-n LIMIT`, `--limit LIMIT`    | Maximum results to print; 0 means unlimited                                                                  | —         |
| `-e`, `--regex`                | Interpret query as a regular expression                                                                      | `false`   |
| `-s STATUS`, `--status STATUS` | Filter by status (repeatable) (choices: `claimed`, `closed`, `in_progress`, `open`, `ready`, `snoozed`)      | —         |
| `-T SLUG`, `--task-type SLUG`  | Filter by task type slug; 'untyped' selects legacy beads (repeatable)                                        | —         |
| `-r TIER`, `--tier TIER`       | Filter by plan-bead tier (repeatable) (choices: `epic`, `plan`)                                              | —         |
| `-t TYPE`, `--type TYPE`       | Filter by issue type (repeatable). Flag beads are task beads; use -T flag (choices: `phase`, `plan`, `task`) | —         |

Arguments:

| Argument | Description                          |
| -------- | ------------------------------------ |
| `query`  | Literal non-empty text to search for |

## `sase bead show`

```text
usage: sase bead show [-h] [-c {auto,always,never}] [-d]
                      [-f {compact,json,full}] [-i {auto,cells,kitty,never}]
                      [-N] [-p {auto,always,never}] [-P PROJECT]
                      [-s {auto,plain,rich}] [-w WIDTH] ID [ID ...]
```

Show every listed bead in argv order. Full or shorthand IDs are accepted. Full IDs first resolve against the current project's store, then fall back to the enabled project named by the ID prefix; shorthand IDs stay local unless --project pins one enabled project. An ID ending in '..' expands to that bead plus its direct children (phase beads and child epics, one level, in phase-number order) before duplicate IDs collapse after resolution. A missing ID reports on stderr and exits 1 without suppressing beads that did resolve. --format compact prints list rows; --format json emits today's single envelope for one ID and an array of envelopes for two or more IDs, always an array for an expansion. --no-links skips neighborhood resolution and omits human and JSON artifact-link fields. Long output on a terminal is paged with color intact. DESCRIPTION, NOTES, link reasons, and +1 evidence prose wrap at 88 columns by default without breaking URLs or inline code spans. -i/--images controls attachment previews (auto, cells, kitty, never); read, JSON, and piped show never draw. This is the human command; inside a SASE agent run it refuses with exit 2 and names the matching `sase bead read ... -r "<why>"` command. Agents consulting beads to do work must use `sase bead read` instead.

Options:

| Option                            | Description                                                                                                                                                                                      | Default |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| `-c COLOR`, `--color COLOR`       | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                                                                                        | `auto`  |
| `-d`, `--download`                | Download every attachment on the shown beads from the shared store, lifting the bead.attachments.auto_fetch_max_bytes cap for this invocation                                                    | `false` |
| `-f FORMAT`, `--format FORMAT`    | Output format: compact, json, or full (default: full) (choices: `compact`, `full`, `json`)                                                                                                       | `full`  |
| `-h`, `--help`                    | show this help message and exit                                                                                                                                                                  | —       |
| `-i IMAGES`, `--images IMAGES`    | Attachment image previews for --format full: auto, cells, kitty, or never (default: bead.show.images, auto). read, JSON, and piped show never draw (choices: `auto`, `cells`, `kitty`, `never`)  | —       |
| `-N`, `--no-links`                | Skip artifact-link neighborhood resolution and omit LINKS / REFERENCED BY (and the JSON artifact_links array plus issue.links). Compact format never expands links, with or without this option  | `false` |
| `-p PAGER`, `--pager PAGER`       | Page long terminal output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                                                                           | `auto`  |
| `-P PROJECT`, `--project PROJECT` | Resolve every ID against one enabled project's bead store, by key, name, or alias (default: current project, falling back to each full ID's project prefix)                                      | —       |
| `-s STYLE`, `--style STYLE`       | Styling level for --format full: auto, plain, or rich (default: auto). --color decides whether ANSI may be emitted; --style decides how much styling to apply (choices: `auto`, `plain`, `rich`) | `auto`  |
| `-w WIDTH`, `--wrap WIDTH`        | Wrap DESCRIPTION, NOTES, and +1 evidence prose at WIDTH columns: integer >= 20, 'auto', 'none', or 0 (default: 88)                                                                               | `88`    |

Arguments:

| Argument | Description                                                                                                                           |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `ids`    | Full or shorthand issue IDs to show (rendered in the order given); an ID ending in '..' expands to that bead plus its direct children |

## `sase bead snooze`

```text
usage: sase bead snooze [-h] ID [ID ...] [-c] [-p COUNT] [-r TEXT] [-u TIME]
```

Defer one or more open or ready task beads. A snoozed task keeps its place in every listing but stops raising triage gates until its wake time arrives or its +1 target is reached, whichever comes first. Use --cancel to wake one early.

Options:

| Option                          | Description                                                                                                            | Default |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ------- |
| `-c`, `--cancel`                | Wake these beads now, returning them to ready                                                                          | `false` |
| `-h`, `--help`                  | show this help message and exit                                                                                        | —       |
| `-p COUNT`, `--plus-ones COUNT` | Also wake when this many additional +1 reports arrive                                                                  | —       |
| `-r TEXT`, `--reason TEXT`      | Why this task is being deferred; @<path> reads it from that file, @@ escapes a literal leading @                       | —       |
| `-u TIME`, `--until TIME`       | Wake time: a duration (30m, 2h, 1h30m, 3d, 1d12h) or an absolute ISO-8601 timestamp; required unless --cancel is given | —       |

Arguments:

| Argument | Description                                           |
| -------- | ----------------------------------------------------- |
| `ids`    | One or more full or shorthand task bead IDs to snooze |

## `sase bead stats`

```text
usage: sase bead stats [-h]
```

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase bead sync`

```text
usage: sase bead sync [-h] [-s]
```

Options:

| Option           | Description                     | Default |
| ---------------- | ------------------------------- | ------- |
| `-h`, `--help`   | show this help message and exit | —       |
| `-s`, `--status` | Just check sync status          | `false` |

## `sase bead sync-external`

```text
usage: sase bead sync-external [-h] [-f] [-n] [-p PROJECT]
```

Diff an enabled project's external tracker against its beads on external_ref and create small open task beads for uncovered issues. Upstream closes and reopens update mirrored beads when safe, while referenced, worked, parented, and already-matching beads get attributed notes only. Runs the same reconciliation pass as the external_issue_mirror AXE job.

Options:

| Option                            | Description                                                                   | Default |
| --------------------------------- | ----------------------------------------------------------------------------- | ------- |
| `-n`, `--dry-run`                 | Show exact planned creations and status transitions without mutating anything | `false` |
| `-f`, `--full`                    | Force a full repair scan instead of the steady-state short-circuit            | `false` |
| `-h`, `--help`                    | show this help message and exit                                               | —       |
| `-p PROJECT`, `--project PROJECT` | Only mirror one project by display name, alias, or canonical key              | —       |

## `sase bead task-type`

```text
usage: sase bead task-type [-h] {list,show} ...
```

Inspect the effective task-type catalog assembled from builtins, plugins, and project config. Invoking 'sase bead task-type' without a subcommand delegates to 'sase bead task-type list'.

Bare `sase bead task-type` defaults to `sase bead task-type list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                 | Summary                                               |
| -------------------------- | ----------------------------------------------------- |
| `sase bead task-type list` | List task types agents may file                       |
| `sase bead task-type show` | Show one task type's fields, template, and provenance |

### `sase bead task-type list`

```text
usage: sase bead task-type list [-h] [-a] [-j]
```

List the effective task-type catalog as a colored table of slug, label, summary, source, and whether agents may file each type. Agent-uncreatable types are hidden unless -a/--all is passed.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-a`, `--all`  | Include agent-uncreatable types | `false` |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

### `sase bead task-type show`

```text
usage: sase bead task-type show [-h] <slug> [-j]
```

Show one task type: label, summary, when_to_use, every field with type, requirement, role, help, and validators, the body template, the triage threshold, and provenance. Reads are not audited; there is no -r/--reason.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

Arguments:

| Argument | Description               |
| -------- | ------------------------- |
| `slug`   | Task-type slug to inspect |

## `sase bead touched`

```text
usage: sase bead touched [-h] <agent> [-j] [-l N] [-v VERB]
```

List the beads one agent touched, newest touch first, as recorded in the agent/bead touch index. One row per bead carries the bead id, the verb chips the agent performed on it with repeat counts, the bead's title, and the relative last-touch time. The index is a derived cache reduced from bead event streams, so a row reflects the last refresh, never a live stream scan; a missing index simply lists nothing. Counts report what the corpus contains, never what it wishes it contained. read comes from `sase bead read` / `sase artifact read bead:` with reasons, viewed comes from a machine-local log of human `show` views, so a remote agent's views are not visible while its mutations are, and automation never produces viewed. linked currently never appears: bead link events are owner-attributed and task sase-159 tracks that. The CLI lists touched beads only; the panel also marks assigned but untouched beads with an assigned chip.

Options:

| Option                   | Description                                         | Default |
| ------------------------ | --------------------------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit                     | —       |
| `-j`, `--json`           | Emit machine-readable JSON                          | `false` |
| `-l N`, `--limit N`      | Maximum beads to print; 0 means unlimited           | —       |
| `-v VERB`, `--verb VERB` | Only show beads touched with this verb (repeatable) | —       |

Arguments:

| Argument | Description                                          |
| -------- | ---------------------------------------------------- |
| `agent`  | Agent name to list touches for (globalized or local) |

## `sase bead update`

```text
usage: sase bead update [-h] ID [ID ...] [-a ASSIGNEE] [-D DESIGN]
                        [-d DESCRIPTION] [-x EXTERNAL_REF | -X] [-m MODEL]
                        [-n NOTE] [-S] [-L] [-K] [-W] [-y] [-b DATE/RELEASE]
                        [-z {xsmall,small,medium,large,xlarge}]
                        [-s {open,claimed,ready,in_progress,closed}]
                        [-r {plan,epic}] [-t TITLE]
```

Update one or more issues. Every listed bead receives the same field changes in a single atomic commit.

Options:

| Option                                           | Description                                                                                                                                                                    | Default |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| `-S`, `--allow-sensitive`                        | Attach files from sensitive paths                                                                                                                                              | `false` |
| `-a ASSIGNEE`, `--assignee ASSIGNEE`             | —                                                                                                                                                                              | —       |
| `-X`, `--clear-external-ref`                     | Clear the external issue identity                                                                                                                                              | `false` |
| `-d DESCRIPTION`, `--description DESCRIPTION`    | Issue description; @<path> reads it from that file, @@ escapes a literal leading @                                                                                             | —       |
| `-D DESIGN`, `--design DESIGN`                   | —                                                                                                                                                                              | —       |
| `-x EXTERNAL_REF`, `--external-ref EXTERNAL_REF` | Project-qualified external issue identity, e.g. bug:sase#42                                                                                                                    | —       |
| `-h`, `--help`                                   | show this help message and exit                                                                                                                                                | —       |
| `-L`, `--local-only`                             | Keep new attachments on this machine without uploading                                                                                                                         | `false` |
| `-m MODEL`, `--model MODEL`                      | Model for this bead's launch. Provider-qualified (e.g. codex/gpt-6.1-sol) or local alias (e.g. #pro). Pass '' to clear.                                                        | —       |
| `-n NOTE`, `--note NOTE`                         | Append this attributed note to each issue; @<path> reads it from that file, @@ escapes a literal leading @                                                                     | —       |
| `-K`, `--private`                                | Store new attachments privately                                                                                                                                                | `false` |
| `-W`, `--public`                                 | Request public attachments (needs confirmation)                                                                                                                                | `false` |
| `-b DATE/RELEASE`, `--remove-by DATE/RELEASE`    | Extend a flag bead's removal thresholds, e.g. 2026-12-01/0.19.0; takes exactly one flag bead ID                                                                                | —       |
| `-z SIZE`, `--size SIZE`                         | Phase size; read sase/memory/sase_sizes.md for guidance (choices: `large`, `medium`, `small`, `xlarge`, `xsmall`)                                                              | —       |
| `-s STATUS`, `--status STATUS`                   | New status; `snoozed` is absent on purpose because it needs a wake time — use `sase bead snooze <id> -u <time>` (choices: `claimed`, `closed`, `in_progress`, `open`, `ready`) | —       |
| `-r TIER`, `--tier TIER`                         | — (choices: `epic`, `plan`)                                                                                                                                                    | —       |
| `-t TITLE`, `--title TITLE`                      | —                                                                                                                                                                              | —       |
| `-y`, `--yes`                                    | Confirm a human public widening without a prompt                                                                                                                               | `false` |

Arguments:

| Argument | Description                                       |
| -------- | ------------------------------------------------- |
| `ids`    | One or more full or shorthand issue IDs to update |

## `sase bead work`

```text
usage: sase bead work [-h] TARGET [TARGET ...] [-a DIR] [-c N] [-C NAME] [-n]
                      [-j] [-P] [-p ID|top-level] [-w SPEC] [-y] [-Y]
```

Launch one or more existing epic plan or standalone task beads, Markdown epic plans, or an ordered mix of both. Each target is processed completely before the next begins, and the command stops at the first error while preserving earlier side effects. An epic launch schedules its phase and land agents. A task launch starts one deterministic worker. A Markdown epic plan can also be validated, archived into the SDD store, compiled into a bead DAG, and launched. Plan-file launches are idempotent and resume from an existing bead_id link.

Options:

| Option                                     | Description                                                                                                                                                                                                          | Default |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a DIR`, `--artifacts-dir DIR`            | Planner artifacts directory to back-fill after an approved epic launch                                                                                                                                               | —       |
| `-c N`, `--capacity N`                     | Epic targets only: per-launch weighted-load capacity budget. Omit for default queue behavior; use 1 to run alone. A segment whose macro claims more weight gets a budget equal to that weight. N must be at least 1. | —       |
| `-C NAME`, `--cl-name NAME`                | Patch name for the approved epic completion notification                                                                                                                                                             | —       |
| `-n`, `--dry-run`                          | Validate and preview the wave plan without changing files, beads, or agents                                                                                                                                          | `false` |
| `-h`, `--help`                             | show this help message and exit                                                                                                                                                                                      | —       |
| `-j`, `--json`                             | Print one machine-readable result object per processed target; multi-target output is JSON Lines; implies --yes-to-all, so no confirmation prompt is shown                                                           | `false` |
| `-P`, `--no-push`                          | Commit plan or bead state locally but skip post-commit pushes                                                                                                                                                        | `false` |
| `-p ID|top-level`, `--parent ID|top-level` | Override a plan file's parent_bead with a full or shorthand ID; use 'top-level' to create an unparented epic                                                                                                         | —       |
| `-w SPEC`, `--wait SPEC`                   | Comma-separated agent names and bead=<id> entries the launched phases wait for                                                                                                                                       | —       |
| `-y`, `--yes`                              | Skip only the launch confirmation prompt                                                                                                                                                                             | `false` |
| `-Y`, `--yes-to-all`                       | Skip both destructive-cleanup and launch confirmation prompts                                                                                                                                                        | `false` |

Arguments:

| Argument | Description                                                                                                |
| -------- | ---------------------------------------------------------------------------------------------------------- |
| `target` | One or more full or shorthand epic/task bead IDs or paths to validated epic plan files, processed in order |

Related: [CLI command groups](index.md).
