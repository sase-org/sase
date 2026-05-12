---
create_time: 2026-05-12 09:47:15
status: done
prompt: sdd/prompts/202605/project_spec_extension_sase.md
bead_id: sase-33
tier: epic
---
# Change Project Spec Extension From `.gp` To `.sase`

## Goal

Change SASE project spec files from:

- active: `~/.sase/projects/<project>/<project>.gp`
- archive: `~/.sase/projects/<project>/<project>-archive.gp`

to:

- active: `~/.sase/projects/<project>/<project>.sase`
- archive: `~/.sase/projects/<project>/<project>-archive.sase`

The work spans the main Python repo, the Rust core repo, and maintained plugins (`sase-github`, `sase-telegram`,
`sase-nvim`). It should be implemented in phases because the extension appears in path construction, project discovery,
archive movement, tests/fixtures, docs, and editor integration.

## Initial Findings

Relevant repositories:

- `sase_105`: main Python/TUI/CLI repo.
- `../sase-core`: Rust backend/domain repo. It already has unrelated modified files in
  `crates/sase_core/src/notifications/store.rs`, `crates/sase_core/src/notifications/wire.rs`, and
  `crates/sase_core/tests/notification_store_parity.rs`; implementation agents must preserve those edits.
- `../sase-github`: GitHub VCS/workspace plugin.
- `../sase-telegram`: Telegram/mobile plugin.
- `../sase-nvim`: Neovim filetype/syntax plugin.

Important current hotspots:

- Main repo path creation/discovery:
  - `src/sase/workflows/utils.py`
  - `src/sase/ace/changespec/__init__.py`
  - `src/sase/ace/changespec/archive.py`
  - `src/sase/ace/changespec/cache.py`
  - `src/sase/ace/tui/models/_loaders/_running_loaders.py`
  - `src/sase/workspace_provider/plugins/bare_git_init.py`
  - `src/sase/workspace_provider/plugins/bare_git_ref.py`
  - `src/sase/workspace_provider/plugins/cd_workspace.py`
  - `src/sase/xprompt/loader.py`
  - `src/sase/agent/launch_cwd.py`
  - `src/sase/agent/launch_spawn.py`
  - `src/sase/agent/running.py`
  - `src/sase/main/utils.py`
  - `src/sase/main/bead_fast_path.py`
  - `src/sase/bead/*`
  - several TUI launch, project-select, status, sync, and rename actions.
- Main repo tests/fixtures:
  - `tests/core_golden/myproj.gp`
  - `tests/core_golden/myproj-archive.gp`
  - many tests build temporary `*.gp` paths.
- Rust core:
  - `crates/sase_core/src/parser.rs` strips extension for `project_basename`.
  - `crates/sase_core/src/agent_scan/scanner.rs` constructs `<project>.gp`.
  - Rust test fixtures are `crates/sase_core/tests/fixtures/*.gp`.
  - gateway/core tests include many expected `*.gp` strings.
- Plugin repos:
  - `sase-github/src/sase_github/workspace_plugin.py` resolves project files and project shorthand using `.gp`.
  - `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py` falls back to `~/.sase/projects/*/<project>.gp` for
    workspace discovery.
  - `sase-nvim/ftdetect/sase_gp.lua` detects `.gp` files and syntax docs refer to `.gp`.

## Compatibility Policy

Use `.sase` as the canonical extension after this migration. To avoid an all-at-once data-loss-prone cutover,
implementation should support a short compatibility window:

- New files are created as `.sase`.
- Discovery prefers `.sase`.
- Existing `.gp` files are readable as a fallback where needed during rollout.
- Archive helpers understand both `.sase` and legacy `.gp`, but emit `.sase` paths for new archive destinations.
- A migration command or startup-safe migration helper renames existing project and archive files from `.gp` to `.sase`
  under the existing project-file lock discipline.
- After all repos are updated and the user data migration is complete, a later cleanup can remove fallback support if
  desired.

Do not edit `memory/` files unless the user explicitly approves it. Historical `sdd/` records can also be left alone
unless they are part of active test/docs surfaces; bulk-rewriting historical records creates noise without improving
runtime behavior.

## Phase 1: Shared Project Spec Path Contract

