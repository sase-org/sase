---
create_time: 2026-06-29 07:24:25
status: done
prompt: sdd/prompts/202606/project_name_field.md
---
# Configurable `PROJECT_NAME` Field for Project Specs

## Context

When `#gh` is given `<github_org>/<github_repo>` and no project yet exists for the canonical key
`gh_<github_org>__<github_repo>` (note: the on-disk directory uses a **double** underscore between org and repo), the
GitHub workspace plugin creates the project record and then attaches a short **alias** equal to `<github_repo>` so the
shorthand `#gh:<github_repo>` keeps working.

The problem: a project's _identity_ is currently always its on-disk **directory name**. So GitHub projects are shown to
the user with their verbose canonical key (e.g. `gh_acme__widgets`) even though a friendly alias exists. The user wants
GitHub projects to be _named_ `<github_repo>` everywhere they are surfaced, not merely aliased.

### How identity works today (established by exploration)

- The Rust core (`sase-core`, `crates/sase_core/src/project_spec.rs`) discovers projects by walking `~/.sase/projects/`.
  Each record's `project_name` is taken **verbatim from the directory name**; it is not stored in the spec file. The
  `NAME:` line in a spec file is only a metadata-header boundary marker, not a project name.
- `ProjectRecordWire` already carries both the logical handle (`project_name`) **and** absolute storage paths
  (`project_dir`, `project_file`, `archive_file`). The recognized metadata-header fields are `PROJECT_STATE:`,
  `WORKSPACE_DIR:`, `PROJECT_ALIASES:`, and `RUNNING:` (all parsed before the `NAME:` boundary).
- The codebase deeply assumes **`project_name == directory name`**. `is_valid_sase_project_name()` in
  `src/sase/core/paths.py` literally asserts `project_dir.name == project_name`, and many call sites build paths as
  `sase_projects_dir() / project_name / ...` (memory logs, artifact paths, change actions, workflow utils, the bare-git
  init plugin, etc.).
- Reference and launch resolution flows through one chokepoint: `resolve_project_alias_ref(ref)` in
  `src/sase/project_aliases.py` maps an alias to its canonical (directory) `project_name`, and
  `canonicalize_project_aliases_in_prompt()` rewrites `#gh:<alias>` to `#gh:<canonical>` before launch, history, and
  artifact writes. `launch_projects.py` and `agent_artifact_paths.py` both resolve through this chokepoint before
  touching the filesystem.
- The GitHub first-use flow lives in the `sase-github` plugin (`src/sase_github/workspace_plugin.py`):
  `_resolve_repo_path_ref()` derives the canonical key via `_canonical_project_name_base()` = `gh_<owner>__<repo>` (with
  a `-2`, `-3` … suffix on the canonical key itself if that directory is already taken for a different workspace),
  writes `WORKSPACE_DIR`, then `_ensure_useful_repo_alias()` allocates and writes the alias.

## Goal / Target Behavior

Introduce a new, configurable project-spec metadata field `PROJECT_NAME:` that holds a project's **logical name**,
decoupled from its on-disk directory key.

- A project's `PROJECT_NAME` is treated as the project name everywhere it is **shown, referenced, or addressed** (TUI,
  CLI, `#gh:<name>` refs, agent rows, notifications).
