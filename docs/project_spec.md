# ProjectSpec Format

A ProjectSpec is SASE's project-level `.sase` file. It groups the active [ChangeSpecs](change_spec.md) for one project
and may also store project metadata used by workspace and agent coordination.

ProjectSpec files live under `~/.sase/projects/<project>/<project>.sase`. Terminal ChangeSpecs are moved to the adjacent
archive file, `~/.sase/projects/<project>/<project>-archive.sase`. Legacy `.gp` files from earlier releases remain
readable as a fallback; the `sase changespec migrate-extension` command renames them to the canonical `.sase` extension.
That migration changes only the ProjectSpec filenames; it does not rewrite ChangeSpec blocks or alter review state.

## Format

A ProjectSpec has two parts:

1. Optional project metadata before the first `NAME:` line.
2. One or more ChangeSpec blocks, separated by two blank lines.

The ChangeSpec parser finds blocks by scanning for `NAME:` lines. Project metadata is read by narrower helpers and must
stay before the first ChangeSpec.

```text
BARE_REPO_DIR: ~/.sase/repos/my_project.git
WORKSPACE_DIR: ~/projects/git/my_project/
PROJECT_STATE: active
RUNNING:
  #10 | 12345 | run | my_project_add_config_parser_1 | 260509_121314


NAME: my_project_add_config_parser_1
DESCRIPTION:
  Add configuration file parser

  This CL implements configuration loading and validation.
BUG: http://b/12345
STATUS: WIP


NAME: my_project_add_docs_1
DESCRIPTION:
  Document configuration setup

  This CL adds user-facing documentation for the configuration file.
PARENT: my_project_add_config_parser_1
STATUS: WIP
```

## BUG Field

`BUG:` is a ChangeSpec field, not required project metadata. Put it inside each ChangeSpec that should link to a bug or
issue. SASE stores the value as text; common values are a plain identifier or a URL:

```text
BUG: 12345
BUG: http://b/12345
BUG: https://b/12345
```

PR workflows that receive `SASE_BUG_ID` or `sase commit --bug-id` write the ChangeSpec field as `http://b/<id>`. Child
ChangeSpecs may inherit the parent's `BUG:` when SASE creates them through the commit workflow.

## Project Metadata Fields

Project metadata fields are optional and appear before the first `NAME:` line. SASE currently uses these fields:

