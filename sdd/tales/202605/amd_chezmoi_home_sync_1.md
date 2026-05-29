---
create_time: 2026-05-29 17:55:47
status: done
prompt: sdd/prompts/202605/amd_chezmoi_home_sync_1.md
---
# Plan: Sync Chezmoi Home AGENTS From `sase amd init`

## Problem

Updating a long-term memory file description in the chezmoi source tree does not refresh
`~/.local/share/chezmoi/home/AGENTS.md` when `sase amd init` is run from `~` or from the SASE project root.

The current AMD init implementation builds and applies a plan for exactly one root: `Path.cwd()`. It only manages the
chezmoi home root when the command is run from `~/.local/share/chezmoi/home` itself. In `use_chezmoi: true` mode, this
differs from the rest of initialization behavior, where the home memory source of truth is the chezmoi home tree.

## Root Cause

- `src/sase/amd/init.py::_build_amd_init_plan()` defaults to the current working directory and does not expand that into
  the configured home/chezmoi roots.
- `_load_amd_h1_title()` already knows how to load titles for `Path.home()` and `config_core.CHEZMOI_HOME`, so the
  rendering logic is capable of producing the correct chezmoi home `AGENTS.md` once the source root is selected.
- `sase amd init --check` uses the same single-root planner, so drift in the chezmoi source home AGENTS file is also
  invisible from `~` and project directories.

## Implementation Approach

1. Add a small root-selection helper in `src/sase/amd/init.py`.
   - In normal mode, preserve the existing single-root behavior.
   - In `use_chezmoi: true` mode, treat `config_core.CHEZMOI_HOME` as the home-level AMD source of truth.
   - When run from live `~`, plan the chezmoi home source instead of the live home tree.
   - When run from a project directory, plan both the project root and the chezmoi home source.
   - Deduplicate roots by resolved path so running inside the chezmoi home source does not double-apply writes.

2. Combine per-root AMD plans into one init plan.
   - Reuse the existing single-root planner for rendering, provider shim repair, migration blockers, and check output.
   - Combine actions, writes, and blockers across selected roots.
   - Keep explicit root calls usable for tests and internal callers.

3. Add regression tests in `tests/main/test_amd_init.py`.
   - `use_chezmoi: true` plus cwd `~` updates `CHEZMOI_HOME/AGENTS.md` from the source long-memory description.
   - `use_chezmoi: true` plus cwd project updates both the project AMD files and `CHEZMOI_HOME/AGENTS.md`.
   - `--check` reports drift for the chezmoi source from project/home contexts without writing.

4. Verify with focused tests, then run the required repo check.
   - Run the AMD init test module first.
   - Run `just install` if needed, then `just check` because this changes SASE repo files.

## Non-Goals

- Do not modify canonical memory files or the user’s chezmoi memory content.
- Do not add commit/apply behavior to `sase amd init`; this fix only makes the correct files visible to the existing
  planner and writer.
- Do not change `sase amd list` display behavior unless tests reveal an inconsistency caused by the planner change.
