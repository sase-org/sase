---
title: "sase plan"
description: "Review the plan pipeline, approve or reject pending proposals from the Patch, inspect SDD prompt/plan links, submit a new plan for review, search SDD and…"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase plan

Review, approve, reject, propose, search, show, and validate implementation plans

Reference for `sase plan`. Run `sase plan --help` for the exact output on this checkout.

```text
usage: sase plan [-h]
                 {approve,links,list,propose,reject,search,show,validate} ...
```

Review the plan pipeline, approve or reject pending proposals from the Patch, inspect SDD prompt/plan links, submit a new plan for review, search SDD and machine-local plans, show one plan's details, or strictly validate one plan file. With no subcommand, `sase plan` defaults to `sase plan list`.

Bare `sase plan` defaults to `sase plan list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand           | Summary                                                    |
| -------------------- | ---------------------------------------------------------- |
| `sase plan approve`  | Approve a pending proposal or a plan file                  |
| `sase plan links`    | List, refresh, repair, or validate SDD plan links          |
| `sase plan list`     | List plan proposals and approval history                   |
| `sase plan propose`  | Submit a plan file for approval (used by /sase_plan skill) |
| `sase plan reject`   | Reject one pending plan proposal                           |
| `sase plan search`   | Search SDD and machine-local markdown plans                |
| `sase plan show`     | Show one plan's details                                    |
| `sase plan validate` | Validate one plan file using its authored tier             |

## `sase plan approve`

```text
usage: sase plan approve [-h] [PLAN] [-D ID=VALUE] [-n]
                         [-k {approve,commit,epic,tale}] [-m MODEL] [-P NAME]
                         [-p PROMPT] [-w SPEC]
```

Approve a pending proposal or a plan file without a live approval gate. PLAN matches a live proposal first (notification ID, archive or bundle path, name, <shard>/<name>, plan: ref, or planner agent), then a plan file. If PLAN is omitted, exactly one pending proposal must exist. A plan already approved whose coder failed, was killed, or never launched gets a replacement coder; one whose coder is running or finished is refused.

Options:

| Option                             | Description                                                                                                                                                                                                                                                                                        | Default |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-D ID=VALUE`, `--decide ID=VALUE` | Answer one Plan Decision (repeatable as ID=VALUE; toggles take true/1/yes/on or false/0/no/off, choices take the exact key case-insensitively; giving the same id twice is an error)                                                                                                               | —       |
| `-n`, `--dry-run`                  | Preview the selected approval without changing files or launching work                                                                                                                                                                                                                             | `false` |
| `-h`, `--help`                     | show this help message and exit                                                                                                                                                                                                                                                                    | —       |
| `-k KIND`, `--kind KIND`           | Approval kind (default: tale; epic plans require an explicit kind): approve runs coder without committing an SDD plan; tale commits to sdd/plans with tier tale; epic commits there with tier epic; commit records the plan without launching coder (choices: `approve`, `commit`, `epic`, `tale`) | —       |
| `-m MODEL`, `--model MODEL`        | Optional model for the follow-up agent                                                                                                                                                                                                                                                             | —       |
| `-P NAME`, `--project NAME`        | Project for a plan without a live approval gate                                                                                                                                                                                                                                                    | —       |
| `-p PROMPT`, `--prompt PROMPT`     | Optional extra prompt text for approve/tale coder follow-up                                                                                                                                                                                                                                        | —       |
| `-w SPEC`, `--wait SPEC`           | Comma-separated agent names, turn=<agent>, bead=<id>, and hood=<name> entries the approved work waits for                                                                                                                                                                                          | —       |

Arguments:

| Argument   | Description                                                                                                |
| ---------- | ---------------------------------------------------------------------------------------------------------- |
| `selector` | Plan: name (TAB completes), <shard>/<name>[.md], path, plan: ref, planner agent, or notification ID/prefix |

## `sase plan links`

```text
usage: sase plan links [-h] {list,refresh,repair,validate} ...
```

Inspect bidirectional artifact links between SDD prompts and plans, or reconcile projected plan provenance headers. With no subcommand, `sase plan links` defaults to `sase plan links list`.

