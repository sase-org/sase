---
create_time: 2026-06-01
updated_time: 2026-06-01
status: research
---

# Project Lifecycle Configuration Research

## Question

Users need a dynamic way to mark SASE projects as active, archived, or closed, and they need to do it from both the CLI
and the ace TUI. What storage model, command shape, and TUI integration should SASE use?

## Summary Recommendation

Add first-class project lifecycle metadata under each existing project directory:

```text
~/.sase/projects/<project>/
  <project>.sase
  <project>-archive.sase
  project.json
```

Use `project.json` for project-level lifecycle state and keep ProjectSpec files focused on ChangeSpecs, workspace
claims, and provider fields:

```json
{
  "schema_version": 1,
  "name": "sase",
  "lifecycle": "active",
  "updated_at": "2026-06-01T00:00:00Z",
  "updated_by": "cli"
}
```

Missing `project.json` should mean `active`. That gives existing installs zero migration burden and lets rollout start by
adding filters without rewriting every project.

Put the lifecycle reader, writer, validation, and filtering contract in `../sase-core/crates/sase_core`, then expose it
through `sase_core_rs` and a thin Python facade. This is shared domain behavior: CLI, TUI, mobile helpers, xprompt
catalogs, bead lookups, ChangeSpec search, and agent scans all need the same active/archived/closed meaning.

Do not implement this by renaming directories, moving projects into archive folders, or editing `~/.config/sase/sase.yml`
from the TUI.

## Lifecycle Semantics

Recommended initial semantics:

| Lifecycle | Default visibility | New launches | Workspace required | Intended use |
| --- | --- | --- | --- | --- |
| `active` | Included in normal CLI/TUI/mobile/xprompt/bead scans | Allowed | Yes for project launches | Current work |
| `archived` | Hidden from daily default views; visible with explicit archived/all filters | Blocked by default; can reactivate | Usually yes | Dormant project with useful history |
| `closed` | Hidden except project management and explicit `--include-closed` reads | Blocked | No | Historical/project no longer operational |

Safety rule: lifecycle transitions away from `active` should refuse when a project has live `RUNNING` claims or active
artifact rows unless the user passes a force flag. Even with forced archived/closed status, active runtime rows should
remain visible in the Agents tab until they finish, so SASE never hides live work.

Treat `home` as a system scope, not a normal configurable project, in the first implementation.

## Current Shape

SASE already has a stable project directory contract:

- `src/sase/ace/changespec/project_spec_path.py:26` defines canonical active ProjectSpec filenames as
  `<project>.sase`; `:31` defines `<project>-archive.sase`; `:72` resolves canonical `.sase` with legacy `.gp` fallback.
- The Rust mirror at `../sase-core/crates/sase_core/src/project_spec.rs:12` through `:93` carries the same filename and
  preferred-path logic.
- `src/sase/core/paths.py:16` documents `projects/` as intentionally unsharded because it is expected to be bounded by
  active project count. Once closed projects accumulate, lifecycle filtering is the right way to preserve that assumption.

Today, most broad project scans simply walk every directory under `~/.sase/projects`:

- ChangeSpecs: `src/sase/ace/changespec/__init__.py:142` reads both main and archive ProjectSpecs across every project.
- ChangeSpec cache: `src/sase/ace/changespec/cache.py:56` repeats the same broad scan with per-file mtime/size caching.
- TUI launch selector: `src/sase/ace/tui/modals/project_select_modal.py:70` loads home, launchable projects, and active
  ChangeSpecs; `project_discovery.py:13` decides launchable projects by scanning project dirs.
- TUI running agents: `src/sase/ace/tui/models/_loaders/_running_loaders.py:56` returns all project files and then reads
  each ProjectSpec `RUNNING` field.
- TUI done/workflow artifacts: `_done_loaders.py:181` and `_workflow_loaders.py:30` scan
  `~/.sase/projects/*/artifacts/...`.
- Rust artifact scanner: `../sase-core/crates/sase_core/src/agent_scan/scanner.rs:107` walks every project directory,
  with only an exact `only_projects` include list.