Owner: one agent, main repo plus `../sase-core`.

Purpose: establish the canonical extension and central path helpers so later agents are replacing call sites with shared
APIs instead of scattering another literal extension.

Tasks:

- Add or extend a Python project-spec path helper module in the main repo with:
  - canonical extension `.sase`
  - legacy extension `.gp`
  - active file name helper
  - archive file name helper
  - archive/main conversion helper
  - basename helper for active/archive paths
  - preferred-with-legacy-fallback resolver for existing files.
- Update the existing main-repo archive helper API to delegate to these helpers while preserving old imports such as
  `get_archive_file_path`, `get_main_file_path`, and `is_archive_file`.
- Add Rust-side constants/helpers in `../sase-core` for the project spec extension and archive suffix, and update parser
  basename tests to cover both `.sase` and legacy `.gp`.
- Add focused tests for the helper contract in both repos.

Validation:

- Main repo: targeted pytest for new helper/archive tests.
- `../sase-core`: targeted cargo tests for parser/path helper behavior.

Exit criteria:

- No new runtime call sites are migrated yet except through compatibility wrapper internals.
- Both `.sase` and `.gp` parse to the same project basename.
- Canonical helper output is `.sase`.

## Phase 2: Main Repo Runtime Path Migration

Owner: one agent, main repo only.

Purpose: switch the main SASE runtime to create and discover `.sase` project spec files while keeping legacy `.gp`
readable.

Tasks:

- Replace direct active/archive filename construction with the Phase 1 helpers in non-TUI runtime code:
  - project creation and commit workflow utilities
  - ChangeSpec discovery and cached discovery
  - running-field discovery
  - workspace provider helpers
  - xprompt known-project discovery
  - bead workspace fallback
  - agent launch cwd/spawn/running helpers
  - mobile integration helper paths
  - main command helpers.
- Update temporary-file suffixes used for atomic writes from `.gp` to a neutral or `.sase` suffix where those suffixes
  are only temporary implementation detail.
- Add migration helper/CLI behavior:
  - identify `<project>.gp` and `<project>-archive.gp`
  - skip when corresponding `.sase` file already exists unless contents are identical or a force mode is explicitly
    requested
  - perform atomic rename under lock
  - report migrated/skipped/conflict counts.
- Keep environment/wire field names such as `project_file` unchanged. The request is a filename extension change, not a
  wire-schema rename.

Validation:

- `just install` first in this ephemeral workspace if dependencies may be stale.
- Targeted pytest for project creation, archive movement, parser/discovery, running-field discovery, xprompt known
  projects, bead workspace resolution, and migration behavior.

Exit criteria:

- New project specs created by SASE are `.sase`.
- Existing `.gp` projects still work before migration.
- Migration safely moves real user project specs to `.sase`.

## Phase 3: Main Repo TUI, Workflow, Tests, And User Docs

Owner: one agent, main repo only.

Purpose: finish user-facing Python surfaces and update tests/docs that assert or describe `.gp`.

Tasks:

- Replace direct `.gp` path construction in TUI actions/modals/models:
  - project discovery and selection
  - workflow launch entry points and prompt bar mounting
  - bulk launch
  - mentor review home project paths
  - status/archive/sync/rename/proposal rebase basename derivation
  - file path hints and clipboard labels.
- Rename canonical test fixtures:
  - `tests/core_golden/myproj.gp` to `tests/core_golden/myproj.sase`
  - `tests/core_golden/myproj-archive.gp` to `tests/core_golden/myproj-archive.sase`
  - update inline snapshots/expected file paths where they intentionally model canonical paths.
- Update active user-facing docs:
  - `docs/project_spec.md`
  - `docs/change_spec.md`
  - `docs/workspace.md`
  - `docs/xprompt.md`
  - `docs/rust_backend.md`
  - `docs/mobile_gateway.md`
  - `docs/architecture.md`
  - `docs/notifications.md`
  - `src/sase/xprompts/skills/sase_changespecs.md`
  - CLI help strings that say "project .gp file".
- Update tests that use `.gp` only as arbitrary sample paths to either:
  - use `.sase` when canonical behavior matters, or
  - keep `.gp` when explicitly testing legacy fallback.

