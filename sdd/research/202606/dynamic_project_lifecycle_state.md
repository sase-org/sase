# Research: Dynamically Configurable Project Lifecycle State (active / archived / closed)

**Date:** 2026-06-01
**Status:** Research — no implementation yet
**Goal:** Let users configure which projects are *active* vs *archived* vs *closed*, from both the
command line and the `sase ace` TUI.

---

## 1. Problem Statement

Today SASE has no concept of a project *lifecycle state*. A "project" is implicit: any directory under
`~/.sase/projects/<name>/` that contains a valid project spec file. Users accumulate projects over time and
have no way to mark a project as finished (archived/closed) so it stops cluttering pickers and listings, nor
to reactivate one later. We want a first-class, mutable project state with three values — **active**,
**archived**, **closed** — settable from the CLI and the TUI.

---

## 2. How Projects Work Today (findings)

### 2.1 No project object, no project status

There is **no `Project` class or struct** anywhere in the codebase. Projects are defined purely by
convention:

- A project is a directory `~/.sase/projects/<name>/` (`src/sase/core/paths.py:55` — `sase_projects_dir()`).
- It is "real"/launchable if it has a valid project spec file and a workspace.

Status/lifecycle concepts exist only at *lower* levels, **never for projects**:

- **Beads** have `Status.OPEN | IN_PROGRESS | CLOSED` (`src/sase/bead/model.py:9`).
- **ChangeSpecs** have a free-text `status` field (`WIP → Draft → Ready → Mailed → Submitted`, plus
  `Archived`/`Reverted`) (`src/sase/ace/changespec/models.py:464`).
- "Archive" today means a *terminal ChangeSpec* gets moved from `<project>.sase` to
  `<project>-archive.sase` (`src/sase/ace/changespec/archive.py:31`). This is **per-ChangeSpec, not
  per-project.**

So "archived project" / "closed project" are brand-new concepts we are introducing.

### 2.2 Project spec file = the natural home for project metadata

ProjectSpec files (`~/.sase/projects/<name>/<name>.sase`, legacy `.gp`) already carry optional
**project-level metadata** in a header region before the first `NAME:` line
(`docs/project_spec.md:60`):

- `BARE_REPO_DIR:` — bare git repo path
- `WORKSPACE_DIR:` — primary checkout
- `RUNNING:` — live workspace claims (managed by SASE)

These are parsed by narrow line-scanning helpers and written back in place under a lock — this is the
**exact precedent** a new `STATUS:` (or `STATE:`) project field would follow:

- Read: `parse_workspace_dir()` / `parse_bare_repo_dir()` — scan lines until first `NAME:`, split on
  `:` (`src/sase/workspace_provider/utils.py:64`, `:93`).
- Write: `set_workspace_dir()` — `changespec_lock(project_file)`, read content, update-in-place or insert,
  atomic write (`src/sase/workspace_provider/utils.py:122`).
- Path resolution (canonical `.sase` preferred, `.gp` fallback): `preferred_project_spec_path()`
  (`src/sase/ace/changespec/project_spec_path.py:72`).

There is a Rust mirror of the path helpers in
`../sase-core/crates/sase_core/src/project_spec.rs` — relevant to the backend-boundary decision (§6).

### 2.3 Project discovery / listing

- `list_launchable_projects()` scans `~/.sase/projects/`, skips `home`, requires a valid spec file with an
  existing `WORKSPACE_DIR` and a detectable workflow type
  (`src/sase/ace/tui/modals/project_discovery.py:13`). This is the **single chokepoint** where a state
  filter would be applied.
- There is **no `sase project` CLI command today.** The only project-adjacent CLI surface is
  `sase changespec` (`--project-file`, `migrate-extension`) and `sase workspace`
  (`src/sase/main/parser_commands.py`). Project management is otherwise TUI-only.

### 2.4 Configuration system (why config files are the *wrong* store)

- Config is a **5-layer read-only merge** (`default_config.yml` → plugin defaults → `~/.config/sase/sase.yml`
  → overlays → `./sase.yml`), parsed as plain dicts (`src/sase/config/core.py`). **Nothing writes back to
  `sase.yml`.**
- Runtime-mutable state is conventionally kept in **separate state files**, not in config. The canonical
  example is the LLM temporary override: a JSON file at `~/.sase/llm_override.json` written atomically with
  a temp file + `os.replace()` (`src/sase/llm_provider/temporary_override.py`). Beads similarly use
  `beads/config.json`.

**Takeaway:** project state must live in a mutable on-disk store, *not* in the YAML config merge chain.

### 2.5 TUI surfaces

