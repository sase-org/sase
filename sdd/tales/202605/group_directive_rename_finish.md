---
prompt: sdd/prompts/202605/group_directive_rename_finish.md
create_time: 2026-05-10 11:34:25
status: done
---

# Finish `%tag` → `%group` Directive Rename (Python Side)

## Status Of Prior Work

A previous planning pass yesterday produced `sdd/tales/202605/group_directive_rename.md` and a sibling
`sdd/tales/202605/time_directive.md`. Code work happened only in the sibling repos:

- `../sase-core` already exposes the directive as `group` (alias `g`) in `crates/sase_core/src/editor/directive.rs`, and
  tests assert `("g", "group")` resolves canonically. `t` has been rebound to a _new_ `time` directive (separate,
  in-flight plan) — i.e. `t -> tag` is gone on the Rust side.
- `~/.local/share/chezmoi` already uses `%g:` everywhere (`home/dot_config/sase/sase_athena.yml`,
  `home/bin/executable_sase_chop_gh_actions_fix`, and `tests/bash/gh_actions_fix_chop_test.sh`).

Nothing in `sase_100` (Python parser, prompt generation, tests, docs) has been touched yet. Working tree is clean. The
two `wip` SDD plans from yesterday remain valid as design context.

## Goals

1. `%group:<value>` and `%g:<value>` are the supported spellings on the Python side.
2. `%tag` / `%t` are no longer recognized as directives. They become unknown `%name` patterns and are left in prompts
   unchanged (current behavior for unknown directives).
3. Generated bead/legend/epic prompts and active xprompts emit `%group:<id>`.
4. The persisted `tag` concept stays: `~/.sase/agent_tags.json`, `PromptDirectives.tag`, ACE tag-grouping UI, and
   `sase agents tag ...` CLI all keep their current names. Only the prompt-directive spelling changes.
5. Tests and user-facing docs (`docs/xprompt.md`, `docs/ace.md`, `docs/axe.md`) describe the new spelling.
6. `just check` passes in `sase_100`.

## Non-Goals

- Do not rename `PromptDirectives.tag` to `group`, do not migrate `agent_tags.json`, do not touch the Agents tab
  grouping UI or `sase agents tag` CLI.
- Do not add a `t -> group` alias. `t` is being rebound to `time` by the separate `time_directive` plan — leave it free
  here.
- Do not edit historical SDD files (`sdd/tales/`, `sdd/prompts/`, `sdd/legends/`, `sdd/epics/`, `sdd/research/`,
  `sdd/beads/issues.jsonl`). These are immutable transcripts of past work. Only the two new plan/prompt files for _this_
  change get written.
- Do not touch the sibling repos (already done) or chezmoi (already done).
- Do not touch the `bead/mutation.rs`, `bead/wire.rs`, `bead/jsonl.rs` test fixtures in `../sase-core` that contain
  `%tag:bad` strings — those test rejection of invalid embedded directives in the bead `model` field, and the literal
  string is incidental.

## Implementation Plan

### 1. Directive parser (`src/sase/xprompt/`)

**`_directive_types.py`**

- Replace `"tag"` with `"group"` in `_KNOWN_DIRECTIVES`.
- Remove the `"t": "tag"` entry from `_DIRECTIVE_ALIASES` and add `"g": "group"`.
- Leave `PromptDirectives.tag: str | None` field unchanged (internal name preserved).

**`directives.py`**

- In `extract_prompt_directives()`, change the lookup `expanded_args.get("tag")` to `expanded_args.get("group")` and the
  `"tag" in expanded_args` check to `"group" in expanded_args`.
- Update the two `DirectiveError` messages from `"Invalid '%tag' value: ..."` and
  `"'%tag' directive requires a tag name argument (e.g., %tag:review)"` to use `%group` and `%group:review`.
- Build the `PromptDirectives(... tag=parsed_tag, ...)` call still passes into the `tag` field (this is intentional —
  internal name preserved).

### 2. Prompt generation

**`src/sase/bead/work.py`**

- Change `_tag_directive()` to emit `f"%group:{bead_id}"`. Rename the helper to `_group_directive()` for clarity and
  update the four call sites (lines ~328, 339, 376, 393).

**`xprompts/pylimit_split.yml`**

