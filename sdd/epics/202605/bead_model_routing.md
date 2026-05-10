---
create_time: 2026-05-10 00:07:15
bead_id: sase-2o
tier: epic
status: done
prompt: sdd/prompts/202605/bead_model_routing.md
---
# Bead Model Routing Plan

## Goal

Add first-class bead metadata for choosing the model that should handle automated bead work:

- For `phase` beads, the stored model selects the phase work agent launched by `sase bead work <epic_id>`.
- For executable `plan` beads with tier `epic` or `legend`, the stored model selects the final land agent for that bead.
- When no model is stored, launch behavior remains unchanged and the normal default model selection applies.

Use a single optional bead field named `model`, exposed as `-m/--model`, serialized in bead storage as `"model": ""` or
omitted/backfilled to empty for old stores. The field should accept the same raw values that `%model` already accepts,
including provider-qualified names such as `codex/gpt-5.5` and local aliases such as `#pro`, while rejecting
newline/control-character input so stored metadata cannot inject extra prompt directives.

## Phase 1: Core Bead Metadata And Storage

Owner: core/storage agent.

Update the bead model across Python and Rust so `model` is part of the canonical bead record.

Implementation scope:

- Add `model: str = ""` to `src/sase/bead/model.py::Issue`.
- Add `model` to Python legacy SQLite schema/migrations in `src/sase/bead/db.py`, JSONL import/export in
  `src/sase/bead/jsonl.py`, and Python/Rust wire conversion in `src/sase/core/bead_wire.py`.
- Add `model` to Rust `IssueWire`, JSONL parsing/export, SQLite schema/migrations, mutation request/update fields, and
  read/mutation outputs in `../sase-core/crates/sase_core/src/bead/*`.
- Ensure old JSONL fixtures without `model` still import with `model == ""`.
- Add shared validation that stored model values cannot contain `\n`, `\r`, or other control characters; trim
  surrounding whitespace at CLI/facade boundaries if that matches existing field normalization.
- Include the field in any bead-facing integration projection that serializes issue details, including mobile bead
  helpers if they expose the full bead summary/detail shape.

Tests:

- Rust unit/parity tests for JSONL round-trip, legacy defaulting, and validation.
- Python model/jsonl/db/facade tests proving `model` survives create, update, read, and export/import.
- Fixture updates for current bead schema goldens in both repos where applicable.

Exit criteria:

- Existing bead stores remain readable.
- New stores can persist and read `model`.
- No launch behavior changes yet.

## Phase 2: CLI CRUD, Display, And Generated Skill Source

Owner: CLI/docs agent.

Expose the field through `sase bead` commands and update the source xprompt skill that documents bead usage.

Implementation scope:

- Add `-m/--model` to `sase bead create` and `sase bead update` in `src/sase/main/parser_bead.py`. Keep the short option
  because this repo expects short options on CLI arguments.
- Pass the field through `handle_bead_create()` and `handle_bead_update()`.
- Display `Model: <value>` in `sase bead show` when set. Listing can stay unchanged unless the surrounding code already
  includes similar optional metadata in list rows.
- Update bead onboard/help text if it enumerates create/update options.
- Update `src/sase/xprompts/skills/sase_beads.md` with examples:
  - phase work model: `sase bead create ... --type phase(<epic>) --model codex/gpt-5.5`
  - epic/legend land model: `sase bead create ... --tier epic --model claude/opus`
  - update/clear guidance for `sase bead update <id> --model <model>` and empty-string clearing if supported.
- Do not edit live generated skill files directly. After the skill source changes, run `sase init-skills --force` and
  `chezmoi apply` as required by the generated-skills workflow.

Tests:

- Parser/help tests for `-m/--model` on create and update.
- CLI golden or focused tests for create/update/show with `model`.
- Skill source test updates if the repository snapshots skill content.

Exit criteria:

- Users and agents can set/read the model field without using internal APIs.
- The `/sase_beads` generated skill documents the new contract.

## Phase 3: Epic Work Plan Model Propagation