- `ProjectSelectModal` lists projects (`[P] name`), home (`[H]`), in-flight CLs (`[C]`), optional `[*] ALL`;
  it already filters by ChangeSpec status when listing CLs and already has destructive project actions
  (`ctrl+d` delete) (`src/sase/ace/tui/modals/project_select_modal.py:47`).
- The main TUI already has the **show/hide filter pattern** we'd reuse: `hide_reverted` / `hide_submitted`
  reactives toggled by `.` and `x`, applied at load time
  (`src/sase/ace/tui/app.py:143`, `src/sase/ace/tui/actions/changespec/_core.py:140`).
- State-mutating actions follow a mixin + background-task pattern (`StatusActionsMixin.action_change_status`,
  `_submit_background_task`) (`src/sase/ace/tui/actions/status.py:137`).

---

## 3. Requirements / Semantics to Pin Down

Proposed semantics (open for confirmation — see §7):

| State | Meaning | Default visibility | Launchable? | Reversible? |
|-------|---------|--------------------|-------------|-------------|
| **active** | Normal, in-use project (default when field absent) | Shown | Yes | — |
| **archived** | Set aside; not in active rotation but expected to return | Hidden behind a toggle | Yes (re-activates on launch? or stays archived) | Yes → active |
| **closed** | Done / wound down; kept for history | Hidden | No (blocked or warns) | Yes → active |

The main open question is whether **archived** and **closed** need to be distinct, or whether one
"inactive" state suffices (§7).

---

## 4. Design Options — Where to Store State

### Option A — `STATUS:`/`STATE:` field in the ProjectSpec header *(recommended)*

Add a project metadata field before the first `NAME:` line, e.g. `STATE: archived`. Absent = `active`.

- **Pros:** Co-located with the project; human-readable; survives alongside ChangeSpecs; reuses the existing
  metadata read/write precedent (`parse_workspace_dir`/`set_workspace_dir`) and the existing
  `changespec_lock` + atomic write; discovery already opens this exact file, so filtering is nearly free; no
  new file to keep in sync with directory reality.
- **Cons:** Writer must preserve ChangeSpec blocks (already solved by `set_workspace_dir` and the archive
  mover); requires touching the metadata parser in **both** Python and (per boundary rule) Rust core.
- **Migration:** None. Missing field defaults to `active`; legacy `.gp` files work via existing fallback.

### Option B — Central registry file (`~/.sase/projects/registry.json`)

A single JSON map `{ "<project>": "archived", ... }`, atomic-written like `llm_override.json`.

- **Pros:** No ProjectSpec parser changes; trivial atomic writes; one place to list/filter; matches the
  established mutable-state-file convention.
- **Cons:** Second source of truth that can drift from the directory listing (deleted/renamed projects leave
  stale entries; needs reconciliation); not co-located; central-file write contention if many writers.

### Option C — Per-project sidecar (`~/.sase/projects/<name>/state.json`)

- **Pros:** Co-located; isolated atomic writes (no central lock); no ProjectSpec parser changes.
- **Cons:** Yet another file format/concept; scattered; listing requires scanning every dir (discovery
  already does this, so cost is low).

### Option D — In `sase.yml` config

Rejected. The config merge chain is read-only by design; nothing writes back to it, and programmatic edits
would lose comments and fight the layering. Contradicts the established pattern (§2.4).

**Recommendation:** **Option A.** It introduces zero new files, reuses a well-worn read/write precedent, and
puts the filter exactly where discovery already reads. Option B is the fallback if we want to avoid editing
the ChangeSpec store file at all.

---

## 5. Design Options — Surfaces

### 5.1 CLI (`sase project` — new command group)

Follow the `register_*_parser` → `create_parser` → `entry.py` dispatch pattern
(`src/sase/main/parser_commands.py`, `parser.py`). Remember the **short+long option** convention from
`memory/short/gotchas.md`.

```
sase project list [-s|--state active|archived|closed|all]   # default: active (or active+archived)
sase project show <name>                                    # print current state + metadata
sase project set-state <name> <active|archived|closed>      # core mutation
# Convenience aliases:
sase project archive <name>
sase project close   <name>
sase project activate <name>
```

A single `set-state` verb keeps the state machine in one place; the aliases are thin wrappers for
ergonomics. `list` reuses `list_launchable_projects()` + a state filter.

### 5.2 TUI (`sase ace`)

Extend the existing `ProjectSelectModal`:

1. **Render state** in each `[P]` row (e.g. dim badge `[P] name (archived)`), like CLs already show
   `[C] name [Ready]`.
2. **State-change keybindings** on the selected project, mirroring the existing `ctrl+d` delete /
   `ctrl+g` edit bindings — e.g. `ctrl+r` activate, `ctrl+e` archive, `ctrl+x` close — routed through a
   background task (`_submit_background_task`) calling the same backend mutation as the CLI.