- Xprompt all-project loading: `src/sase/xprompt/loader_sources.py:380` enumerates all ProjectSpecs with valid
  `WORKSPACE_DIR`.
- Mobile/bead helpers: `src/sase/integrations/_mobile_helper_beads.py:195` and `src/sase/bead/workspace.py:43` scan all
  known project dirs.

This makes project lifecycle a cross-cutting filter, not a single TUI feature.

## Options Considered

### Option 1: Store lifecycle in `~/.config/sase/sase.yml`

Example:

```yaml
projects:
  sase:
    lifecycle: active
  old-tool:
    lifecycle: archived
```

Pros:

- Easy for users to edit by hand.
- Fits the word "configure".
- `sase config show` already explains merged config.

Cons:

- The TUI would be mutating user-authored config, overlays, and possibly chezmoi-managed files.
- Config merge behavior includes defaults, user config, `sase_*.yml` overlays, and local `./sase.yml`; dynamic per-project
  state does not belong in that merge chain.
- TUI runs intentionally disable local config inheritance for ace, so project lifecycle from config would need careful
  source rules.
- A project status change is operational state, not static configuration.

Verdict: poor fit.

### Option 2: Move or rename inactive project directories

Example:

```text
~/.sase/projects-active/sase/
~/.sase/projects-archived/old-tool/
```

Pros:

- Existing broad scans would naturally see fewer active projects.
- Manual filesystem inspection is obvious.

Cons:

- Many callers assume `~/.sase/projects/<project>/<project>.sase`.
- Agent artifacts, branch maps, episodes, dismissed bundles, mobile context, and workspace helpers all use project-dir
  relative paths.
- Moving directories creates a risky migration and breaks references embedded in marker JSON and historical artifacts.
- "Archive" already means terminal ChangeSpecs via `<project>-archive.sase`, so directory archival would overload the
  term further.

Verdict: too disruptive.

### Option 3: Add a top-level field to `<project>.sase`

Example:

```text
PROJECT_LIFECYCLE: archived
WORKSPACE_DIR: /home/bryan/projects/sase/
```

Pros:

- Local to the existing project record.
- Reuses existing ProjectSpec locks and atomic write helpers.
- No sidecar drift.

Cons:

- Mixes project metadata into a text file mostly treated as ChangeSpec corpus plus workspace claims.
- A lifecycle change would update ProjectSpec mtime/size and invalidate ChangeSpec parsing caches even though no
  ChangeSpec changed.
- Closed projects may not have a useful active ProjectSpec beyond metadata.
- More naming confusion around active ProjectSpec vs active project lifecycle vs archive ProjectSpec.

Verdict: viable, but less clean than a sidecar.

### Option 4: Add per-project `project.json`

Pros:

- Local to the project directory, so it moves/copies with project state.
- Structured, schema-versioned, and easy to extend with future metadata.
- Missing file can default to active, so no migration is required.
- Status changes do not touch ChangeSpec text or `RUNNING` fields.
- Rust core can parse and filter it cheaply before Python callers do heavier work.

Cons:

- Adds one extra small read per project scan.
- Needs its own atomic write and lock discipline.
- Needs drift handling if `project.json` exists without a ProjectSpec, or vice versa.

Verdict: best fit.

## Proposed Core Contract

Add a Rust-owned project lifecycle module with Python bindings:

```rust
enum ProjectLifecycle {
    Active,
    Archived,
    Closed,
}

struct ProjectRecordWire {
    name: String,
    lifecycle: ProjectLifecycle,
    project_dir: String,
    project_file: Option<String>,
    archive_file: Option<String>,
    workspace_dir: Option<String>,
    metadata_file: String,
    metadata_missing: bool,
    warnings: Vec<String>,
}
```

Core operations:

- `list_project_records(projects_root, include_lifecycles, include_home=false)`
- `read_project_lifecycle(project_dir, project_name)`
- `set_project_lifecycle(projects_root, project_name, lifecycle, force=false)`
- `filter_project_names(projects_root, include_lifecycles)`

Rules:

