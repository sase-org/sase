---
create_time: 2026-05-01 22:13:41
status: wip
prompt: sdd/prompts/202605/sdd_prompt_management.md
---
# Plan: SDD Prompt File Management

## Goal

Rename SDD prompt snapshots from `sdd/specs/` to `sdd/prompts/`, add code-owned bidirectional frontmatter links between
prompt files and generated plan files, and add a first-class `sase sdd` command group with validation that runs in CI.

The important product rule is that agents should not be responsible for these metadata fields. SASE should write and
repair them the same way it already owns `create_time` and `status` in plan frontmatter.

## Current State

- Prompt snapshots are stored under `sdd/specs/{YYYYMM}/`.
- Generated plans are stored under `sdd/tales/{YYYYMM}/`, `sdd/epics/{YYYYMM}/`, and `sdd/legends/{YYYYMM}/`.
- `src/sase/sdd/files.py` owns SDD path resolution and `write_sdd_files()`.
- `src/sase/axe/run_agent_exec_plan.py` expands the planner prompt and calls `write_sdd_files()`.
- Built-in xprompts in `src/sase/default_config.yml` still refer to `sdd/specs`.
- There is no `sase sdd` top-level command today.
- There is already a migration wrinkle: SDD generation writes under `sdd/`, but commit-hook fallback tests still expect
  root `plans/{YYYYMM}/`. That should be cleaned up while touching SDD paths.
- Existing historical data is not perfectly paired: there are more plan-like files than prompt snapshots, and some old
  prompt snapshots have no current plan counterpart. Validation must handle historical unpaired files intentionally.

## Target Model

Canonical version-controlled layout:

```text
sdd/
  prompts/{YYYYMM}/*.md   # expanded prompt snapshots
  plans/{YYYYMM}/*.md     # normal implementation plans
  epics/{YYYYMM}/*.md     # executable multi-phase epic plans
  legends/{YYYYMM}/*.md   # higher-level coordination plans
```

Local non-version-controlled mode keeps the same shape under `.sase/sdd/`.

For generated pairs:

- Plan, epic, and legend files get YAML frontmatter:
  - `prompt: sdd/prompts/{YYYYMM}/{name}.md` in version-controlled mode.
  - `prompt: .sase/sdd/prompts/{YYYYMM}/{name}.md` in local SDD mode.
- Prompt files get YAML frontmatter:
  - `plan: sdd/{tales|epics|legends}/{YYYYMM}/{name}.md` in version-controlled mode.
  - `plan: .sase/sdd/{tales|epics|legends}/{YYYYMM}/{name}.md` in local SDD mode.
- Paths should be relative, stable, slash-separated strings. Do not write absolute paths into tracked files.
- When a plan has no prompt counterpart or a prompt has no plan counterpart because it is historical, validation may
  warn but should not fail CI. When a counterpart exists, missing or incorrect link frontmatter is an error.

## Phase 1: Rename Specs To Prompts And Preserve Compatibility

Owner: one agent.

Scope:

- Mechanically move `sdd/specs/` to `sdd/prompts/`.
- Update `src/sase/sdd/files.py` terminology and paths:
  - Prefer `prompts` as the canonical kind.
  - Keep `specs` as a legacy lookup alias so archived plans, xprompts, and older callers do not break immediately.
  - Rename internal variables from `spec_*` to `prompt_*` where doing so is localized and clarifies behavior.
  - Keep public compatibility wrappers or aliases where that reduces churn for downstream code in this phase.
- Update generation in `write_sdd_files()` so new prompt snapshots are written to `prompts/{YYYYMM}/`.
- Update `_commit_sdd_files()` lookup in `src/sase/axe/run_agent_exec_plan.py` to stage prompt files from `prompts`,
  while still finding legacy `specs` if needed.
- Update tests in `tests/test_sdd.py`, `tests/test_expand_for_spec.py`, and plan-exec tests to expect `prompts`.
- Update user-facing docs and built-in xprompts that refer to current prompt paths:
  - `src/sase/default_config.yml`
  - `docs/sdd.md`
  - SASE bead skill text if it references `sdd/specs`.
- Do not rewrite old historical plan prose except where it is part of active docs or tests.

Acceptance criteria:

- New SDD prompt snapshots are created under `sdd/prompts/{YYYYMM}/`.
- Existing references to legacy `sdd/specs/**/{name}.md` still resolve through compatibility lookup.
- Focused SDD tests pass.

## Phase 2: Code-Owned Bidirectional Frontmatter

Owner: one agent after Phase 1 lands.

Scope:

- Add a small SDD frontmatter helper module, likely `src/sase/sdd/frontmatter.py`, that can:
  - Parse YAML frontmatter and body.
  - Set or replace individual fields.
  - Preserve existing body text.
  - Serialize predictable YAML without relying on regex-only updates.
- Update `write_sdd_files()` to compute both final paths before writing either file.
- When writing the prompt snapshot, prepend or update `plan: <plan path>`.
- When writing the plan/epic/legend, add or update `prompt: <prompt path>` in addition to existing
  `create_time`/`status`.
