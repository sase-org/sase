---
create_time: 2026-05-27 12:18:10
status: done
prompt: sdd/prompts/202605/bare_git_sdd_version_controlled.md
---
# Plan: Bare Git Implies Version-Controlled SDD

## Goal

Make `sdd.version_controlled` unnecessary for bare-git projects. For any repository resolved as the built-in `bare_git`
VCS provider, SASE should behave as if `sdd.version_controlled: true` even when the merged config omits the field or
sets it to `false`.

## Current Behavior

`sase.sdd.beads.get_sdd_config()` currently returns only the merged YAML value at `sdd.version_controlled`, defaulting
to `false`. Callers use that boolean to choose between:

- version-controlled SDD under `<workspace>/sdd/`, including `sdd/beads/`; and
- local SDD under `<primary_workspace>/.sase/sdd/`, with a standalone git repo.

This affects plan approval archiving, SDD commit handling, bead initialization, bead CLI storage resolution, fast-path
bead commands, mobile/TUI plan approval archiving, and commit pre-hook `SASE_PLAN` handling.

Bare-git workspace/VCS support already has a concrete provider identity: `bare_git`. The missing piece is making SDD
mode resolution treat that provider as an implicit version-controlled mode.

## Design

Add an effective SDD mode helper in `sase.sdd.beads`:

- Preserve `get_sdd_config()` as the compatibility entry point.
- Add provider-aware detection that returns true when the current directory or an explicit workspace path resolves to
  `detect_vcs(...) == "bare_git"`.
- Catch VCS detection errors and fall back to the configured value so SDD config lookup remains non-fatal in non-repo
  contexts.
- Add a workspace-aware helper for call sites that already know the relevant workspace path, so background UI/mobile
  flows do not accidentally use the daemon process CWD.

Use the effective helper at every SDD placement or commit gate where a workspace path is available:

- plan approval SDD writes in `src/sase/axe/run_agent_exec_plan.py`;
- bead initialization in `src/sase/sdd/beads.py`;
- bead CLI and fast-path bead storage resolution;
- commit pre-hook `handle_sase_plan(..., cwd)`;
- mobile and TUI plan approval archiving.

Keep the raw default config and schema default as `false`, because non-bare-git providers still support local SDD mode.
Document that bare-git projects ignore the false value and always use project-root `sdd/`.

## Tests

Add focused tests for the new effective-mode behavior:

- config false + detected `bare_git` => effective true;
- config false + detected non-bare provider or detection failure => effective false;
- explicit workspace-path detection makes a bare-git workspace effective true even when the process CWD is elsewhere.

Add or adjust one storage-resolution test where useful to show bare-git effective mode selects `sdd/beads/` without
requiring `sdd.version_controlled: true`.

Run focused pytest for the touched areas first, then `just check` after all file changes, following repo instructions.

## Documentation

Update the SDD/configuration docs to describe `sdd.version_controlled` as a non-bare-git storage-mode switch and call
out that bare-git projects always use version-controlled SDD under `sdd/`.
