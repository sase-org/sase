---
create_time: 2026-05-12 12:08:33
status: done
prompt: sdd/prompts/202605/phase5_plugin_sase_migration.md
---
# Phase 5 Re-Do: Maintained Plugin `.gp` → `.sase` Migration

## Context

The `sase-33` epic migrates project spec files from the legacy `.gp` extension to the canonical `.sase` extension across
the SASE main repo, the Rust `sase-core` repo, and three maintained plugin repos. Phases 1–4 are genuinely complete:

- Main repo (`sase_100`) ships `project_spec_path.py` with `PROJECT_SPEC_EXTENSION = ".sase"`,
  `LEGACY_PROJECT_SPEC_EXTENSION = ".gp"`, and a `preferred_project_spec_path` helper that prefers canonical over legacy
  when both exist.
- Test fixtures and the Rust core (`sase-core`) have been renamed to `.sase` with legacy `.gp` retained only in
  compatibility tests and migration helpers.
- `just check` in `sase_100` and `just rust-check` for `sase-core` both pass.

Phase 5, however, was closed without any actual plugin work: there are zero `sase-33` commits in `sase-github`,
`sase-telegram`, or `sase-nvim`, and the plugin runtime code still writes/reads `.gp`. Phase 6 (cross-repo verification)
was also closed prematurely as a result. This plan finishes Phase 5, redoes the relevant Phase 6 verification, then
closes the epic.

## Goal

Bring the three maintained plugin repos in line with the canonical `.sase` extension while keeping legacy `.gp` files
readable, then close the `sase-33` epic and mark the epic plan file done.

## Scope

### 1. `sase-github` (commit `sase-33.5a`)

- Update `src/sase_github/workspace_plugin.py`:
  - Mode-1 repo-path branch (line ~380): construct the project file via the main-repo `preferred_project_spec_path`
    helper (importable as `from sase.ace.changespec.project_spec_path import …`). Resolution should prefer an existing
    `.sase` file, fall back to legacy `.gp`, and default to writing `.sase` when neither exists.
  - Mode-2 project-shorthand branch (line ~406): same — use the helper instead of hand-constructing `f"{gh_ref}.gp"`.
  - Update the surrounding docstring from `…/<name>.gp` to `…/<name>.sase`.
- Update `docs/architecture.md` and `docs/configuration.md` so the example project-spec path uses `.sase`.
- Update `tests/test_workspace_plugin.py`: switch the canonical fixtures (`myproj.gp`, `proj.gp`,
  `tempfile suffix=".gp"`) to `.sase`, and add one legacy-fallback test that confirms a project directory containing
  only the legacy `.gp` file still resolves.
- Verify: `just check`.

### 2. `sase-telegram` (commit `sase-33.5b`)

- Update `src/sase_telegram/scripts/sase_tg_inbound.py`:
  - `_resolve_workspace_from_project_file` (line ~263) and `_iter_known_project_workspaces` (line ~279) should use the
    main-repo `preferred_project_spec_path` helper for both the single-project lookup and the directory iteration.
    Telegram inbound already imports from `sase.*`, so the helper is available.
- Update `docs/inbound.md`: replace `~/.sase/projects/*/<project>.gp` with `<project>.sase` and note the legacy
  fallback.
- Update `tests/test_inbound.py` (line 1921 and any siblings): switch the canonical fixture to `sase.sase` and add a
  legacy-`.gp`-only smoke test if not already covered.
- Verify: `just check`.

### 3. `sase-nvim` (commit `sase-33.5c`)

- Update `ftdetect/sase_gp.lua` to detect both `.sase` (canonical) and `.gp` (legacy) under `~/.sase/projects/`.
  Decision: keep the `sase_gp` filetype name for back-compat (user `ftplugin/sase_gp.*` overrides and existing syntax
  groups continue to work). Do not rename the filetype in this phase; it can be revisited after the migration window
  closes.
- Update `syntax/sase_gp.vim` header comment from "SASE Project Spec (.gp)" to "SASE Project Spec (.sase / legacy .gp)".
- Update `README.md` section "Filetype Detection & Syntax Highlighting": replace
  `~/.sase/projects/<project>/<project>.gp` with `~/.sase/projects/<project>/<project>.sase` and note legacy support.
- Verify the Lua pattern by sourcing the file in a headless `nvim --noplugin` smoke check that opens a
  `~/.sase/projects/foo/foo.sase` path under a temp `HOME` and asserts `&filetype == "sase_gp"`.

### 4. Phase 6 re-verification

- Cross-repo grep for `\.gp`, `*.gp`, `-archive.gp`, `sase_gp`, `gp_file`, `.replace(".gp", "")` across all four repos.
  Classify remaining hits as: intentional legacy compatibility (helpers / migration command / fallback tests / `sase_gp`
  filetype name) versus missed work. Fix any missed runtime/docs/test hits.
- Run `just check` in `sase_100`, `sase-github`, `sase-telegram`, and the Lua filetype smoke in `sase-nvim`; run
  `just rust-check` for `sase-core` if any new edits were needed (none expected).

### 5. Close out

- `sase bead close sase-33` (the child beads are already closed).
- Run `just pyvision` in the main repo and remove any newly-flagged unused code.
- Update `sdd/epics/202605/project_spec_extension_sase.md` frontmatter `status` field to `done`.

## Out of scope

- No further changes to `sase_100` runtime or `sase-core` beyond what falls out of Phase 6 re-verification.
- No data-migration command runs against `~/.sase/projects`; that is gated on explicit user approval per the epic plan.
- The `sase_gp` filetype name is intentionally preserved; renaming to `sase_project` is a separate future decision.

## Risks

- Plugin repos import from `sase.*` for ChangeSpec utilities, so importing `project_spec_path` should be safe; if a
  plugin's CI runs against an older `sase_100` checkout, the helper may be unavailable. Mitigate by mirroring the
  minimal extension + fallback logic locally when the import fails, per the epic's handoff notes.
- The `sase_gp` filetype name stays, so users with `ftplugin/sase_gp.lua` still work, but anyone keying syntax highlight
  on the filename pattern alone will need the new `.sase` pattern — that is the entire point of this phase.