- Missing metadata means `active`.
- Unknown lifecycle values degrade to `active` with a warning for compatibility, but `set` only writes valid values.
- `home` is omitted unless explicitly requested.
- Records are sorted by project name.
- Writes are atomic and lock on `project.json.lock` or an equivalent sidecar lock.
- Archive/close transitions validate no live claims unless `force=true`.

## CLI Shape

Add a new top-level `sase project` command rather than extending `workspace`. Workspace commands manage checkouts;
project lifecycle affects ChangeSpecs, agents, xprompts, mobile helpers, and beads.

Recommended commands:

```bash
sase project list [-s active|archived|closed|all] [-j|--json]
sase project set-status <project> -s active|archived|closed [-f|--force]
sase project show <project> [-j|--json]
```

Convenience aliases can be added later:

```bash
sase project activate <project>
sase project archive <project>
sase project close <project>
```

Follow existing CLI convention by giving every option both a short and long form where possible.

## TUI Shape

Do not overload the existing Ctrl+D "delete project" behavior. Deletion is destructive; lifecycle is reversible metadata.

Recommended TUI pieces:

- Add a Project Management modal listing all projects with lifecycle, workspace health, active claim count, and
  ChangeSpec counts.
- Provide actions to mark selected project active, archived, or closed.
- Default ProjectSelectModal should show active projects and active ChangeSpecs only.
- Add a filter/toggle in the management modal for active, archived, closed, and all.
- When lifecycle changes, invalidate/reload ChangeSpecs, project selector contents, and agent/project filters.
- Add a file-watch or refresh pulse for `project.json` so CLI changes are picked up while the TUI is running.

The existing ProjectSelectModal can still be reused for launch selection, but it should not be the only place to reopen
archived/closed projects because those projects are hidden by default.

## Integration Points

Initial integration should replace broad project scans with a shared active-project list:

- `find_all_changespecs` and `ChangeSpecSnapshotCache.find_all_changespecs_cached`: default to active projects, with an
  internal option for all statuses.
- `ProjectSelectModal` and `project_discovery`: list active launch targets by default; management modal lists all.
- Agent loading:
  - Read `RUNNING` claims across all lifecycle states for safety.
  - Load completed/history artifacts from active projects by default.
  - Extend Rust index/query APIs with lifecycle or project filters, because the persistent index currently has no
    project-status predicate.
- Xprompt catalog: load project-local xprompts from active projects by default; allow explicit archived project lookup.
- Mobile helpers: all-known project scope should mean active by default, with explicit archived/closed support only when
  an operation is read-only.
- Bead helpers: all-known bead reads should use active projects by default; explicit project reads can report lifecycle in
  the response and block work/launch operations for archived/closed projects.
- Workspace inference from CWD should still resolve archived/closed projects so users can reactivate them, but launch/work
  operations should enforce lifecycle policy after resolution.

## Migration Plan

1. Add core lifecycle read/list/set APIs and Python facade.
2. Add CLI `sase project list/show/set-status`.
3. Update project discovery and ChangeSpec scans to use active projects by default.
4. Update agent artifact scans/index queries to support project lifecycle filters, keeping active runtime rows visible.
5. Add the TUI project management modal and refresh behavior.
6. Update docs/configuration and mobile gateway docs.

No bulk migration is needed because missing metadata means active. A future maintenance command can materialize
`project.json` for all known projects if users want explicit files.

## Test Plan

- Rust unit tests for metadata parsing, missing-file default, unknown-value warning, sorted listing, and atomic writes.
- Python facade tests for CLI JSON shape and legacy `.gp` ProjectSpec fallback.
- ChangeSpec scan tests proving archived/closed projects are hidden by default and included when requested.
- TUI modal tests for lifecycle actions and status filters.
- Agent loader tests proving live agents from archived/closed projects still appear.
- Mobile/bead/xprompt tests proving all-known defaults exclude inactive projects while explicit project requests are
  handled intentionally.

## Decision

Use per-project `project.json` lifecycle metadata with missing-as-active compatibility, implement the domain contract in
Rust core, add `sase project` CLI commands, and add a dedicated TUI Project Management modal. This keeps project state
local and dynamic without disturbing existing ProjectSpec text, artifact paths, or user config files.