Validation:

- `just install`
- `just check`

Exit criteria:

- Main repo has no runtime `.gp` literals except legacy fallback tests, explicit compatibility comments, historical
  records, or user-approved memory updates.
- User-facing docs describe `.sase`.
- Full main-repo check passes.

## Phase 4: Rust Core Full Migration

Owner: one agent, `../sase-core` only.

Purpose: make core backend/domain behavior canonical for `.sase` and keep wire/test parity stable.

Tasks:

- Update agent scan to construct `<project>.sase`, with legacy fallback if the scan needs to find existing project
  files.
- Rename Rust test fixtures:
  - `crates/sase_core/tests/fixtures/myproj.gp` to `myproj.sase`
  - `crates/sase_core/tests/fixtures/myproj-archive.gp` to `myproj-archive.sase`.
- Update expected JSON/wire samples and parser/query/gateway tests to use `.sase` for canonical paths.
- Keep compatibility parser tests for `.gp` basenames.
- Avoid touching the unrelated existing notification edits unless the user explicitly asks.

Validation:

- Run the appropriate `just check` in `../sase-core` if available; otherwise run the relevant cargo test/check commands
  documented in that repo.

Exit criteria:

- Core-generated project-file paths are `.sase`.
- Core parser/query/agent-scan tests pass.
- Legacy `.gp` basename compatibility remains covered.

## Phase 5: Maintained Plugin Repos

Owner: one agent, plugin repos only.

Purpose: align maintained integrations with canonical `.sase` paths.

Tasks:

- `../sase-github`:
  - update project shorthand and repo-path resolution in `src/sase_github/workspace_plugin.py`
  - use main SASE helpers if available through public imports; otherwise mirror the minimal extension/fallback behavior
    locally
  - update tests and docs.
- `../sase-telegram`:
  - update workspace fallback from `~/.sase/projects/*/<project>.gp` to `.sase` preferred with `.gp` fallback
  - update tests and docs.
- `../sase-nvim`:
  - update filetype detection from `.gp` to `.sase`
  - decide whether to retain `sase_gp` as an internal filetype name for compatibility or rename to a clearer
    `sase_project` filetype. If renamed, provide compatibility aliases/autocmds so existing user config does not
    silently stop working.
  - update README/syntax comments.

Validation:

- Run `just check` in each modified plugin repo.
- For `sase-nvim`, run its existing test/check command if present; otherwise verify the Lua pattern matches
  representative `~/.sase/projects/foo/foo.sase` paths.

Exit criteria:

- Maintained plugins create/discover/detect `.sase` project specs.
- Plugin tests and docs are updated.

## Phase 6: Cross-Repo Verification And Cleanup

Owner: one final integration agent.

Purpose: confirm the extension change is complete across repositories and produce any final cleanup patches.

Tasks:

- Run cross-repo searches for:
  - `.gp`
  - `*.gp`
  - `-archive.gp`
  - `sase_gp`
  - `gp_file`
  - `.replace(".gp", "")`
- Classify remaining hits as:
  - intentional legacy compatibility
  - historical docs/SDD/memory not being edited
  - tests explicitly covering legacy behavior
  - missed migration work.
- Fix missed runtime/docs/test hits.
- Run checks in every modified repo:
  - main repo: `just install && just check`
  - each modified plugin repo: `just check`
  - `../sase-core`: repo-specific check command.
- Optionally run the user-data migration on a disposable copy of `~/.sase/projects` first, then on the real directory
  only with explicit user approval.

Exit criteria:

- All modified repos pass their checks.
- Remaining `.gp` references are intentional and documented.
- Real user project data is migrated only after explicit approval.

## Handoff Notes For Implementation Agents

- Prefer helper APIs over raw string replacement. This change is path semantics, not just text substitution.
- Preserve dirty worktree changes you did not make, especially in `../sase-core`.
- Do not modify memory files without explicit user approval.
- Use `.sase` in new docs/tests unless a test is explicitly asserting legacy fallback.
- Keep `project_file` variable and wire field names unless a later product decision changes the schema; those names
  describe the role, not the extension.
- If a phase modifies a repo, run that repo's required check command before handoff.
