---
title: Bead CLI
description: An overview of the commands for reading and managing SASE beads.
---

# Bead CLI

The `sase bead` command group reads and manages bead records.

## CLI Commands

With no subcommand, `sase bead` defaults to `sase bead list` with default options. Use
the explicit `sase bead list` form when passing list filters.

<a id="sase-bead-apply-status-id-status"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-apply-status-id-status).
<a id="sase-bead-attach-id-file"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-attach-id-file).
<a id="sase-bead-attachment-list-id-open-path-push"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-attachment-list-id-open-path-push).
<a id="sase-bead-attachment-purge-id-name--r-why-sase-bead-attachment-prune"></a> Moved
to
[Bead CLI records](bead-cli-records.md#sase-bead-attachment-purge-id-name--r-why-sase-bead-attachment-prune).
<a id="sase-bead-blocked"></a> Moved to
[Bead CLI queries](bead-cli-query.md#sase-bead-blocked).
<a id="sase-bead-1-task-id"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-1-task-id).
<a id="sase-bead-close-id-id2"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-close-id-id2).
<a id="sase-bead-create"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-create). <a id="sase-bead-dep"></a>
Moved to [Bead CLI records](bead-cli-records.md#sase-bead-dep).
<a id="sase-bead-ref"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-ref). <a id="sase-bead-doctor"></a>
Moved to [Bead CLI queries](bead-cli-query.md#sase-bead-doctor).
<a id="sase-bead-epic-symbols-id"></a> Moved to
[Bead CLI queries](bead-cli-query.md#sase-bead-epic-symbols-id).
<a id="sase-bead-history-id"></a> Moved to
[Reading beads](bead-cli-inspection.md#sase-bead-history-id).
<a id="sase-bead-init"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-init). <a id="sase-bead-list"></a>
<a id="summary-line"></a> Moved to [Bead CLI queries](bead-cli-query.md#sase-bead-list).
<a id="sase-bead-note-id-text"></a> Moved to
[Reading beads](bead-cli-inspection.md#sase-bead-note-id-text).
<a id="sase-bead-onboard"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-onboard).
<a id="sase-bead-open-id"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-open-id). <a id="sase-bead-ready"></a>
Moved to [Bead CLI queries](bead-cli-query.md#sase-bead-ready).
<a id="sase-bead-resolve-conflicts"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-resolve-conflicts).
<a id="sase-bead-rm-id-id2"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-rm-id-id2).
<a id="sase-bead-search-query"></a> Moved to
[Bead CLI queries](bead-cli-query.md#sase-bead-search-query).
<a id="sase-bead-read-id-id2"></a> Moved to
[Reading beads](bead-cli-inspection.md#sase-bead-read-id-id2).
<a id="sase-bead-show-id-id2"></a> Moved to
[Reading beads](bead-cli-inspection.md#sase-bead-show-id-id2).
<a id="sase-bead-snooze-id-id2"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-snooze-id-id2).
<a id="sase-bead-stats"></a> Moved to
[Bead CLI queries](bead-cli-query.md#sase-bead-stats). <a id="sase-bead-sync"></a> Moved
to [Bead CLI records](bead-cli-records.md#sase-bead-sync).
<a id="sase-bead-sync-external"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-sync-external).
<a id="sase-bead-task-type"></a> Moved to
[Bead CLI queries](bead-cli-query.md#sase-bead-task-type).
<a id="sase-bead-touched-agent"></a> Moved to
[Bead CLI queries](bead-cli-query.md#sase-bead-touched-agent).
<a id="sase-bead-update-id-id2"></a> Moved to
[Bead CLI records](bead-cli-records.md#sase-bead-update-id-id2).
<a id="sase-bead-work-target"></a> Moved to
[Starting bead work](bead-work.md#sase-bead-work-target).

## Related

- [Bead CLI records](bead-cli-records.md)
- [Bead CLI queries](bead-cli-query.md)
- [Reading beads](bead-cli-inspection.md)
- [Starting bead work](bead-work.md)

## `sase bead`

With no subcommand, `sase bead` defaults to `sase bead list`. Commands that take
existing bead IDs route a full ID to the enabled project whose bead store owns it, while
shorthand suffixes stay in the current project; see
[CLI Reference](cli-workflows.md#work-tracking-and-planning) and
[Bead ID Arguments](beads.md#bead-id-arguments). The tables below cover the most-used
subcommands; [Beads](#cli-commands) documents every subcommand.

<a id="cli-options-29"></a> Moved to [sase bead](bead-cli.md#sase-bead).

<a id="command-behavior-18"></a> Moved to [Bead CLI](bead-cli.md#command-behavior-18).

### `sase bead create`

| Flag                          | Values                                         | Default    | Description                                                                                                                                                 |
| ----------------------------- | ---------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-t, --title`                 | string                                         | (required) | Issue title                                                                                                                                                 |
| `-w, --reason`                | string                                         | (required) | Why the bead was filed. Trimmed, non-blank, at most 2000 characters. `@<path>` reads the text from a file. See [Creation Reason](beads.md#creation-reason). |
| `-T, --type`                  | string                                         | (required) | `plan(<file>)`, `plan(<file>,<parent>)`, `phase(<parent_id>)`, or `task(<slug>)`. Feature flags use `sase flag new`                                         |
| `-f, --field`                 | `k=v`                                          | -          | Task-type field value; repeatable. `@<path>` reads the value from a file                                                                                    |
| `-d, --description`           | string                                         | -          | Issue description                                                                                                                                           |
| `-a, --assignee`              | string                                         | -          | Assignee name                                                                                                                                               |
| `-m, --model`                 | string                                         | -          | Epic land-agent, phase-worker, or task-worker model                                                                                                         |
| `-R, --ref`                   | artifact reference                             | -          | Artifact reference to attach; repeatable                                                                                                                    |
| `-z, --size`                  | `xsmall`, `small`, `medium`, `large`, `xlarge` | -          | Phase/task size; required for new task beads and rejected for plan beads. Phases use model and plan-first routing, tasks use model routing only             |
| `-r, --tier`                  | `plan`, `epic`                                 | -          | Plan-bead tier; invalid for phase and task beads                                                                                                            |
| `-c, --patch`, `--changespec` | Patch name                                     | -          | Attach Patch metadata to a plan bead; `--changespec` is legacy-compatible                                                                                   |
| `-b, --bug-id`                | string                                         | -          | Bug ID for the attached Patch; requires `--patch` or `--changespec`                                                                                         |
| `-x, --external-ref`          | string                                         | -          | Project-qualified external issue identity, e.g. `bug:sase#42`                                                                                               |

### `sase bead list`

| Flag              | Values                                                                | Default                                    | Description                                                                                                                 |
| ----------------- | --------------------------------------------------------------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `-c, --color`     | `auto`, `always`, `never`                                             | `auto`                                     | Color mode for compact output                                                                                               |
| `-f, --format`    | `compact`, `json`, `full`                                             | `compact`                                  | Output format                                                                                                               |
| `-n, --limit`     | non-negative integer                                                  | (unlimited)                                | Maximum beads to print; closed listings default to 20, `0` means all                                                        |
| `-S, --since`     | DATE                                                                  | -                                          | Only beads created at or after DATE                                                                                         |
| `-s, --status`    | `all`, `open`, `claimed`, `ready`, `snoozed`, `in_progress`, `closed` | open, claimed, ready, snoozed, in progress | Filter by status (repeatable); `all` selects every status. With no match and no `--status`, closed beads are listed instead |
| `-T, --task-type` | catalog slug or `untyped`                                             | -                                          | Filter by task type (repeatable); `untyped` selects legacy beads                                                            |
| `-r, --tier`      | `plan`, `epic`                                                        | -                                          | Filter by plan-bead tier (repeatable)                                                                                       |
| `-t, --type`      | `plan`, `phase`, `task`                                               | -                                          | Filter by issue type (repeatable). Flag beads are tasks; use `-T flag`                                                      |
| `-u, --until`     | DATE                                                                  | -                                          | Only beads created at or before DATE                                                                                        |

### `sase bead search`

| Flag              | Values                                                         | Default     | Description                                                                            |
| ----------------- | -------------------------------------------------------------- | ----------- | -------------------------------------------------------------------------------------- |
| `query`           | string                                                         | (required)  | Literal non-empty text to search for                                                   |
| `-c, --color`     | `auto`, `always`, `never`                                      | `auto`      | Color mode for compact output                                                          |
| `-f, --format`    | `compact`, `json`, `full`                                      | `compact`   | Output format                                                                          |
| `-e, --regex`     | flag                                                           | -           | Treat the query as a case-insensitive regular expression unless it starts with `(?-i)` |
| `-n, --limit`     | non-negative integer                                           | (unlimited) | Maximum results to print; `0` also means unlimited                                     |
| `-s, --status`    | `open`, `claimed`, `ready`, `snoozed`, `in_progress`, `closed` | -           | Filter by status (repeatable); all statuses are searched by default                    |
| `-T, --task-type` | catalog slug or `untyped`                                      | -           | Filter by task type (repeatable); `untyped` selects legacy beads                       |
| `-r, --tier`      | `plan`, `epic`                                                 | -           | Filter by plan-bead tier (repeatable)                                                  |
| `-t, --type`      | `plan`, `phase`, `task`                                        | -           | Filter by issue type (repeatable). Flag beads are tasks; use `-T flag`                 |

### `sase bead task-type`

With no subcommand, `sase bead task-type` defaults to `sase bead task-type list`.

| Flag / argument | Values | Default | Description                                            |
| --------------- | ------ | ------- | ------------------------------------------------------ |
| `list`          |        |         | Colored catalog table; `-a/--all` includes uncreatable |
| `show <slug>`   |        |         | Full spec, fields, template, triage, and provenance    |
| `-j, --json`    | flag   | -       | Machine-readable output on `list` and `show`           |

### `sase bead epic-symbols`

| Flag           | Values                    | Default   | Description                                |
| -------------- | ------------------------- | --------- | ------------------------------------------ |
| `id`           | string                    | (all)     | Optional bead ID; omit to list every entry |
| `-c, --color`  | `auto`, `always`, `never` | `auto`    | Color mode for compact output              |
| `-f, --format` | `compact`, `json`         | `compact` | Output format                              |

### `sase bead read`

| Flag             | Values                             | Default         | Description                                                                             |
| ---------------- | ---------------------------------- | --------------- | --------------------------------------------------------------------------------------- |
| `ids`            | string                             | (required)      | One or more IDs; `<epic-id>..` expands the epic plus direct children                    |
| `-c, --color`    | `auto`, `always`, `never`          | `auto`          | Color mode; applies to `--format full` and compact                                      |
| `-f, --format`   | `compact`, `json`, `full`          | `full`          | Output format. Compact never expands artifact links                                     |
| `-N, --no-links` | flag                               | off             | Skip artifact-link neighborhood resolution and omit link sections / JSON                |
| `-p, --pager`    | `auto`, `always`, `never`          | `auto`          | Page long terminal output                                                               |
| `-P, --project`  | project key, name, or alias        | current project | Resolve every ID against one enabled project's bead store, including shorthand suffixes |
| `-r, --reason`   | string                             | (required)      | Non-empty reason for the audited bead read                                              |
| `-s, --style`    | `auto`, `plain`, `rich`            | `auto`          | Styling level for `--format full`                                                       |
| `-w, --wrap`     | integer >= 20, `auto`, `none`, `0` | `88`            | Prose wrap width for the filing reason, description, notes, link reasons, and evidence  |

### `sase bead touched`

| Flag          | Values       | Default    | Description                                                                 |
| ------------- | ------------ | ---------- | --------------------------------------------------------------------------- |
| `agent`       | string       | (required) | Agent name, globalized or local                                             |
| `-j, --json`  | flag         | off        | Machine-readable rows with `verbs`, `actors`, and `read_reasons`            |
| `-l, --limit` | integer >= 0 | unlimited  | Maximum beads to print; `0` means unlimited                                 |
| `-v, --verb`  | verb         | (all)      | Only show beads touched with this verb (repeatable); unknown verbs exit `2` |

### `sase bead show`

| Flag             | Values                             | Default         | Description                                                                             |
| ---------------- | ---------------------------------- | --------------- | --------------------------------------------------------------------------------------- |
| `ids`            | string                             | (required)      | One or more IDs; `<epic-id>..` expands the epic plus direct children                    |
| `-c, --color`    | `auto`, `always`, `never`          | `auto`          | Color mode; applies to `--format full` and compact                                      |
| `-f, --format`   | `compact`, `json`, `full`          | `full`          | Output format. Compact never expands artifact links                                     |
| `-N, --no-links` | flag                               | off             | Skip artifact-link neighborhood resolution and omit link sections / JSON                |
| `-p, --pager`    | `auto`, `always`, `never`          | `auto`          | Page long terminal output                                                               |
| `-P, --project`  | project key, name, or alias        | current project | Resolve every ID against one enabled project's bead store, including shorthand suffixes |
| `-s, --style`    | `auto`, `plain`, `rich`            | `auto`          | Styling level for `--format full`                                                       |
| `-w, --wrap`     | integer >= 20, `auto`, `none`, `0` | `88`            | Prose wrap width for the filing reason, description, notes, link reasons, and evidence  |

### `sase bead open`

| Flag | Values | Default    | Description        |
| ---- | ------ | ---------- | ------------------ |
| `id` | string | (required) | Issue ID to reopen |

### `sase bead update`

| Flag                       | Values                                              | Default    | Description                                                           |
| -------------------------- | --------------------------------------------------- | ---------- | --------------------------------------------------------------------- |
| `ids`                      | string                                              | (required) | One or more full or shorthand issue IDs                               |
| `-s, --status`             | `open`, `claimed`, `ready`, `in_progress`, `closed` | -          | Change status; `ready` is task-only. Use `sase bead snooze` to snooze |
| `-t, --title`              | string                                              | -          | Change title                                                          |
| `-d, --description`        | string                                              | -          | Change description                                                    |
| `-n, --note`               | string                                              | -          | Append an attributed note to each issue                               |
| `-D, --design`             | path                                                | -          | Change design path; all types accepted                                |
| `-a, --assignee`           | string                                              | -          | Change assignee                                                       |
| `-m, --model`              | string                                              | -          | Change launch model; `''` clears it                                   |
| `-b, --remove-by`          | `YYYY-MM-DD/release`                                | -          | Extend one `flag` task bead's thresholds                              |
| `-z, --size`               | `xsmall`, `small`, `medium`, `large`, `xlarge`      | -          | Change phase/task size                                                |
| `-r, --tier`               | `plan`, `epic`                                      | -          | Change plan-bead tier                                                 |
| `-x, --external-ref`       | string                                              | -          | Set the project-qualified external issue identity, e.g. `bug:sase#42` |
| `-X, --clear-external-ref` | flag                                                | -          | Clear the external issue identity                                     |

### `sase bead close`

| Flag               | Values                           | Default    | Description                                            |
| ------------------ | -------------------------------- | ---------- | ------------------------------------------------------ |
| `ids`              | string                           | (required) | One or more IDs; exactly one epic ID with `--phases`   |
| `-f, --force`      | flag                             | -          | Sweep unfinished descendants; needs both below         |
| `-P, --no-push`    | flag                             | -          | Commit the close locally but skip the post-commit push |
| `-n, --note`       | string                           | -          | Attributed note appended to each listed issue          |
| `-p, --phases`     | number/range list                | -          | Close numbered phase beads of the target epic          |
| `-r, --reason`     | string                           | -          | Optional close reason text                             |
| `-R, --resolution` | `canceled`, `done`, `superseded` | `done`     | How this bead was resolved                             |

### `sase bead rm`

Atomically removes the requested issues and the recursive union of their descendants.
Every requested ID must exist; overlapping or repeated selections remove each issue only
once. Removal is irreversible.

| Flag  | Values | Default    | Description           |
| ----- | ------ | ---------- | --------------------- |
| `ids` | string | (required) | One or more issue IDs |

### `sase bead note`

| Flag           | Values           | Default                   | Description                                                                                   |
| -------------- | ---------------- | ------------------------- | --------------------------------------------------------------------------------------------- |
| `id`           | string           | (required)                | Full or shorthand issue ID                                                                    |
| `text`         | string           | -                         | Note text; a single `@<path>` token reads it from a file. Required unless `--remove` is given |
| `-a, --author` | string           | current agent, else owner | Author recorded on the entry                                                                  |
| `-e, --edit`   | note ordinal `N` | -                         | Rewrite note `N` as numbered by `sase bead read`; ordinals shift after any edit or removal    |
| `-x, --remove` | note ordinal `N` | -                         | Retract note `N`; `sase bead history` keeps the retracted record                              |

### `sase bead dep`

Bare `sase bead dep` delegates to `sase bead dep list`. Mutations reject dependency
edges that would cross bead stores before writing.

| Form                   | Flag / argument                | Values                                        | Default                                                                | Description                                                                                           |
| ---------------------- | ------------------------------ | --------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `dep list`             | `id`                           | string                                        | store-wide                                                             | Optional issue whose edges to list                                                                    |
| `dep list`             | `-d, --direction`              | `both`, `in`, `out`                           | `both`                                                                 | Edges to show                                                                                         |
| `dep list`, `dep tree` | `-c, --color` / `-f, --format` | `auto\|always\|never` / `compact\|full\|json` | `auto` / `compact`                                                     | Color mode and output format                                                                          |
| `dep list`, `dep tree` | `-s, --status`                 | `open`, `claimed`, `in_progress`, `closed`    | all when scoped; open, claimed, ready, snoozed, in progress store-wide | Filter by status (repeatable); current `--help` text omits ready and snoozed from the runtime default |
| `dep list`             | `-n, --limit`                  | non-negative integer                          | -                                                                      | Maximum beads to print; `0` means unlimited                                                           |
| `dep tree`             | `id`                           | string                                        | store-wide                                                             | Optional issue to walk from                                                                           |
| `dep tree`             | `-d, --direction`              | `both`, `in`, `out`                           | `out`                                                                  | Walk dependencies (`out`), blockers (`in`), or both                                                   |
| `dep tree`             | `-L, --levels`                 | non-negative integer                          | unlimited                                                              | Maximum levels to descend; `0` means unlimited                                                        |
| `dep add`              | `issue`                        | string                                        | (required)                                                             | Issue that depends                                                                                    |
| `dep add`              | `depends_on`                   | string                                        | (required)                                                             | Issue being depended upon                                                                             |
| `dep rm`               | `issue` `depends_on...`        | strings                                       | (required)                                                             | Remove one or more dependencies from an issue                                                         |

### `sase bead sync`

| Flag           | Values | Default | Description                          |
| -------------- | ------ | ------- | ------------------------------------ |
| `-s, --status` | flag   | -       | Check sync status without committing |

### `sase bead work`

| Flag                  | Values                                | Default    | Description                                                                                        |
| --------------------- | ------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------- |
| `targets`             | bead IDs or plan paths                | (required) | One or more epic/task beads or validated epic plan files, processed in order until the first error |
| `-a, --artifacts-dir` | directory                             | -          | Back-fill planner artifacts after each approved epic; plan-file targets only                       |
| `-c, --capacity`      | positive integer                      | omitted    | Epic-only per-launch capacity budget; `1` runs alone; a heavier macro weight floors that segment   |
| `-C, --cl-name`       | Patch name                            | -          | Approved epic Patch name applied per plan-file target                                              |
| `-n, --dry-run`       | flag                                  | -          | Preview the epic wave plan or task prompt without mutating files, beads, or agents                 |
| `-j, --json`          | flag                                  | -          | Print one result object per processed target as JSON Lines and imply `--yes-to-all`                |
| `-P, --no-push`       | flag                                  | -          | Commit checkpoint state locally but skip post-commit pushes                                        |
| `-p, --parent`        | bead ID or `top-level`                | -          | Override a plan file's `parent_bead`, including forcing an unparented epic; plan-file targets only |
| `-w, --wait`          | comma-separated names and `bead=<id>` | -          | Agent names and bead dependencies the launched phases wait for                                     |
| `-y, --yes`           | flag                                  | -          | Skip only the launch confirmation prompt                                                           |
| `-Y, --yes-to-all`    | flag                                  | -          | Skip both destructive-cleanup and launch confirmation prompts                                      |

Multiple `sase bead work` targets are non-atomic: earlier successes are not rolled back,
later targets are not prevalidated, and every command-wide flag is checked again for the
current target.

## Command behavior {#command-behavior-18}
