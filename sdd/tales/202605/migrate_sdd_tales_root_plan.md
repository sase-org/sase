---
create_time: 2026-05-01 23:42:50
status: done
---
# Plan: Migrate SDD Plans To Tales

## Goal

Rename the smallest SDD plan directory from `sdd/plans/` to `sdd/tales/` so the hierarchy reads:

- `sdd/tales/` for ordinary non-epic implementation plans
- `sdd/epics/` for executable multi-phase plans
- `sdd/legends/` for larger coordination plans
- future `sdd/myths/` for the largest narrative layer

The migration should update code, tests, docs, CI paths, generated frontmatter links, and committed SDD files so new and
existing canonical references point at `sdd/tales/`.

## Current State

- `sdd/plans/` exists with dated markdown files and `perf_artifacts/` subdirectories.
- SDD generation currently treats `"plans"` as the default plan-like kind in `src/sase/sdd/files.py`,
  `src/sase/sdd/links.py`, `src/sase/axe/run_agent_exec_plan.py`, and the TUI plan approval archive path.
- `sase sdd list --kind` exposes `plans`.
- Commit precommit hooks copy archived plan files into `sdd/plans/{YYYYMM}/`.
- CI, the Justfile, perf tests, docs, xprompt skill text, and many test docstrings/reference strings point to
  `sdd/plans`.
- Personal/local plan archives under `~/.sase/plans` and generic runtime plan terminology are separate concepts and
  should not be renamed.

## Design

1. Make `tales` the canonical SDD directory and kind for ordinary implementation plans.
   - Default generated SDD files should write to `tales`.
   - Prompt frontmatter for ordinary plans should say `plan: sdd/tales/{YYYYMM}/{name}.md` or
     `.sase/sdd/tales/{YYYYMM}/{name}.md`.
   - Plan frontmatter should keep the field name `prompt`; only paths change.

2. Preserve compatibility for historical or external references to the old directory.
   - SDD file lookup should accept `"plans"` as a legacy alias for `"tales"` where callers may still pass old path kind
     values.
   - Link validation/listing should scan canonical `tales` and can also resolve legacy `plans` link paths if such files
     exist in older workspaces.
   - Personal archives under `~/.sase/plans` stay unchanged.

3. Update public SDD surfaces.
   - `sase sdd list --kind` should expose `tales` instead of `plans`.
   - Docs and xprompt skill examples should describe `tales`, while generic prose can still say "plans" when it means
     the concept rather than the directory.

4. Move committed artifacts.
   - Rename `sdd/plans/` to `sdd/tales/`.
   - Update all canonical `sdd/plans/...` and `.sase/sdd/plans/...` references to `sdd/tales/...` /
     `.sase/sdd/tales/...`.
   - Update ignore rules, CI artifact upload paths, Justfile perf output paths, perf metadata, tests, and frontmatter in
     `sdd/prompts`.

## Implementation Steps

1. Move the directory.
   - Use `mv sdd/plans sdd/tales`.
   - Leave unrelated root `plans/` and personal `~/.sase/plans` concepts untouched.

2. Update SDD core helpers.
   - Change canonical plan kind sets from `plans` to `tales`.
   - Add kind aliasing so `find_sdd_file(..., "plans", ...)` can still find both canonical `sdd/tales` and legacy
     `sdd/plans` / root `plans`.
   - Update link validation/listing constants to scan `tales`, infer prompt counterparts against `tales|epics|legends`,
     and expose list kind choices as `prompts|tales|epics|legends|all`.

3. Update generation and approval flows.
   - Change default `plan_kind` values and normal approval `_plan_kind_for_action()` returns from `"plans"` to
     `"tales"`.
   - Update commit precommit hook copy destinations from `sdd/plans/{YYYYMM}/` to `sdd/tales/{YYYYMM}/`.
   - Update TUI archive paths for ordinary approved plans.

4. Update tests.
   - Adjust unit tests for SDD writing, path lookup, links, handler listing, plan approval follow-ups, commit workflow
     artifacts, and rejection paths.
   - Keep tests for `~/.sase/plans` unchanged because that is the runtime plan archive, not the SDD directory.
   - Add or adjust a focused compatibility assertion that legacy `"plans"` lookup can resolve canonical `tales`.

5. Update repository references.
   - Replace canonical `sdd/plans/` and `.sase/sdd/plans/` references across source, tests, docs, CI, `.gitignore`,
     `.prettierignore`, `Justfile`, `sdd/prompts`, and moved SDD files.
   - Update brace examples such as `sdd/{plans|epics|legends}` to `sdd/{tales|epics|legends}`.
   - Update relative SDD references inside moved plan files where they clearly point at the canonical SDD directory.

6. Verify.
   - Run a final reference sweep for `sdd/plans` and `.sase/sdd/plans`.
   - Run focused SDD and workflow tests first.
   - Run `just install`, then `just check` as required by repo instructions.

## Non-Goals

- Rename the internal bead tier `plan`; this is domain terminology for a plan bead and includes epics/legends.
- Rename `~/.sase/plans`, `SASE_PLAN`, plan approval statuses, or generic prose that refers to plans conceptually.
- Rewrite every historical mention of a root `plans/` directory unless it is clearly a canonical SDD path that now moved
  to `sdd/tales/`.