- Replace `%tag:chop` with `%group:chop` on line 39.

### 3. Comments referencing the directive

**`src/sase/axe/run_agent_phases.py`** — update the `%tag` comment on line 200 to `%group`. This is presentation-only;
behavior is unchanged because the parser still populates `PromptDirectives.tag`.

**`src/sase/axe/runner_utils.py`** — update the `%tag:review` example in the docstring on line 229 to `%group:review`.

### 4. Tests

Update test files to assert the new spelling and exercise both `%group` and `%g`:

- `tests/test_directives_extract.py` — rename and update test cases that exercise `%tag` / `%t`. Add at least one `%g:`
  alias case to guard against alias regressions. Add a case asserting `%tag:foo` is left in the prompt unchanged (now an
  unknown directive).
- `tests/test_bead/test_cli_work_epic.py`, `tests/test_bead/test_cli_work_legend.py`,
  `tests/test_bead/test_work_epic_plan.py`, `tests/test_bead/test_work_legend_plan.py`,
  `tests/test_bead/test_work_rendering.py` — update assertions that expect `%tag:<bead_id>` strings in rendered prompts
  to expect `%group:<bead_id>`.
- `tests/test_axe_run_agent_phases_tags.py`, `tests/test_axe_runner_utils.py`,
  `tests/test_multi_prompt_launcher_launch.py` — replace `%tag:` with `%group:` (and `%t:` with `%g:` where the alias
  path is being tested, otherwise drop).

### 5. Docs

- `docs/xprompt.md` — update the directive table row (line ~868) and example block (lines ~910–911) so the directive
  name is `%group`, alias `%g`, and examples are `%group:review` / `%g:review`.
- `docs/ace.md` — update lines 319 and 390 to reference `%group:review` and `%group <name>`.
- `docs/axe.md` — update line 222 to reference `%group:review`.

Keep narrative wording about “tag”, “tagging”, “grouping tag”, “user-managed tag”, etc. as-is where it describes the
persisted concept rather than the directive spelling.

### 6. SDD artifacts for _this_ change

This task’s prompt and plan must be committed in the standard SDD locations:

- `sdd/prompts/202605/group_directive_rename_finish.md` — the user’s prompt with a pointer to the plan.
- `sdd/tales/202605/group_directive_rename_finish.md` — the finalized plan body (this document’s `## Goals` … `## Risks`
  sections), with `status: wip`.

Use the existing `group_directive_rename.md` pair from yesterday as the format template. Do not modify those older
files; create new `_finish` siblings.

## Verification

1. From the `sase_100` workspace root:
   - `just install`
   - `just check`
2. Targeted runs while iterating:
   - `pytest tests/test_directives_extract.py tests/test_bead -x -q`
   - `pytest tests/test_axe_run_agent_phases_tags.py tests/test_axe_runner_utils.py tests/test_multi_prompt_launcher_launch.py -x -q`
3. Final cross-cutting grep over active code and docs in `sase_100`:
   - `rg -n '%tag|%t:' src tests xprompts docs` should return only intentional non-directive matches (e.g. mutt-style
     `%t` placeholders, if any). Expected result: empty.
   - `rg -n '%group|%g:' src tests xprompts docs` should show the new spelling.
4. Do **not** re-run cargo/just in `../sase-core` or chezmoi for this change — those were verified yesterday and have no
   pending edits from this plan.

## Risks & Notes

- The `time_directive` plan (also `wip`) intends to rebind `t -> time`. This plan deliberately leaves `t` unbound after
  removing `t -> tag` so the two changes compose cleanly. If `time_directive` lands first, `t` will already be `time`
  and removing the `t -> tag` mapping will be a no-op.
- After this rename, any user prompt or stored agent prompt that still contains literal `%tag:foo` / `%t:foo` text will
  silently become a no-op (unknown `%name` left in the prompt) instead of erroring. Acceptable — matches current
  treatment of unknown directives — but worth flagging in the commit message.
- `PromptDirectives.tag` and the field-population path stay untouched. This preserves the “mixed internal/public naming”
  already documented in yesterday’s tale; comments and error text in the parser are the only place that exposes `%group`
  to users, so the parser docstring should make the mapping (`%group` → `directives.tag`) explicit.
