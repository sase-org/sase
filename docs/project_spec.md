# ProjectSpec Format

A ProjectSpec is SASE's project-level `.sase` file. It groups the non-terminal
[ChangeSpecs](change_spec.md) for one project and may also store project metadata used
by workspace and agent coordination.

ProjectSpec files live under `~/.sase/projects/<project>/<project>.sase`. Terminal
ChangeSpecs are moved to the adjacent archive file,
`~/.sase/projects/<project>/<project>-archive.sase`. Legacy `.gp` files from earlier
releases remain readable as a fallback; the `sase changespec migrate-extension` command
renames them to the canonical `.sase` extension. That migration changes only the
ProjectSpec filenames; it does not rewrite ChangeSpec blocks or alter review state.

## Format

A ProjectSpec has two parts:

1. Optional project metadata before the first `NAME:` line.
2. One or more ChangeSpec blocks, separated by two blank lines.

The ChangeSpec parser finds blocks by scanning for `NAME:` lines. Project metadata is
read by narrower helpers and must stay before the first ChangeSpec.

```text
BARE_REPO_DIR: ~/.sase/repos/my_project.git
WORKSPACE_DIR: ~/projects/git/my_project/
PROJECT_STATE: enabled
PROJECT_NAME: my_project
PROJECT_ALIASES: docs
RUNNING:
  #10 | 12345 | run | my_project_add_config_parser_1 | 260509_121314


NAME: my_project_add_config_parser_1
DESCRIPTION:
  Add configuration file parser

  This PR implements configuration loading and validation.
BUG: http://b/12345
STATUS: WIP


NAME: my_project_add_docs_1
DESCRIPTION:
  Document configuration setup

  This PR adds user-facing documentation for the configuration file.
PARENT: my_project_add_config_parser_1
STATUS: WIP
```

## BUG Field

`BUG:` is a ChangeSpec field, not required project metadata. Put it inside each
ChangeSpec that should link to a bug or issue. SASE stores the value as text; common
values are a plain identifier or a URL:

```text
BUG: 12345
BUG: http://b/12345
BUG: https://b/12345
```

PR workflows that receive `SASE_BUG_ID` or `sase commit --bug-id` write the ChangeSpec
field as `http://b/<id>`. Child ChangeSpecs may inherit the parent's `BUG:` when SASE
creates them through the commit workflow.

## Project Metadata Fields

Project metadata fields are optional and appear before the first `NAME:` line. SASE
currently uses these fields:

- **BARE_REPO_DIR**: Path to the local bare git repository for the built-in `#git`
  workflow.