Bare `sase plan links` defaults to `sase plan links list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                 | Summary                                     |
| -------------------------- | ------------------------------------------- |
| `sase plan links list`     | List SDD artifact links                     |
| `sase plan links refresh`  | Reconcile projected plan provenance headers |
| `sase plan links repair`   | Infer and repair bidirectional SDD links    |
| `sase plan links validate` | Validate SDD artifact links                 |

### `sase plan links list`

```text
usage: sase plan links list [-h] [-j] [-p PATH]
```

Print every SDD prompt/plan artifact link and whether its reverse link is intact. This is also the default for bare `sase plan links`.

Options:

| Option                   | Description                                              | Default |
| ------------------------ | -------------------------------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit                          | —       |
| `-j`, `--json`           | Emit machine-readable JSON                               | `false` |
| `-p PATH`, `--path PATH` | SDD root or project root path (default: current project) | —       |

### `sase plan links refresh`

```text
usage: sase plan links refresh [-h] [-j] [-p PATH] [-P REF] [-w]
```

Rebuild PARENT, BEAD, AGENTS, and COMMITS plan-header sections from durable state. The default is a read-only dry run; --write updates changed plans and commits them to the plans store in one batch.

Options:

| Option                   | Description                                              | Default |
| ------------------------ | -------------------------------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit                          | —       |
| `-j`, `--json`           | Emit a machine-readable refresh report                   | `false` |
| `-p PATH`, `--path PATH` | SDD root or project root path (default: current project) | —       |
| `-P REF`, `--plan REF`   | Refresh only the plan named by REF                       | —       |
| `-w`, `--write`          | Write and commit changed plan headers (default: dry run) | `false` |

### `sase plan links repair`

```text
usage: sase plan links repair [-h] [-p PATH] [-w]
```

Options:

| Option                   | Description                                              | Default |
| ------------------------ | -------------------------------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit                          | —       |
| `-p PATH`, `--path PATH` | SDD root or project root path (default: current project) | —       |
| `-w`, `--write`          | Write inferred link fixes                                | `false` |

### `sase plan links validate`

```text
usage: sase plan links validate [-h] [-j] [-p PATH] [-q] [-W]
```

Options:

| Option                   | Description                                              | Default |
| ------------------------ | -------------------------------------------------------- | ------- |
| `-h`, `--help`           | show this help message and exit                          | —       |
| `-j`, `--json`           | Emit machine-readable JSON                               | `false` |
| `-p PATH`, `--path PATH` | SDD root or project root path (default: current project) | —       |
| `-q`, `--quiet`          | Only print validation failures                           | `false` |
| `-W`, `--show-warnings`  | Show warning-severity issues (hidden by default)         | `false` |

## `sase plan list`

```text
usage: sase plan list [-h] [-j] [-n LIMIT] [-s {approved,proposed,rejected}]
                      [-t {tale,epic}]
```

Show pending plan proposals plus approved and inferred rejected archived plans. Filter the displayed sections by status and control the amount of approval history shown. This is also the default for bare `sase plan`.

Options:

| Option                         | Description                                                                                                                   | Default |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                 | show this help message and exit                                                                                               | —       |
| `-j`, `--json`                 | Print plan inventory as JSON                                                                                                  | `false` |
| `-n LIMIT`, `--limit LIMIT`    | Maximum approved and rejected rows shown per section; 0 = unlimited; pending proposals are always shown in full (default: 10) | `10`    |
| `-s STATUS`, `--status STATUS` | Show only these pipeline sections (repeatable; default: all) (choices: `approved`, `proposed`, `rejected`)                    | —       |
| `-t TIER`, `--tier TIER`       | Filter by plan-file tier: tale or epic (repeatable) (choices: `epic`, `tale`)                                                 | —       |

## `sase plan propose`

```text
usage: sase plan propose [-h] PLAN_FILE
```

Submit a Markdown plan file for user approval. This command is intended for SASE agent runs with SASE_AGENT and SASE_ARTIFACTS_DIR set.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument    | Description               |
| ----------- | ------------------------- |
| `plan_file` | Path to the plan .md file |

## `sase plan reject`

```text
usage: sase plan reject [-h] [PLAN]
```

Reject one pending plan proposal. PLAN matches exactly first (notification ID, archive or bundle path, name, <shard>/<name>, plan: ref, or planner agent), then by notification-ID prefix. If PLAN is omitted, exactly one pending proposal must exist. The rejection response is written first; SASE then attempts to user-kill the matching planner agent and dismiss its Agents-tab row, the same cleanup path used by sase's TUI.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Arguments:

| Argument   | Description                                                                                                        |
| ---------- | ------------------------------------------------------------------------------------------------------------------ |
| `selector` | Pending plan: name (TAB completes), <shard>/<name>[.md], path, plan: ref, planner agent, or notification ID/prefix |

## `sase plan search`

```text
usage: sase plan search [-h] [query] [-c {auto,always,never}]
                        [-f {compact,full,json,markdown}] [-k KIND] [-n LIMIT]
                        [-A DATE] [-o {all,repo,local}]
                        [-r {relevance,recent,title}] [-s {wip,done}]
                        [-B DATE]