3. **Visibility toggle** mirroring `hide_reverted`/`hide_submitted`: a reactive `hide_inactive_projects`
   that hides archived+closed projects from the modal by default, toggled by a key. Apply the filter in
   `_load_items()` (`project_select_modal.py:70`).
4. Update the help modal, footer keybindings, and `default_config.yml` keymaps per the `src/sase/ace`
   AGENTS.md rules (help popup, 57-char box width, footer conditional-keymap convention) and
   `memory/short/gotchas.md` (default keymap config).

---

## 6. Rust Core Backend Boundary

Per `memory/short/rust_core_backend_boundary.md`, the litmus test ("would a web app / CLI / other frontend
need this to match the TUI?") is clearly **yes** — project state and the legal transitions between active →
archived → closed are shared domain behavior. So:

- The **state enum, the parse/serialize of the project-spec metadata field, and the transition rules** belong
  in `../sase-core/crates/sase_core` (alongside the existing `project_spec.rs` path helpers), exposed through
  the `sase_core_rs` binding.
- The Python CLI handler and the TUI action should be **thin callers** of that binding.
- Pragmatic note: the *current* metadata helpers (`parse_workspace_dir`, `set_workspace_dir`) still live in
  Python (`workspace_provider/utils.py`) and have **no Rust equivalent yet**. So there is a real choice:
  - **(6a)** Do it right: add the state field read/write/transition to Rust core now and call through. Higher
    up-front cost, correct per the boundary rule.
  - **(6b)** Prototype in Python following the `set_workspace_dir` precedent, then migrate to core. Faster,
    but accrues boundary debt and a second parser to reconcile.
  Recommendation leans **6a** for the state-machine logic (it's small and genuinely cross-frontend), while
  the TUI rendering/keybindings stay Python.

---

## 7. Open Questions (for the user)

1. **Do we need three states or two?** Is the *archived* vs *closed* distinction meaningful to you, or is a
   single "inactive/hidden" state enough? (Proposed distinction in §3: archived = paused/returnable, closed =
   done/history, non-launchable.)
2. **Launch behavior:** Should launching/selecting an archived or closed project be **blocked**, **warn +
   auto-reactivate**, or **silently allowed**?
3. **Default `list` / picker scope:** Show only `active` by default, or `active + archived` (hiding only
   `closed`)?
4. **Storage:** Confirm Option A (ProjectSpec metadata field) vs Option B (central registry). Affects whether
   we touch the ChangeSpec store file.
5. **Boundary timing:** Build the state machine in Rust core now (6a) or prototype in Python first (6b)?

---

## 8. Recommended Direction (summary)

- **Store** project state as a `STATE:` metadata field in the ProjectSpec header (Option A), defaulting to
  `active` when absent.
- **Model** the state enum + transitions + spec-field read/write in **sase-core Rust**, exposed via binding
  (Option 6a).
- **CLI:** new `sase project` group — `list`, `show`, `set-state`, plus `archive`/`close`/`activate` aliases
  (short+long options).
- **TUI:** extend `ProjectSelectModal` to render state, add per-project state-change keybindings via the
  existing background-task path, and add a `hide_inactive_projects` visibility toggle mirroring
  `hide_reverted`. Keep help modal, footer, and `default_config.yml` in sync.
- Resolve the §7 questions (especially #1 and #4) before implementation.

---

## 9. Key References

| Concern | File:line |
|---|---|
| Projects dir root | `src/sase/core/paths.py:55` |
| Project metadata read precedent | `src/sase/workspace_provider/utils.py:64,93` |
| Project metadata write precedent | `src/sase/workspace_provider/utils.py:122` |
| Spec path resolution (.sase/.gp) | `src/sase/ace/changespec/project_spec_path.py:72` |
| Project discovery / list | `src/sase/ace/tui/modals/project_discovery.py:13` |
| ProjectSpec format docs | `docs/project_spec.md:60` |
| ChangeSpec archive (per-CS, for contrast) | `src/sase/ace/changespec/archive.py:31` |
| Mutable-state-file precedent | `src/sase/llm_provider/temporary_override.py` |
| Config merge (read-only) | `src/sase/config/core.py` |
| CLI parser registration | `src/sase/main/parser_commands.py`, `src/sase/main/parser.py` |
| TUI project modal | `src/sase/ace/tui/modals/project_select_modal.py:47` |
| TUI hide/show filter pattern | `src/sase/ace/tui/app.py:143`, `actions/changespec/_core.py:140` |
| TUI state-mutation pattern | `src/sase/ace/tui/actions/status.py:137` |
| Rust spec path mirror | `../sase-core/crates/sase_core/src/project_spec.rs` |
| Backend boundary rule | `memory/short/rust_core_backend_boundary.md` |
