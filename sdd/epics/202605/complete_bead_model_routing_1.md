---
bead_id: sase-2r
tier: epic
status: done
create_time: 2026-05-10 11:29:15
prompt: sdd/prompts/202605/complete_bead_model_routing_1.md
---

# Complete Bead Model Routing (sase-2o)

## Context

`sase-2o` and all five of its phase beads are marked closed, but the Python implementation of the bead `model` field
described in `sdd/epics/202605/bead_model_routing.md` was never landed:

- The bead's notes record `COMMIT: c817836f`, but no such commit exists in `git log` on master.
- The Rust side (`../sase-core/crates/sase_core/src/bead/`) is fully implemented: `IssueWire.model`, JSONL/SQLite/wire
  conversion, mutation create/update fields, validation (`validate_model_value`), `EpicWorkPlan.land_model` /
  `PhaseAssignment.model`, `LegendWorkPlan.land_model`, and `--model` parsed in the Rust CLI helpers.
- The Python side is empty: no `model` on `Issue` (`src/sase/bead/model.py`), no `model` column in the legacy SQLite
  schema (`src/sase/bead/db.py`), no `model` handling in `issue_from_dict` (`src/sase/core/bead_wire.py`), no
  `-m /--model` on `sase bead create` / `sase bead update` (`src/sase/main/parser_bead.py`), no propagation through
  `handle_bead_create` / `handle_bead_update` (`src/sase/bead/cli_crud.py`), no `model` parameter on
  `BeadProject.create()` (`src/sase/bead/project.py`), no `model` payload key in `bead_mutation_facade.create()`
  (`src/sase/core/bead_mutation_facade.py`), no `model` on `PhaseAssignment` / `EpicWorkPlan.land_model` /
  `LegendWorkPlan.land_model`, no `%model:<value>` emission in `render_multi_prompt` / `render_legend_multi_prompt`
  (`src/sase/bead/work.py`), no `Model:` line in `handle_bead_show` (`src/sase/bead/cli_query.py`), and no `--model`
  documentation in `src/sase/xprompts/skills/sase_beads.md`. The `bd/new_epic` and `bd/new_legend` xprompts in
  `src/sase/default_config.yml` do not teach agents to propagate model metadata from plan frontmatter.

The user-facing skill copy in `~/.claude/skills/sase_beads/` already advertises `--model` syntax, so the doc/CLI gap is
also user-visible: agents trying to follow the skill will hit `unrecognized arguments: --model` from argparse.

The Rust side already validates input against control characters and rejects directive-injection attempts
(`validate_model_value`), so the Python side just needs to forward strings through; no Python-side validation logic
needs to be reinvented.

## Goal

Land the Python half of the bead-`model` contract so that `sase bead create/update/show` and `sase bead work` honor the
field exactly as specified in `sdd/epics/202605/bead_model_routing.md`. Once the work is done, regenerate the
`/sase_beads` skill, update the relevant default-config xprompts, run `just check` and `just pyvision`, set the epic
plan file's frontmatter `status: done`, and re-close `sase-2o`.

## Non-goals

- No new Rust changes: the Rust side already passes `model` end-to-end. Phases below only touch Rust if a Python test
  reveals a real wire mismatch.
- No new bead frontmatter conventions beyond the original plan (`model` on epic/legend plan frontmatter → land model;
  phase-level `model` annotation → phase work model). No new field names.
- No retrofitting historic JSONL fixtures with `model`. Old fixtures must keep loading with `model == ""`.

## Phase 1: Core Bead Metadata Plumbing (Python)

Owner: storage / data-model agent.

Make `model` a first-class Python field on `Issue` and on every Python codec / wire that the production hot path
touches. After this phase the field is persisted, surfaced on reads, and round-trips through Rust without affecting
launch behavior.

Implementation scope:

- Add `model: str = ""` to `Issue` in `src/sase/bead/model.py`. Place it next to `design`/`notes` to match the Rust
  struct ordering. No `validate()` change (Rust enforces format).
- Add `model TEXT NOT NULL DEFAULT ''` to the legacy SQLite schema in `src/sase/bead/db.py` and to any row serialization
  helpers in that file. The Python schema is compat-only, but its tests still exercise this column.
- Add `model` to the `issue_from_dict` reader in `src/sase/core/bead_wire.py` with the same defaulting pattern as
  `design`/`notes` (treat `None`/missing as `""`).
- Add `"model": issue.model` to `_issue_to_wire_dict` in `src/sase/bead/work.py` so the Rust epic-work-plan builder
  receives the field.