- **WORKSPACE_DIR**: Path to the primary checkout (workspace `#0`). Managed numbered
  checkouts are resolved through the per-project workspace store rather than by
  appending `_<num>` to this path; see
  [`docs/workspace.md`](workspace.md#workspace-directory-layout) for the
  directory-layout reference and [`docs/configuration.md`](configuration.md#workspace)
  for the `workspace.root` knob.
- **PROJECT_STATE**: Project lifecycle state. User-facing values are `enabled` and
  `disabled`; `sibling` is reserved for internal linked-repository backing records.
  Missing `PROJECT_STATE` means `enabled`. Legacy `active` normalizes to enabled, while
  `inactive`, `archived`, and `closed` normalize to disabled.
- **PROJECT_NAME**: Optional user-facing project name. The storage key remains the
  directory name `~/.sase/projects/<project>/`; `PROJECT_NAME` is surfaced in project
  lists, launch pickers, agent grouping labels, and VCS workspace references. ChangeSpec
  `project:` queries (including the `+project` shorthand) also use this configured name
  exactly and case-insensitively, falling back to the directory key only when
  `PROJECT_NAME` is missing or invalid.
- **PROJECT_ALIASES**: Comma-separated alternate project names accepted in VCS workspace
  references. Aliases are canonicalized to the directory-key project name before launch
  state, prompt history, and agent artifacts are written.
- **RUNNING**: Active workspace claims written and released by SASE while agents or
  workflows are running.

`BARE_REPO_DIR` and `WORKSPACE_DIR` are created by first-use `#git:<project>`
initialization or `#git:<bare-repo-path>` registration. They are parsed only before the
first ChangeSpec.

`PROJECT_STATE` is managed by `sase project`. If you edit this field by hand, keep it
before `RUNNING:` or the first `NAME:` line and use one of the valid lowercase values.

`PROJECT_NAME` is written by workspace providers such as `sase-github` and may be edited
by hand. If you edit it manually, keep it before `RUNNING:` or the first `NAME:` line
and use the same syntax as SASE project names.

`PROJECT_ALIASES` is managed by `sase project alias` and ACE's Projects tab (in the SASE
Admin Center). If you edit it by hand, keep it before `RUNNING:` or the first `NAME:`
line and use the same comma-separated form SASE writes.

### Project Names and Aliases

The directory name remains the canonical storage key. `PROJECT_NAME` lets a known
project expose a primary user-facing name without renaming its project directory.
`PROJECT_ALIASES` adds secondary names. For example, `PROJECT_NAME: bob` in
`~/.sase/projects/gh_bbugyi200__bob/gh_bbugyi200__bob.sase` makes launch-bound VCS refs
such as `#gh:bob`, `#gh_bob`, and `#gh(bob)` behave like refs to the `gh_bbugyi200__bob`
directory-key project.

Workspace providers can create display names automatically. The GitHub provider uses
this for first-use `owner/repo` refs: `#gh:foo-org/foo` can create a canonical SASE
project such as `gh_foo-org__foo` with `WORKSPACE_DIR` set to
`~/projects/github/foo-org/foo/` and `PROJECT_NAME: foo`. If another GitHub repo has the
same basename, such as `#gh:bar-org/foo`, the provider keeps a distinct canonical
project such as `gh_bar-org__foo` and allocates the first available display name,
starting with `foo_1`, then `foo_2`, and so on.

Existing basename projects are compatibility anchors. If `~/.sase/projects/foo/foo.sase`
already points at `~/projects/github/foo-org/foo/`, the GitHub provider reuses `foo`
instead of migrating or renaming it. Existing auto-aliased GitHub projects also keep
their aliases; no automatic migration from `PROJECT_ALIASES` to `PROJECT_NAME` is
performed.

`PROJECT_NAME` and aliases are resolved at the launch/xprompt boundary before workspace
resolution, xprompt expansion, prompt history writes, and agent artifact writes. These
friendly refs should not persist in `submitted_xprompt.md`, `raw_xprompt.md`,
`agent_meta.json`, prompt history, history sort keys, or VCS refs. Storage paths and
metadata keep using the directory key, while display surfaces prefer `PROJECT_NAME` when
present. Display-only helpers also humanize filename-safe project stems in some
artifact, retry, and mobile-facing labels when they can map the stem back to a
ProjectSpec display name; the underlying files are not renamed.

ChangeSpec `project:` queries use `PROJECT_NAME` as their sole project identity when it
is configured; the directory key is not an additional query alias. `PROJECT_ALIASES`
remain launch/xprompt aliases and do not participate in this filter. Non-terminal and
archived ChangeSpecs share the name configured in the main ProjectSpec.

Validation rules:

- Missing `PROJECT_NAME` means the user-facing name is the directory-key project name.
- Missing `PROJECT_ALIASES` means the project has no aliases.
- Alias values are comma-separated, trimmed, deduplicated, and stored in sorted order.
- `PROJECT_NAME` and alias names use the same syntax as SASE project names.
- `PROJECT_NAME` allocation tries the requested short name first, then appends `_1`,
  `_2`, and higher suffixes until it finds a value that does not collide.
- Project alias mutation validates the exact aliases provided by the caller; it does not
  allocate alternate spellings automatically.
- An alias cannot equal its directory-key project name or the same project's
  `PROJECT_NAME`.
- A directory key, `PROJECT_NAME`, or alias cannot collide with another project's
  directory key, `PROJECT_NAME`, or alias across non-system projects in any lifecycle
  state.
- Invalid or duplicate manually edited names and aliases are reported as parse warnings;
  CLI and TUI mutation helpers reject invalid writes.

CLI commands:

```bash
sase project alias list [PROJECT] [-j|--json]
sase project alias add PROJECT ALIAS
sase project alias remove PROJECT ALIAS
sase project alias clear PROJECT
```

Alias mutation uses the normal ProjectSpec lock and can target enabled, disabled, or
sibling records. The system-managed `home` project cannot be mutated.

ACE exposes aliases in the Projects tab of the SASE Admin Center (press `#`). Rows show
compact alias information, the detail pane shows the full list, the text filter matches
`PROJECT_NAME` and aliases, and `A` opens the alias editor for the highlighted project.
Alias edits replace the selected project's alias set; marked bulk operations remain
lifecycle-only.

### Project Lifecycle

Project lifecycle state controls whether a project appears in the default lists used to
start new work or browse current work. It is project-level metadata; it does not delete
project files. Do not confuse it with ChangeSpec status (`WIP` through `Submitted` or
`Archived`), an agent or workspace being active, or the `is_sase_managed` configuration
marker that authorizes generated project files.

| State      | Meaning                                                                                           |
| ---------- | ------------------------------------------------------------------------------------------------- |
| `enabled`  | Normal work state. Missing `PROJECT_STATE` also means enabled.                                    |
| `disabled` | Dormant, historical, or finished project. Hidden from default launch and discovery lists.         |
| `sibling`  | Internal linked-repository backing marker. It is not a third user-facing project lifecycle state. |

Legacy `PROJECT_STATE: active` files normalize to enabled. Legacy `inactive`,
`archived`, and `closed` files normalize to disabled. Normal user workflows should use
`sase project enable` and `sase project disable`; `sibling` is reserved for SASE's
linked-repository bookkeeping.

Broad project discovery is enabled-only. That includes launch and completion pickers,
`sase changespec search`, project-local xprompt catalogs, broad mobile helper catalogs,
and all-known bead helper reads. Disabled records are intentionally hidden from those
surfaces. An explicitly typed known-project VCS ref such as `#gh:sase` is the exception:
launch preparation treats it as intent to resume work and writes
`PROJECT_STATE: enabled` before claiming a workspace. A checkout cwd or mobile `project`
value is only prompt-resolution context, not a workspace ref; without an explicit ref, a
bare prompt defaults to `#git:home`. Direct workspace claims that bypass launch
preparation remain blocked by the claim guard while the ProjectSpec is disabled.

Agents use `/sase_repo` for configured linked repositories and for another SASE
project's primary repo. The underlying audited open infers the host project and
workspace from cwd; agent-history views that need old artifacts pass an explicit
all-state scan.

Use `sase project list --state all` to inspect disabled projects and sibling records,
and `sase project show <project>` to see state, workspace, launchability, and warnings.
Run `sase project enable <project>` before a direct workspace claim, or use an explicit
known-project VCS ref when automatic re-enablement is intended. The `enable`, `disable`,
and `set-state` forms update the ProjectSpec under the normal ProjectSpec lock.
Deprecated `activate`, `deactivate`, `archive`, and `close` aliases remain accepted for
compatibility. Disabling refuses projects with live `RUNNING` claims or active artifact
markers unless `--force` is passed. The system-managed `home` project cannot be mutated
through this command.

ACE exposes the same lifecycle operations through the Projects tab of the SASE Admin
Center (press `#`). The tab shows enabled and disabled non-system projects together,
with enabled rows first. Its single text filter also matches the literal state name. The
tab supports marks for bulk enable/disable operations and bulk full-directory deletion,
and uses the same blocked-operation checks before disabling a project. It can also open
the selected ProjectSpec in `$EDITOR`. Its delete action removes the whole SASE project
directory under `~/.sase/projects/` after confirmation, including ProjectSpecs,
project-local config, and artifacts; it does not remove workspace checkouts. This is
broader than `Ctrl+D` in project launch pickers, which only removes an empty project's
ProjectSpec files.

Common workflows:

- Disable a dormant project: `sase project disable old-project`
- List disabled projects: `sase project list --state disabled`
- List sibling project records: `sase project list --state sibling`
- Inspect every lifecycle state as JSON: `sase project list --state all --json`
- Re-enable from the CLI: `sase project enable old-project`
- Add a short project alias: `sase project alias add bob-cli bob`
- Inspect project aliases as JSON: `sase project alias list bob-cli --json`
- Re-enable from ACE: press `#`, switch to the Projects tab, highlight the project, then
  press `a`
- Edit aliases from ACE: press `#`, switch to the Projects tab, highlight the project,
  then press `A`
- Bulk-disable from ACE: press `#`, switch to the Projects tab, mark projects with `m`,
  then press `d`

Maintenance and agent-history scans intentionally keep reading all project directories.
This keeps live `RUNNING` claims, stale-claim cleanup, dismissed-agent recovery,
agent-name collision checks, and historical Agents-tab rows visible even after a project
is disabled.

The `RUNNING` section is managed by SASE. Each entry has this shape:

```text
RUNNING:
  #<WORKSPACE_NUM> | <PID> | <WORKFLOW> | <CHANGESPEC_NAME> | <TIMESTAMP> | PINNED
```

The timestamp and `PINNED` marker are optional. Do not edit `RUNNING` by hand unless you
are repairing a stale workspace claim and have verified the process is gone.

## ChangeSpec Fields

Each ChangeSpec in a ProjectSpec follows the [ChangeSpec format](change_spec.md). For
hand-written entries, the normal minimum fields are:

1. **NAME**: Unique ChangeSpec identifier. SASE-generated names normally start with
   `<project>_` and end with a numeric uniqueness suffix such as `_1`.
2. **DESCRIPTION**: A title, a blank line, and a body, all indented by two spaces.
3. **STATUS**: One of the lifecycle statuses documented in
   [`change_spec.md`](change_spec.md#status). New manual work typically starts as `WIP`.

Common optional fields include:

- **PARENT**: The `NAME` of a parent ChangeSpec that must land first. Omit it when there
  is no dependency.
- **PR**: URL for the created review, omitted until the PR exists. New files write
  `PR:`; legacy `CL:` fields remain readable during the compatibility window.
- **BUG**: Bug or issue reference for this ChangeSpec.
- **COMMITS**, **DELTAS**, **HOOKS**, **COMMENTS**, **MENTORS**, and **TIMESTAMPS**: See
  [`change_spec.md`](change_spec.md) for details.

## Example

```text
WORKSPACE_DIR: ~/projects/git/my_project/
PROJECT_STATE: enabled
PROJECT_NAME: my_project
PROJECT_ALIASES: docs


NAME: my_project_add_config_parser_1
DESCRIPTION:
  Add configuration file parser for user settings

  This PR implements a YAML-based configuration parser that reads
  user settings from ~/.myapp/config.yaml. The parser includes load
  and validation behavior, plus tests for valid YAML, invalid config,
  and missing file handling.
BUG: http://b/12345
STATUS: WIP


NAME: my_project_integrate_parser_1
DESCRIPTION:
  Integrate config parser into application startup

  This PR loads the parser during application initialization and
  surfaces validation errors clearly. Tests cover valid and invalid
  startup configuration.
PARENT: my_project_add_config_parser_1
STATUS: WIP


NAME: my_project_add_docs_1
DESCRIPTION:
  Document configuration setup

  This PR explains where the configuration file lives, shows common
  examples, and documents the supported keys.
PARENT: my_project_integrate_parser_1
STATUS: WIP
```

## Important Notes

- **Project file path**: Use `~/.sase/projects/<project>/<project>.sase` for
  non-terminal ChangeSpecs and `~/.sase/projects/<project>/<project>-archive.sase` for
  terminal history.
- **Project metadata**: Keep `BARE_REPO_DIR`, `WORKSPACE_DIR`, `PROJECT_STATE`,
  `PROJECT_NAME`, `PROJECT_ALIASES`, and `RUNNING` before the first `NAME:` line.
- **Blank lines between ChangeSpecs**: Separate ChangeSpecs with exactly two blank
  lines.
- **NAME field**: Prefer SASE-generated names, which use the project prefix and a
  numeric suffix.
- **PARENT field**: Set it only to another ChangeSpec `NAME`; omit it when there is no
  dependency.
- **PR field**: Omit until the PR exists, then set it to the review URL.
- **No file modification lists**: Keep file lists out of `DESCRIPTION`; SASE records
  file-level deltas separately.