- **BARE_REPO_DIR**: Path to the local bare git repository for the built-in `#git` workflow.
- **WORKSPACE_DIR**: Path to the primary checkout (workspace `#0`). Managed numbered checkouts are resolved through the
  per-project workspace store rather than by appending `_<num>` to this path; see
  [`docs/workspace.md`](workspace.md#workspace-directory-layout) for the directory-layout reference and
  [`docs/configuration.md`](configuration.md#workspace) for the `workspace.root` knob.
- **PROJECT_STATE**: Project lifecycle state. Valid values are `active`, `archived`, and `closed`. Missing
  `PROJECT_STATE` means `active`, so existing projects do not need a migration.
- **RUNNING**: Active workspace claims written and released by SASE while agents or workflows are running.

`BARE_REPO_DIR` and `WORKSPACE_DIR` are created by `sase git init` or by first-use `#git:<project>` initialization. They
are parsed only before the first ChangeSpec.

`PROJECT_STATE` is managed by `sase project`. If you edit this field by hand, keep it before `RUNNING:` or the first
`NAME:` line and use one of the valid lowercase values.

### Project Lifecycle

Project lifecycle state controls whether a project appears in the default lists used to start new work or browse current
work. It is project-level metadata; it does not delete project files and is separate from a ChangeSpec whose `STATUS` is
`Archived`.

| State      | Meaning                                                                                                   |
| ---------- | --------------------------------------------------------------------------------------------------------- |
| `active`   | Normal work state. Missing `PROJECT_STATE` also means `active`, so existing projects need no migration.   |
| `archived` | Dormant or historical project. Hidden from default launch pickers and discovery lists.                    |
| `closed`   | Finished project. Operationally hidden from the same default launch and discovery surfaces as `archived`. |

Default project discovery is active-only. That includes ACE project selection, `sase changespec search`, known-project
workspace references such as `#gh:sase`, project-local xprompt catalogs, broad mobile helper catalogs, and all-known
bead helper reads. Agent-history views that need old artifacts pass an explicit all-state scan.

Use `sase project list --state all` to inspect inactive projects, `sase project show <project>` to see state, workspace,
launchability, and warnings, and `sase project activate <project>` before launching new work in an archived or closed
project. The `archive`, `close`, and `set-state` forms update the ProjectSpec under the normal ProjectSpec lock.
Archiving or closing refuses projects with live `RUNNING` claims or active artifact markers unless `--force` is passed.
The system-managed `home` project cannot be mutated through this command.

ACE exposes the same lifecycle operations through the `,p` project management panel. The panel lists non-system projects
across all states by default, offers text and state filters, supports marks for bulk activate/archive/close operations
and bulk full-directory deletion, and uses the same blocked-operation checks before archiving or closing a project. It
can also open the selected ProjectSpec in `$EDITOR`. Its delete action removes the whole SASE project directory under
`~/.sase/projects/` after confirmation, including ProjectSpecs, project-local config, and artifacts; it does not remove
workspace checkouts. This is broader than `Ctrl+D` in project launch pickers, which only removes an empty project's
ProjectSpec files.

Common workflows:

- Archive a dormant project: `sase project archive old-project`
- List closed projects: `sase project list --state closed`
- Inspect every lifecycle state as JSON: `sase project list --state all --json`
- Reactivate from the CLI: `sase project activate old-project`
- Reactivate from ACE: press `,p`, highlight the project, then press `a`
- Bulk-archive from ACE: press `,p`, mark projects with `m`, then press `r`

Maintenance and agent-history scans intentionally keep reading all project directories. This keeps live `RUNNING`
claims, stale-claim cleanup, dismissed-agent recovery, agent-name collision checks, and historical Agents-tab rows
visible even after a project is archived or closed.

The `RUNNING` section is managed by SASE. Each entry has this shape:

```text
RUNNING:
  #<WORKSPACE_NUM> | <PID> | <WORKFLOW> | <CHANGESPEC_NAME> | <TIMESTAMP> | PINNED
```

The timestamp and `PINNED` marker are optional. Do not edit `RUNNING` by hand unless you are repairing a stale workspace
claim and have verified the process is gone.

## ChangeSpec Fields

Each ChangeSpec in a ProjectSpec follows the [ChangeSpec format](change_spec.md). For hand-written entries, the normal
minimum fields are:

1. **NAME**: Unique ChangeSpec identifier. SASE-generated names normally start with `<project>_` and end with a numeric
   uniqueness suffix such as `_1`.
2. **DESCRIPTION**: A title, a blank line, and a body, all indented by two spaces.
3. **STATUS**: One of the lifecycle statuses documented in [`change_spec.md`](change_spec.md#status). New manual work
   typically starts as `WIP`.

Common optional fields include:

- **PARENT**: The `NAME` of a parent ChangeSpec that must land first. Omit it when there is no dependency.
- **CL / PR**: URL for the created review, omitted until the CL or PR exists. `CL:` and `PR:` are parsed the same way.
- **BUG**: Bug or issue reference for this ChangeSpec.
- **COMMITS**, **DELTAS**, **HOOKS**, **COMMENTS**, **MENTORS**, and **TIMESTAMPS**: See
  [`change_spec.md`](change_spec.md) for details.

## Example

```text
WORKSPACE_DIR: ~/projects/git/my_project/
PROJECT_STATE: active


NAME: my_project_add_config_parser_1
DESCRIPTION:
  Add configuration file parser for user settings

  This CL implements a YAML-based configuration parser that reads
  user settings from ~/.myapp/config.yaml. The parser includes load
  and validation behavior, plus tests for valid YAML, invalid config,
  and missing file handling.
BUG: http://b/12345
STATUS: WIP


NAME: my_project_integrate_parser_1
DESCRIPTION:
  Integrate config parser into application startup

  This CL loads the parser during application initialization and
  surfaces validation errors clearly. Tests cover valid and invalid
  startup configuration.
PARENT: my_project_add_config_parser_1
STATUS: WIP


NAME: my_project_add_docs_1
DESCRIPTION:
  Document configuration setup

  This CL explains where the configuration file lives, shows common
  examples, and documents the supported keys.
PARENT: my_project_integrate_parser_1
STATUS: WIP
```

## Important Notes

- **Project file path**: Use `~/.sase/projects/<project>/<project>.sase` for active ChangeSpecs and
  `~/.sase/projects/<project>/<project>-archive.sase` for terminal history.
- **Project metadata**: Keep `BARE_REPO_DIR`, `WORKSPACE_DIR`, `PROJECT_STATE`, and `RUNNING` before the first `NAME:`
  line.
- **Blank lines between ChangeSpecs**: Separate ChangeSpecs with exactly two blank lines.
- **NAME field**: Prefer SASE-generated names, which use the project prefix and a numeric suffix.
- **PARENT field**: Set it only to another ChangeSpec `NAME`; omit it when there is no dependency.
- **CL / PR field**: Omit until the CL or PR exists, then set it to the review URL.
- **No file modification lists**: Keep file lists out of `DESCRIPTION`; SASE records file-level deltas separately.