- Add `model` to JSONL helpers in `src/sase/bead/jsonl.py` if they reference Issue fields directly. (Most of the JSONL
  hot path is Rust; only touch Python helpers that today list the canonical field set.)
- Update `mobile_bead`/projection helpers if any of them flatten the issue shape for an integration projection.

Tests:

- Extend `tests/test_bead/test_model.py` with a default-empty + assignment test.
- Extend `tests/test_bead/test_db.py` to round-trip a non-empty `model` through the legacy SQLite codec and to load a
  pre-`model` fixture as `""`.
- Extend `tests/test_bead/test_jsonl.py` only if jsonl.py changed.
- Extend `tests/test_bead/test_project_rust_delegation.py` (or its peer) to assert that an `Issue` returned from the
  Rust facade has `.model` populated when the underlying bead has one.

Exit criteria:

- `just install && pytest tests/test_bead -q` is green.
- Old fixtures still import; `Issue(...).model == ""` by default.
- No launch behavior or CLI surface change yet.

## Phase 2: CLI CRUD, Show Display, And Skill Source

Owner: CLI / docs agent. Depends on Phase 1.

Expose the field on the user-facing CLI and bring the `/sase_beads` generated skill in sync with the actual
implementation.

Implementation scope:

- Add `-m/--model` to both `bead_create_parser` and `bead_update_parser` in `src/sase/main/parser_bead.py`. Short option
  is required by the project gotchas note. Help text should mention provider-qualified strings (`codex/gpt-5.5`) and
  local aliases (`#pro`).
- In `src/sase/bead/cli_crud.py::handle_bead_create`, forward `args.model or ""` into the `proj.create()` call.
- In `src/sase/bead/cli_crud.py::handle_bead_update`, treat `args.model is not None` as "user passed the flag" so
  empty-string clears the field (matching the documented `--model ""` clear behavior).
- Add `model` to `BeadProject.create()` in `src/sase/bead/project.py` and forward it into
  `bead_mutation_facade.create()`. Add `model` to the create payload in `src/sase/core/bead_mutation_facade.py`.
  `update()` already passes arbitrary `**fields`, so the only new requirement there is that `cli_crud` populate
  `fields["model"]`.
- Add `Model: <value>` to `handle_bead_show` in `src/sase/bead/cli_query.py`, gated on `if issue.model:` (mirror the
  existing `if issue.assignee:` block).
- Update `src/sase/xprompts/skills/sase_beads.md` with the same examples already present in the live skill copy: phase
  work model, epic/legend land model, and update/clear guidance. Include the `Model: <value>` show example.
- Run `sase init-skills --force` and `chezmoi apply` to regenerate the live skill files. Verify the regenerated
  `~/.claude/skills/sase_beads/SKILL.md` (and any peer agent runtime copies — codex/gemini/qwen/opencode) match the
  source. NEVER hand-edit generated skill output; only the source.

Tests:

- Parser tests for `-m/--model` accept-and-store on both subcommands.
- A focused CLI test covering `sase bead create ... --model ...`, `sase bead update <id> --model ""`, and
  `sase bead show` rendering `Model:` only when set.
- Regenerated-skill snapshot tests if `tests/main/test_init_skills_sources.py` /
  `tests/main/test_init_skills_handler.py` snapshot the bead skill.

Exit criteria:

- `sase bead create --help` lists `-m/--model`.
- A round-trip `create --model X` + `show` displays `Model: X`.
- `pytest tests/test_bead tests/main/test_init_skills_sources.py tests/main/test_init_skills_handler.py` is green.
- The `/sase_beads` skill source and its generated outputs no longer disagree on `--model`.

## Phase 3: Work-Plan Model Propagation (Epic + Legend)

Owner: epic / legend work-rendering agent. Depends on Phase 2.

Make `sase bead work <id>` honor phase, epic, and legend bead model metadata in the rendered multi-prompt. Combined into
a single phase because both rendering paths live side-by-side in `src/sase/bead/work.py` and share the same
`_segment_prefix` / directive-ordering conventions.

Implementation scope:

- Add `model: str = ""` to `PhaseAssignment` (`src/sase/bead/work.py`).
- Add `land_model: str = ""` to `EpicWorkPlan` and to `LegendWorkPlan`.
- Update `_plan_from_payload` to read `assignment["model"]` and `payload["land_model"]` from the Rust payload (the Rust
  side already populates these — see `../sase-core/crates/sase_core/src/bead/work.rs`).