- The on-disk **directory key** (the spec file's directory/stem) remains the project's storage identity and is the only
  thing used to compute filesystem paths.
- For **new** GitHub projects, the plugin sets `PROJECT_NAME: <github_repo>` **instead of** adding an alias.
- If `<github_repo>` is already in use as a project name, alias, or another project's `PROJECT_NAME`, allocate
  `<github_repo>_<N>` where `N` is the first **positive integer** (starting at `1`: `foo_1`, `foo_2`, …) producing an
  unused name. This lets `acme/widgets` and `globex/widgets` coexist as `widgets` and `widgets_1`.
- Projects without a `PROJECT_NAME` (all existing projects, the `home` project) are unaffected: their logical name
  remains the directory name.

## Key Design Decision

**Keep `project_name` equal to the directory key; add `PROJECT_NAME` as a separate logical name surfaced as a primary
alias-equivalent.** Concretely:

- Parse `PROJECT_NAME:` in Rust into a new wire field (`display_name: Option<String>`). The record's existing
  `project_name` stays equal to the directory name (the storage invariant the whole codebase enforces is preserved).
- Register each project's `display_name` in the existing alias resolution map as `display_name -> <directory key>`, with
  the same uniqueness guarantees as aliases. This makes `#gh:widgets` resolve to `gh_acme__widgets` through the
  already-existing `resolve_project_alias_ref` / `canonicalize_project_aliases_in_prompt` chokepoint — so **every
  filesystem, launch, history, and artifact path keeps working unchanged**, because they all resolve a ref to the
  directory key before computing a path.
- Add a single accessor, `effective_project_name(record) = record.display_name or record.project_name`, and use it at
  the (enumerable) **display/identity** surfaces so users see `widgets` instead of `gh_acme__widgets`.

### Why not make `project_name` itself the logical name?

The literal phrasing ("treated as the project name in all ways except the spec file path") suggests flipping
`project_name` to the logical value and redirecting only path computation to the directory key. We deliberately do
**not** do this:

- `project_name == directory name` is an invariant enforced by validation (`is_valid_sase_project_name` checks
  `project_dir.name == project_name`) and assumed by ~180 files. Breaking it means every un-audited
  `sase_projects_dir() / project_name` silently writes to a **non-existent / wrong** directory — a data-loss failure
  mode.
- With the chosen design, the failure mode of missing a surface is **cosmetic** (a verbose name shows somewhere),
  trivially fixable, never corrupting storage.
- The user-visible behavior is identical: `PROJECT_NAME` is shown and is addressable everywhere; only the internal
  storage handle stays on the directory key.

This keeps the change additive and safe while fully delivering the requested behavior.

## Uniqueness & Collision Rules

A single "occupied names" namespace governs both aliases and project names:

```
occupied = {every project's directory key} ∪ {every alias} ∪ {every PROJECT_NAME}
```

- A `PROJECT_NAME` must be a valid SASE project name and must not collide with any entry in `occupied` belonging to a
  _different_ project (it may equal its own directory key, which is a redundant no-op).
- Allocation for new GitHub projects: try `<repo>`; while taken, try `<repo>_1`, `<repo>_2`, … (underscore separator,
  first free positive integer). This is distinct from the existing **alias** allocator, which uses a hyphen and starts
  at `-2`; the two allocators stay separate so each matches its documented contract.
- Validation is enforced in both layers: Rust emits parse warnings for colliding `PROJECT_NAME` values (mirroring the
  existing alias-collision warnings), and the Python alias-map builder rejects conflicts so launch-time resolution stays
  deterministic.

## Phase 1 — `sase-core`: Parse and Expose `PROJECT_NAME`

Primary repo: `sase-core` (Rust). Files: `crates/sase_core/src/project_spec.rs`, `crates/sase_core_py/src/lib.rs`.

Work:

- Add a `PROJECT_NAME:` field prefix constant alongside the existing metadata-header prefixes.
- Add `read_project_name_from_content()` mirroring `read_project_aliases_from_content()`: read the first `PROJECT_NAME:`
  line before the `NAME:` boundary, trim, validate with the existing `is_valid_sase_project_name`, and emit a parse
  warning on an invalid value or duplicate occurrences.
- Add `display_name: Option<String>` to `ProjectRecordWire` (serde `default`, appended after existing fields to keep the
  wire stable) and populate it in `build_project_record()`. Keep `project_name` derived from the directory name and keep
  `system_managed`/`home` detection keyed on the directory name.
- Extend the project-name/alias collision detection so a `PROJECT_NAME` that duplicates another project's directory key,
  alias, or `PROJECT_NAME` produces a parse warning.
- Add `apply_project_name_update(content, name: Option<&str>)` modeled on `apply_project_aliases_update()`: set/replace
  the `PROJECT_NAME:` line, insert it in the correct header position when absent, or remove it when `name` is empty;
  validate the value; preserve newline style.
- Expose `apply_project_name_update` through the PyO3 layer (`py_apply_project_name_update`) and register it. The new
  `display_name` field flows to Python automatically via the existing serde serialization in `py_list_project_records`.
- Decide on the wire schema version: adding an optional, defaulted field is backward compatible, but bump the
  `ProjectRecordWire` schema version (and the matching Python constant) if we want explicit signaling; document the
  choice.
- Coordinate the `sase-core-rs` package version with the `sase-core-rs>=0.2.0,<0.3.0` pin in `sase`'s `pyproject.toml`
  and the `tools/validate_sase_core_rs_version` check (a compatible minor bump within `0.2.x`).

Tests (Rust, in `project_spec.rs`):

- `read_project_name_from_content`: present/absent, invalid value warns, duplicate occurrences warn.
- `apply_project_name_update`: insert into a spec with no field, replace existing, remove on empty, header ordering and
  newline preservation.
- `list_project_records` populates `display_name` from the spec and leaves it `None` when absent.
- Collision warnings for a `PROJECT_NAME` clashing with another project's name/alias/`PROJECT_NAME`.

Validation: build the crate and run its test suite in the opened `sase-core` workspace.

## Phase 2 — `sase`: Wire, Accessor, Resolution, Allocation

Primary repo: `sase` (Python).

Work:

- `src/sase/core/project_lifecycle_wire.py`: add `display_name: str | None = None` to `ProjectRecordWire`; populate it
  in `project_record_from_dict()`; bump `PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION` if Phase 1 bumped the Rust schema.
- `src/sase/core/project_lifecycle_facade.py`: add `apply_project_name_update(content, name)` wrapping the new Rust
  binding.
- Add `effective_project_name(record)` (returns `display_name or project_name`) in a shared location (wire module or a
  small helper), plus a reverse `display_name_for_directory_key(key)` helper for surfaces that only have the stored
  directory key (e.g. agent rows).
- `src/sase/project_aliases.py`:
  - Register each project's `display_name` as a ref in `_project_alias_map_from_records()` mapping to that project's
    directory-key `project_name`, subject to the same uniqueness checks as aliases (reject collisions with names,
    aliases, or other `PROJECT_NAME` values). This makes `resolve_project_alias_ref()` and
    `canonicalize_project_aliases_in_prompt()` handle `PROJECT_NAME` automatically — the keystone that keeps all
    path/launch logic working.
  - Include `display_name` values in the occupancy set used by allocation/validation.
  - Add `allocate_project_name(desired_base, records)` using the underscore separator and first-free positive integer
    starting at `1`.
  - Add locked mutators `set_project_name_locked(project, name)` and `ensure_project_name_locked(project, name)` built
    on `apply_project_name_update` and the existing ProjectSpec lock (same pattern as the alias mutators).

Tests (Python):

- Wire round-trips `display_name`; `effective_project_name` falls back correctly.
- Alias map includes `display_name -> directory key`; `resolve_project_alias_ref("widgets")` returns the directory key;
  `canonicalize_project_aliases_in_prompt` rewrites `#gh:widgets` to the canonical key.
- Uniqueness: a `PROJECT_NAME` colliding with another project's name/alias/`PROJECT_NAME` is rejected.
- `allocate_project_name`: free base, then `_1`, `_2`; collisions counted across names, aliases, and `PROJECT_NAME`
  values; invalid base rejected.
- Locked setters write/replace/remove `PROJECT_NAME` and preserve other fields.

Validation: `just install && just check` in the `sase` workspace (this rebuilds `sase_core_rs` from the sibling
`sase-core`, so Phase 1 must be present on disk).

## Phase 3 — `sase-github`: Set `PROJECT_NAME` on First Use

Primary repo: `sase-github`. File: `src/sase_github/workspace_plugin.py`.

Work:

- Replace `_ensure_useful_repo_alias()` with logic that, for a newly created canonical project, allocates
  `<github_repo>` via `allocate_project_name` (underscore/`_<N>` collisions) and writes it with
  `set_project_name_locked` / `ensure_project_name_locked` — **no alias is added**.
- Keep the existing guards: skip when `<github_repo>` is not a valid SASE project name or would equal the canonical
  directory key (redundant), in which case the directory key remains the displayed name.
- Keep canonical **directory-key** allocation (`_allocate_canonical_project_name`, `gh_<owner>__<repo>` with `-N`
  directory suffixing) unchanged — that governs the storage path, which is orthogonal to `PROJECT_NAME`.
- Keep `ResolvedRef.project_name` equal to the directory key (storage identity); the friendly name is surfaced via the
  resolution/display layers, not by changing what is stored.
- Preserve idempotency: the existing reuse-by-`WORKSPACE_DIR` short-circuit means a repeated first-use does not
  re-allocate or duplicate a `PROJECT_NAME`.

Tests (update `tests/test_workspace_plugin.py::TestResolveGhRef`):

- First use of `alice/myrepo` writes `PROJECT_NAME: myrepo` (and **no** `PROJECT_ALIASES`).
- Duplicate basename: `acme/widgets` → `PROJECT_NAME: widgets`; later `globex/widgets` → distinct directory key with
  `PROJECT_NAME: widgets_1`.
- Legacy basename project reuse (matching `WORKSPACE_DIR`) is still reused without adding a name.
- Canonical directory-key collision still suffixes the **directory** (`gh_alice__widgets-2`) while `PROJECT_NAME` stays
  `widgets`.
- `#gh:widgets` shorthand resolves to the canonical project.

Validation: run the `sase-github` check/test suite in its opened workspace.

## Phase 4 — Surface the Logical Name (Display/UX)

Primary repo: `sase` (with any `sase-github`/integration display touch-ups).

Goal: show `effective_project_name` wherever a project is presented or addressed, so the verbose key stops leaking.

Work:

- TUI project surfaces: project-management modal/rendering, projects pane, project-discovery list, and the alias-editor
  header (`src/sase/ace/tui/modals/project_management_rendering.py`, `project_management_actions.py` — excluding the
  path construction at its line ~420, which must stay on the directory key — `projects_pane.py`,
  `project_alias_editor_modal.py`).
- Agents tab: render the project column for agent rows via `display_name_for_directory_key` (agent metadata continues to
  store the directory key for correct grouping/paths). Mind TUI performance — cache the directory-key → display-name map
  per refresh rather than resolving per row (see `memory/tui_perf.md`).
- CLI: have `sase project` subcommands accept a `PROJECT_NAME` (or alias) for the project argument by resolving it to
  the directory key first (today `project_handler._get_project_record` matches the directory key only; this also closes
  the existing gap where aliases are not accepted as CLI args). Listings show the logical name with the directory key as
  a secondary detail.
- Notifications / any agent-context surfaces that print the project name: show the logical name.

Tests:

- Rendering/CLI snapshot or unit tests asserting the logical name appears and the directory key is no longer the primary
  label for a project with `PROJECT_NAME`.

Validation: `just install && just check` in `sase` (includes the PNG visual snapshot suite for TUI changes).

## Phase 5 — Documentation & Compatibility

Primary repos: `sase`, `sase-github`.

Work:

- Document the `PROJECT_NAME` field in the project-spec docs (`docs/project_spec.md`): purpose, that it is the logical
  name, that the directory key remains the storage identity, validation, and uniqueness/collision rules.
- Update `docs/xprompt.md` (or equivalent) to explain that `#gh:<repo>` resolves via the project's `PROJECT_NAME`, with
  a duplicate-basename example (`widgets` vs `widgets_1`).
- Update `sase-github` docs to describe first-use `PROJECT_NAME` allocation replacing the old auto-alias.
- Compatibility notes:
  - Existing projects and existing auto-aliased GitHub projects are unchanged and keep resolving via their alias; no
    migration or rename is performed (explicit non-goal). A follow-up could optionally migrate legacy auto-aliases to
    `PROJECT_NAME`, but it is out of scope here.
  - `home` and any project without `PROJECT_NAME` continue to display by directory name.

## Cross-Repo Sequencing & Risks

- **Build sequencing**: Phase 1 (Rust) must land before Phase 2 can call the new binding. Local `just install` in `sase`
  rebuilds `sase_core_rs` from the sibling `sase-core`, so the validated order is: implement Phase 1 in `sase-core`,
  then Phase 2 in `sase`. Coordinate the `sase-core-rs` version with the `pyproject.toml` pin and
  `tools/validate_sase_core_rs_version`.
- **Storage-invariant risk**: the design preserves `project_name == directory name`, so no path code changes; the main
  guard is ensuring `display_name` is _only_ used at display/identity surfaces and never substituted into a path. Add an
  explicit test that a project with a `PROJECT_NAME` still resolves all per-project paths (artifacts, memory logs,
  changespec) under its **directory key**.
- **Resolution races**: allocation and writes happen while holding the ProjectSpec lock with a re-read of records before
  writing (reuse the existing alias-mutation locking and retry-on-conflict pattern).
- **Uniqueness drift after manual edits**: the alias-map builder rejects (rather than guesses) conflicts among names,
  aliases, and `PROJECT_NAME` values, surfaced as Rust parse warnings and Python validation errors, so resolution stays
  deterministic.
- **Display coverage**: missing a surface only shows a verbose name (cosmetic, incrementally fixable); enumerate the
  known surfaces in Phase 4 and prefer a shared accessor so future surfaces inherit the behavior.

## Out of Scope / Non-Goals

- Renaming the internal `project_name` field or relocating any project storage directory.
- Migrating existing alias-based GitHub projects to `PROJECT_NAME`.
- Changing how the canonical directory key (`gh_<owner>__<repo>`) is derived or suffixed.