- Keep `update_spec_with_qa()` or its renamed equivalent from breaking prompt frontmatter when appending Q&A.
- Update commit-hook fallback in `src/sase/workflows/commit/precommit_hooks.py`:
  - Copy archived plans into `sdd/tales/{YYYYMM}/`, not root `plans/{YYYYMM}/`.
  - Preserve or add `prompt` frontmatter when SASE can infer a matching prompt.
  - Update tests that currently expect root `plans/`.
- Add focused unit tests for:
  - New plan files include `prompt`.
  - New prompt files include `plan`.
  - Existing frontmatter fields such as `bead_id`, `legend_bead_id`, `tier`, and `status` are preserved.
  - Local `.sase/sdd` mode writes `.sase/sdd/...` relative paths.

Acceptance criteria:

- SASE-generated new plans and prompts are linked both ways without agent edits.
- Frontmatter updates are idempotent.
- Existing plan metadata is not dropped.

## Phase 3: Add `sase sdd` Command Group

Owner: one agent after Phase 2 lands.

Scope:

- Add parser and handler modules, following existing argparse style:
  - `src/sase/main/parser_sdd.py`
  - `src/sase/main/sdd_handler.py`
  - register the command in `src/sase/main/parser.py` and `src/sase/main/entry.py`.
- Add useful subcommands:
  - `sase sdd validate [-p/--path PATH] [-j/--json] [-q/--quiet] [--strict]`
  - `sase sdd links [-p/--path PATH] [-j/--json]`
  - `sase sdd list [-k/--kind prompts|tales|epics|legends|all] [-j/--json]`
  - `sase sdd repair-links [-p/--path PATH] [-w/--write]`
- Validation rules:
  - YAML frontmatter must parse when present.
  - `prompt` on plan/epic/legend files must be a string path if present.
  - `plan` on prompt files must be a string path if present.
  - Linked paths must exist.
  - Linked paths must point to the correct opposite kind.
  - Bidirectional links must agree.
  - For files with an inferable counterpart by `{YYYYMM}/{name}.md`, missing links are errors.
  - Unpaired historical files are warnings by default and errors under `--strict`.
- `repair-links --write` should be the code-owned migration path. It can infer unambiguous counterpart pairs and write
  the missing or stale `prompt`/`plan` fields. Without `--write`, it should print a dry-run report.
- All subcommands should support version-controlled `sdd/` and local `.sase/sdd/` roots via `-p/--path`.

Acceptance criteria:

- `sase sdd validate` exits nonzero for broken current links and zero for valid linked pairs plus unpaired legacy files.
- `sase sdd repair-links --write` can backfill an unambiguous fixture without hand-editing files.
- CLI tests cover success, warning, error, JSON output, and invalid path cases.

## Phase 4: Backfill Existing Repository Metadata With SASE Code

Owner: one agent after Phase 3 lands.

Scope:

- Run the new code-owned repair path on this repo, not manual frontmatter edits:

```bash
sase sdd repair-links --write
```

- Review the report and commit only deterministic changes:
  - unambiguous `sdd/prompts/{YYYYMM}/{name}.md` to `sdd/{tales|epics|legends}/{YYYYMM}/{name}.md` pairs get
    bidirectional frontmatter.
  - unpaired historical files remain unlinked and are recorded as warnings.
- If duplicate candidates appear, improve the repair logic rather than resolving them manually in markdown.
- Run `sase sdd validate` after repair.
- Update any snapshots or docs that need to show the new frontmatter fields.

Acceptance criteria:

- Current repo prompt/plan pairs are linked by code-generated fields.
- `sase sdd validate` passes in the repository.
- The repair report clearly explains any remaining historical warnings.

## Phase 5: CI Integration And Final Cleanup

Owner: one agent after Phase 4 lands.

Scope:

- Add a `just sdd-validate` target that runs `sase sdd validate`.
- Add a GitHub Actions step, probably in the existing `lint` job after `just install`, to run `just sdd-validate`.
- Ensure CI uses the installed `.venv/bin/sase` or the same invocation style as nearby jobs.
- Remove stale compatibility references where safe:
  - Active docs should say `prompts`, not `specs`.
  - Code comments should reserve `specs` only for legacy compatibility.
- Keep legacy lookup support for at least this rollout; do not delete it in the same phase as the CI gate.
- Run full repo verification required by local memory:

```bash
just install
just check
```

Acceptance criteria:

- GitHub Actions runs SDD validation.
- Full local verification passes.
- No agent-authored prompt/plan link fields are required for new SDD files.

## Risks And Notes

- The rename is mostly mechanical, but historical docs contain many legitimate mentions of "specs". Avoid noisy churn in
  old SDD artifacts.
- Existing `add_create_time_frontmatter()` is regex based. New link fields should use structured YAML helpers so future
  fields do not accumulate fragile one-off mutators.
- Validation needs a legacy-aware default so CI can pass without forcing every old unpaired plan file to invent a
  prompt. `--strict` is still useful for fresh fixtures and future cleanup.
- Because SDD behavior is currently implemented in Python and is tied to agent plan generation and the Python CLI, this
  plan keeps the first implementation in this repo. If another frontend needs identical SDD validation later, that is a
  good point to move the validation core into `../sase-core`.