```

Find plan artifacts whose text contains a literal, case-insensitive query string, across plans in the resolved SDD store (the `repo` source, prioritized) and the machine-local `~/.sase/plans/` archive. The query is optional: omit it to browse and filter. SDD-store plans are surfaced above local plans on equal-relevance ties.

Options:

| Option                         | Description                                                                                                                      | Default   |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- | --------- |
| `-c COLOR`, `--color COLOR`    | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                        | `auto`    |
| `-f FORMAT`, `--format FORMAT` | Output format: compact, full, json, or markdown (default: compact) (choices: `compact`, `full`, `json`, `markdown`)              | `compact` |
| `-h`, `--help`                 | show this help message and exit                                                                                                  | —         |
| `-k KIND`, `--kind KIND`       | Filter repo artifacts by plan tier, prompt, or configured document-sidecar role (repeatable)                                     | —         |
| `-n LIMIT`, `--limit LIMIT`    | Maximum results to print; 0 means unlimited (default: 20)                                                                        | `20`      |
| `-A DATE`, `--since DATE`      | Only plans created on/after DATE (YYYY-MM-DD, YYYY-MM, YYYYMM, or relative 14d/2w/3m)                                            | —         |
| `-r SORT`, `--sort SORT`       | Sort order: relevance, recent, or title (default: relevance with a query, else recent) (choices: `recent`, `relevance`, `title`) | —         |
| `-o SOURCE`, `--source SOURCE` | Which corpus to scan: all, repo, or local (default: all) (choices: `all`, `local`, `repo`)                                       | `all`     |
| `-s STATUS`, `--status STATUS` | Filter by frontmatter status: wip or done (repeatable) (choices: `done`, `wip`)                                                  | —         |
| `-B DATE`, `--until DATE`      | Only plans created on/before DATE (YYYY-MM-DD, YYYY-MM, YYYYMM, or relative 14d/2w/3m)                                           | —         |

Arguments:

| Argument | Description                                                 |
| -------- | ----------------------------------------------------------- |
| `query`  | Literal case-insensitive substring to match; omit to browse |

## `sase plan show`

```text
usage: sase plan show [-h] [TARGET] [-c {auto,always,never}]
                      [-f {compact,full,json,raw}]
                      [-t {auto,bead,name,path,proposal,ref}] [-w WIDTH]
```

Resolve TARGET — an explicit path, a `plan:` reference or legacy marker path, a pending-approval id or unique prefix, a bare slug or `<shard>/<slug>`, or a bead id whose design points at a plan — to exactly one plan and render it as a colored, section-structured detail view matching the PLAN lane in sase's TUI. With no TARGET, show the sole visible pending plan proposal, exactly as `sase plan approve`/`reject` treat an omitted SELECTOR. In auto mode the ladder is tried in this order: path, ref, proposal, name, then bead; `-t/--target` forces one rung with no fallthrough.

Options:

| Option                                   | Description                                                                                                                                   | Default |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-c COLOR`, `--color COLOR`              | Color output: auto, always, or never (default: auto) (choices: `always`, `auto`, `never`)                                                     | `auto`  |
| `-f FORMAT`, `--format FORMAT`           | Output format: compact, full, json, or raw (default: full) (choices: `compact`, `full`, `json`, `raw`)                                        | `full`  |
| `-h`, `--help`                           | show this help message and exit                                                                                                               | —       |
| `-t TARGET_KIND`, `--target TARGET_KIND` | Force one interpretation of TARGET instead of walking the ladder (default: auto) (choices: `auto`, `bead`, `name`, `path`, `proposal`, `ref`) | `auto`  |
| `-w WIDTH`, `--wrap WIDTH`               | Wrap goal, phase, and diagnostics prose at WIDTH columns: integer >= 20, 'auto', 'none', or 0 (default: 88)                                   | `88`    |

Arguments:

| Argument | Description                                                   |
| -------- | ------------------------------------------------------------- |
| `target` | The plan to show (default: the sole visible pending proposal) |

## `sase plan validate`

```text
usage: sase plan validate [-h] PLAN_FILE [-e] [-j] [-q]
```

Strictly validate exactly one Markdown plan file against the frontmatter schema selected by its `tier:` property. The command is hermetic: it does not require an active project or agent run. All discovered problems are reported in one pass; failures include the expected schema and a minimal valid example.

Options:

| Option            | Description                                                   | Default |
| ----------------- | ------------------------------------------------------------- | ------- |
| `-e`, `--explain` | Print tier-specific schema guidance before validation results | `false` |
| `-h`, `--help`    | show this help message and exit                               | —       |
| `-j`, `--json`    | Emit a machine-readable validation envelope                   | `false` |
| `-q`, `--quiet`   | Print nothing for a valid plan in human output mode           | `false` |

Arguments:

| Argument    | Description                    |
| ----------- | ------------------------------ |
| `plan_file` | Path to the plan Markdown file |

Related: [CLI command groups](index.md).