- Update `_legend_plan_from_payload` similarly (Rust already sets `land_model` from the legend bead's model).
- In `render_multi_prompt`, emit `%model:<assignment.model>` per phase segment when non-empty, and
  `%model:<plan.land_model>` on the final land segment when non-empty. Place the directive after `%name` and the
  `_tag_directive` and before `%approve` (consistent with the original plan's directive-ordering note).
- In `render_legend_multi_prompt`, emit `%model:<plan.land_model>` only on the final `bd/land_legend` segment.
  Intermediate epic-planning segments must NOT carry `%model` (they are not landing the legend).
- `print_work_plan_summary()` may show the resolved models if it can stay compact; the dry-run prompt itself is the
  source of truth.

Tests:

- Extend `tests/test_bead/test_work_rendering.py` with cases for: phase model present, phase model empty, mixed phases,
  epic land model, legend land model, and a regression test confirming legend epic-planning segments have no `%model`
  directive.
- Extend `tests/test_bead/test_work_epic_plan.py` and `tests/test_bead/test_work_legend_plan.py` to cover
  `_plan_from_payload` / `_legend_plan_from_payload` reading `model` / `land_model` from the Rust payload.
- A negative test confirming a pathological model value cannot inject extra directives. Rust validates on write, so this
  test mostly proves the renderer doesn't double-handle escaping.
- A `sase bead work <id> --dry-run` integration test asserting the rendered multi-prompt contains the expected `%model:`
  lines and absent ones.

Exit criteria:

- All `tests/test_bead` tests pass.
- Existing tests that don't set `model` still see no `%model` directives in the rendered output.
- Rendered multi-prompt is byte-identical for the no-model case to today's output.

## Phase 4: Default-Config Xprompts, Verification, And Bead Closeout

Owner: integration agent. Depends on Phase 3.

Finish the user-facing automation contract, run the repo-wide verification path, and close `sase-2o` cleanly.

Implementation scope:

- Update `bd/new_epic` in `src/sase/default_config.yml` so the agent that creates epic beads is told to:
  - read a `model:` field from the plan-file frontmatter, if present, and pass it via `--model` on the epic plan-bead
    `sase bead create` call;
  - read per-phase `model:` annotations (matching the simple convention from the original epic plan), if present, and
    pass `--model` on each phase `sase bead create` call.
- Update `bd/new_legend` similarly so the legend bead inherits a frontmatter `model:` value as the land model.
- Keep the simple convention from `sdd/epics/202605/bead_model_routing.md`: only one field name, `model`. Do not invent
  secondary names.
- Run `sase init-skills --force` and `chezmoi apply` once if `default_config.yml` xprompt body changes alter any
  generated artifact. (Most config.yml changes do not regenerate skill files; only run if a generated artifact
  references the changed bodies.)
- Update any failing snapshots/goldens (e.g. `tests/test_default_config*` or skill snapshots) that capture the
  bd/new_epic / bd/new_legend bodies.
- Add `status: done` to the frontmatter of `sdd/epics/202605/bead_model_routing.md` (replace the existing
  `status: wip`).
- Run the verification battery:
  ```bash
  just install
  pytest tests/test_bead tests/test_bead_xprompt_tags.py \
         tests/main/test_init_skills_sources.py tests/main/test_init_skills_handler.py
  cargo test -p sase_core bead   # only if any Rust file was touched
  just check
  ```
- Re-close `sase-2o` using `sase bead close sase-2o` (and update its NOTES with the real completion commit hash so
  future audits can find the work). The five phase beads are already closed; do not reopen them.
- Run `just pyvision` AFTER closing the epic so any newly-unused symbols introduced or revealed by this work are
  surfaced.

Exit criteria:

- `sase bead show sase-2o` reports `[CLOSED]` with a NOTES line pointing at the actual completion commit.
- `sdd/epics/202605/bead_model_routing.md` has `status: done` in frontmatter.
- `just check` passes; `just pyvision` reports no new unused symbols introduced by this work.
- The five original phase beads remain closed (no thrash).

## Phase Dependencies

```
P1 → P2 → P3 → P4
```

Each phase is intended for a separate agent instance (claude / gemini / codex / qwen / opencode). P1 is purely
data-model plumbing; P2 is CLI + skill source; P3 is rendering; P4 is config + verification + closeout. P3 and P4 must
run after P2 because P2 makes the CLI accept `--model`, which the integration tests in P3/P4 rely on.