Owner: epic-work automation agent.

Make `sase bead work <epic_id>` honor phase and epic model metadata.

Implementation scope:

- Extend Rust epic work plan wires so each phase assignment carries the phase bead model, and the epic land assignment
  carries the epic bead model.
- Extend Python dataclasses in `src/sase/bead/work.py` accordingly.
- In `render_multi_prompt()`, emit `%model:<model>` for a phase segment when that phase bead has `model` set.
- Emit `%model:<model>` for the final `bd/land_epic` segment when the epic bead has `model` set.
- Place `%model` near the existing launch directives, preferably after `%name` and before `%tag/%approve`, so dry-run
  output remains readable and directive extraction keeps working.
- Keep `preclaim_epic_work()` unchanged except for any wire struct fallout; model routing should not affect
  assignee/status preclaims.
- Add model information to `print_work_plan_summary()` only if it is useful and compact; the dry-run prompt itself is
  the source of truth.

Tests:

- Rust work-plan tests proving phase assignment models and epic land model are copied from the relevant issues.
- Python rendering tests proving `%model` appears only on the intended segments and is absent for empty models.
- CLI dry-run test proving the rendered multi-prompt includes the expected `%model` lines for phase and land agents.
- A negative test proving model values cannot inject additional directives via newline input.

Exit criteria:

- Epic phase agents use their phase bead model.
- Epic land agents use their epic bead model.
- Existing epic work tests pass unchanged when no model is set.

## Phase 4: Legend Work Model Propagation

Owner: legend-work automation agent.

Make `sase bead work <legend_id>` honor legend model metadata for the final land agent.

Implementation scope:

- Extend Rust legend work plan wire and Python `LegendWorkPlan` so the plan carries the legend bead model.
- In `render_legend_multi_prompt()`, emit `%model:<model>` only on the final `bd/land_legend` segment when the legend
  bead has `model` set.
- Do not apply the legend bead model to the intermediate epic-planning agents unless a separate requirement is
  introduced. Those agents are planning future epics, not landing the legend bead.
- Preserve the current wait chain and tag behavior exactly.

Tests:

- Rust legend work-plan test for `land_model`.
- Python rendering snapshot/focused test showing the legend land segment has `%model` and epic-planning segments do not.
- CLI dry-run test for a legend bead with a model.

Exit criteria:

- Legend land agents use the legend bead model.
- Intermediate legend epic-planning agents remain unchanged.

## Phase 5: Automation Prompts, Regeneration, And Final Verification

Owner: integration agent.

Finish user-facing automation and run the full verification path.

Implementation scope:

- Review built-in bead xprompts in `src/sase/default_config.yml`, especially `bd/new_epic` and `bd/new_legend`, and
  update them if they need to teach agents how to propagate model metadata from plan frontmatter or phase text into
  `sase bead create --model ...`.
- If adding a frontmatter convention, keep it simple:
  - `model` on epic/legend plan frontmatter maps to the executable plan bead land model.
  - A phase-level `model` annotation maps to that phase bead work model.
  - Do not invent multiple field names unless tests already show a stronger local convention.
- Regenerate generated skills after `src/sase/xprompts/skills/sase_beads.md` changes with `sase init-skills --force`,
  then apply with `chezmoi apply`.
- Update any snapshots/goldens affected by the added field.
- Run `just install` before checks in this ephemeral workspace, then run targeted tests for bead storage, bead CLI, bead
  work rendering, xprompt skill generation, and Rust core parity. Finish with `just check`.

Suggested targeted commands:

```bash
just install
pytest tests/test_bead tests/test_bead_xprompt_tags.py tests/main/test_init_skills_sources.py tests/main/test_init_skills_handler.py
cargo test -p sase_core bead
just check
```

Exit criteria:

- `sase bead create/update/show` supports `model`.
- `sase bead work` renders `%model` for phase work agents and epic/legend land agents exactly as specified.
- Generated `/sase_beads` skill content is in sync with the source xprompt skill.
- Backward compatibility fixtures confirm old bead stores continue to load.
