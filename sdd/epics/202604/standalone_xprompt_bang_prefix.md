---
create_time: 2026-04-29 23:28:54
status: done
bead_id: sase-1g
prompt: sdd/prompts/202604/standalone_xprompt_bang_prefix.md
---
# Plan: Require `#!` for standalone xprompt workflows

## Goal

Separate inline xprompt/template references from standalone xprompt workflow references by requiring standalone
workflows to use the `#!name` prefix instead of bare `#name`.

Definitions for this plan:

- Inline-capable xprompt/template reference: a prompt or workflow that can contribute text to a containing prompt. It
  continues to use `#name`.
- Standalone xprompt workflow: a YAML workflow with no `prompt_part` step. It must be referenced as `#!name` in new
  user-facing syntax.
- Compatibility window: existing top-level and mixed-wrapper bare `#standalone` invocations should continue to run for
  now, but they should warn and point users to `#!standalone`.
- Embedding safety: any expansion site that would send literal `#standalone` or `#!standalone` into an LLM prompt should
  fail loudly with a clear error instead of silently passing through.

This work spans the main `sase` repo and the sibling `../sase-nvim` repo. Each phase below is intended for a distinct
agent instance.

## Key Constraints

- Do not treat multi-agent markdown xprompts as standalone YAML workflows. They remain `#name` and keep their existing
  sole-segment usage checks.
- Use the existing semantic predicate as the source of truth: standalone workflow means
  `not workflow.has_prompt_part()`.
- Preserve mixed wrapper prompts such as `#gh:sase #!sase/pylimit_split %model:...`.
- Preserve HITL suffixes: `#!sync!!` and `#!sync??` should parse as standalone workflow `sync` plus HITL override.
- Avoid one-off regex edits. The current `#name` grammar is duplicated in processor, embedded-workflow expansion,
  workflow runner, SDD dry expansion, validator extraction, and multi-agent code. Add shared parsing utilities before
  changing behavior broadly.
- `#@` picker functionality must remain supported in both the TUI prompt input widget and `../sase-nvim`; selecting a
  standalone workflow should insert `#!name`, while selecting inline-capable entries should insert `#name`.

## Phase 1: Shared Reference Model And Prompt Kind

Owner focus: main `sase` repo parser/model foundations.

1. Add a small shared xprompt reference model, likely in `src/sase/xprompt/_parsing.py` or a new
   `src/sase/xprompt/references.py`.
2. The model should represent:
   - marker kind: inline `#` vs standalone `#!`
   - normalized name
   - span start/end
   - raw matched text
   - paren/colon/plus/shorthand argument details, or enough data for existing arg parsing helpers to consume
3. Centralize the reference regex fragments so future call sites can match both `#name` and `#!name` consistently.
4. Add a workflow-kind helper, either a property/function or enum, with at least:
   - `simple_xprompt`
   - `embeddable_workflow`
   - `standalone_workflow`
5. Keep kind classification based on existing `Workflow` predicates first. Do not require new loader metadata to
   identify standalone YAML workflows.
6. Add focused tests for reference parsing:
   - `#commit`
   - `#!sync`
   - `#!sync!!`
   - `#!sase/pylimit_split:prod`
   - `#!deploy(arg=value)`
   - references inside fenced blocks can still be filtered by callers
   - `# Heading` remains non-matchable

Primary files:

- `src/sase/xprompt/_parsing.py`
- `src/sase/xprompt/workflow_models.py`
- `tests/test_xprompt_processor_shorthand.py` or a new parser-focused test module

Acceptance:

- Existing parser tests pass.
- New parser tests document the `#!` grammar and HITL order.
- No behavior change is required yet outside the new helper surface.

## Phase 2: Execution Semantics And Compatibility Warnings

Owner focus: main `sase` repo execution paths.

1. Update top-level `sase run` special handling in `src/sase/main/query_handler/special_cases.py`:
   - accept `#!name`
   - only allow `#!name` when the resolved workflow is standalone
   - keep bare `#standalone` working with a deprecation warning for now
   - reject `#!commit` / `#!gh:sase` with a clear message because they have `prompt_part`
2. Update anonymous workflow flattening in `src/sase/xprompt/workflow_runner.py`:
   - fast path handles single `#!standalone`
   - slow path handles mixed wrappers like `#gh:sase #!sase/pylimit_split`
   - compatibility path still finds exactly one bare `#standalone`, warns, and flattens
   - prefer explicit `#!` if both explicit and legacy standalone references are present, but reject ambiguous multiple
     standalone references
3. Update TUI standalone workflow execution in `src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py`:
   - accept prompts beginning with `#!`
   - keep legacy bare `#standalone` working with a warning/notification
   - return `False` for embeddable workflows as today, unless they are incorrectly referenced with `#!`, in which case
     notify clearly
4. Make daemon/runner paths preserve `#!` prompts until the anonymous workflow flattening layer consumes them.
5. Add or update tests around `_flatten_anonymous_workflow`, `execute_workflow`, and TUI `_try_execute_workflow`.

Primary files:

- `src/sase/main/query_handler/special_cases.py`
- `src/sase/xprompt/workflow_runner.py`
- `src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py`
- `tests/test_xprompt_processor_workflow.py`
- TUI workflow execution tests if present, otherwise add focused pure-unit coverage

Acceptance:

- `sase run '#!sync'` executes the standalone workflow.
- `sase run '#sync'` still executes during the compatibility window and emits a deprecation warning.
- `#gh:sase #!sase/pylimit_split` flattens to `sase/pylimit_split`.
- `#!commit` errors clearly.
- `#!sync!!` preserves HITL override semantics.

## Phase 3: Expansion-Site Safety

Owner focus: main `sase` repo prompt expansion and spec expansion.

1. Update top-level embedded workflow expansion in `src/sase/main/query_handler/_embedded_workflows.py`:
   - `#standalone` in an inline expansion context should raise a clear error: use `#!standalone` as a standalone
     workflow, not inside inline text.
   - `#!standalone` in a true inline expansion context should also error unless the caller is the anonymous-workflow
     flattening path that is explicitly allowed to execute it.
   - `#!embeddable` should error with "only standalone workflows use `#!`".
2. Update workflow-step embedded expansion in `src/sase/xprompt/workflow_executor_steps_embedded_expand.py` similarly.
   Replace the current warning-and-literal passthrough for no-`prompt_part` workflows with a hard error.
3. Update SDD/spec dry expansion in `src/sase/sdd/files.py`:
   - decide on and document behavior for standalone workflow references in stored expanded prompts
   - recommended behavior: preserve a compact marker for `#!standalone` rather than trying to inline it, and error on
     legacy `#standalone` so specs stop capturing ambiguous syntax
4. Update any validator extraction that assumes only `#name` so validation errors point at the right marker.
5. Add regression tests for inline rejection and dry expansion behavior.

Primary files:

- `src/sase/main/query_handler/_embedded_workflows.py`
- `src/sase/xprompt/workflow_executor_steps_embedded_expand.py`
- `src/sase/xprompt/workflow_executor_steps_embedded_types.py`
- `src/sase/sdd/files.py`
- `src/sase/xprompt/workflow_validator_extract.py`
- `tests/test_expand_for_spec.py`

Acceptance:

- Standalone workflows no longer silently pass through into LLM prompts as literal `#name`.
- Error messages name the workflow and the correct replacement syntax.
- Fenced code blocks remain protected.
- Embeddable workflows keep expanding with `#name` as before.

## Phase 4: Catalog, Completion, And TUI Picker Insertion

Owner focus: main `sase` repo discovery and TUI UX.

1. Update `sase xprompt list` output in `src/sase/main/xprompt_handler.py`:
   - keep backward-compatible `type` values if needed, but add a stable `kind` field such as `xprompt`,
     `embeddable_workflow`, `standalone_workflow`
   - add an `insertion` or `prefix` field so clients do not re-derive syntax
2. Update TUI xprompt select modal:
   - display standalone workflows with `#!name`
   - return an insertion string or structured item instead of only the bare name, so `#@` can insert the right marker
3. Update `PromptInputBar.insert_snippet()`:
   - current behavior assumes the `#` from `#@` is already present and appends only the selected name
   - when selected item is standalone, insert `!name` after the existing `#`
   - for non-standalone entries, keep appending only `name`
4. Update Ctrl+T xprompt completion in `src/sase/ace/tui/widgets/xprompt_completion.py`:
   - standalone candidates should have insertion `#!name`
   - completion display should show `#!` for standalone and `#` for everything else
   - token detection should recognize both `#foo` and `#!foo` as xprompt-like tokens
   - decide whether typing `#!` filters only standalone workflows; recommended yes
5. Update TUI preview/browser labels to distinguish embeddable vs standalone workflows.

Primary files:

- `src/sase/main/xprompt_handler.py`
- `src/sase/ace/tui/modals/xprompt_select_modal.py`
- `src/sase/ace/tui/modals/xprompt_browser_modal.py`
- `src/sase/ace/tui/widgets/prompt_input_bar.py`
- `src/sase/ace/tui/widgets/xprompt_completion.py`
- `src/sase/ace/tui/widgets/_file_completion.py`

Acceptance:

- `#@` selection of standalone workflow inserts `#!name`.
- `#@` selection of simple xprompt or embeddable workflow inserts `#name`.
- Ctrl+T completion can complete `#!sy` to `#!sync`.
- Existing clients that only understand `type` do not immediately break.

## Phase 5: `../sase-nvim` Integration

Owner focus: sibling `../sase-nvim` repo.

1. Consume the new `sase xprompt list` fields, preferring `insertion` or `kind`.
2. Update `lua/sase/xprompt.lua`:
   - insert `#!name` for standalone workflows
   - display `#!name` in picker entries
   - keep cancellation behavior for `#@` restoring a single `#`
3. Update Telescope extension display and insertion in `lua/telescope/_extensions/sase.lua`.
4. Update completion token logic in `lua/sase/complete/_token.lua`:
   - `#!foo` must be an xprompt-like token, despite `!` currently being a delimiter
   - consider `#!` as a standalone workflow filter
5. Update `lua/sase/complete/xprompt.lua` if it relies on bare-name insertion.
6. Update README docs for `#@` and completion examples.
7. Run `just check` in `../sase-nvim` after modifications.

Primary files:

- `../sase-nvim/lua/sase/xprompt.lua`
- `../sase-nvim/lua/telescope/_extensions/sase.lua`
- `../sase-nvim/lua/sase/complete/_token.lua`
- `../sase-nvim/lua/sase/complete/xprompt.lua`
- `../sase-nvim/plugin/sase_xprompt.lua`
- `../sase-nvim/README.md`

Acceptance:

- `#@` in Neovim still opens the picker.
- Selecting a standalone workflow from either fallback UI or Telescope inserts `#!name`.
- Cancelling after `#@` still restores a single `#`.
- Ctrl+T completion treats `#!` as one token.

## Phase 6: Documentation, Migration, And Examples

Owner focus: repo-wide docs/examples/config references.

1. Update user docs:
   - explain `#name` as inline/template syntax
   - explain `#!name` as standalone workflow syntax
   - use single quotes in shell examples: `sase run '#!sync'`
   - call out compatibility warning for top-level legacy `#standalone`
2. Search and migrate references to known standalone workflows:
   - built-ins: `#sync`, `#eval_parallel`, `#eval_ifs_loops`
   - project-local examples: `#sase/fix_just`, `#sase/pylimit_split`, `#sase/refresh_docs`
3. Use a catalog-aware migration script or command so namespaced local workflows are detected by `has_prompt_part()`,
   not by a hard-coded list alone.
4. Update tests and fixture strings that intentionally refer to standalone workflows.
5. Do not migrate embeddable workflows such as `#commit`, `#pr`, `#propose`, `#git`, `#mentor`, or VCS wrappers.
6. Search external config locations only if needed for local workflow examples:
   - `~/.local/share/chezmoi/home/dot_config/sase/`
   - project-local `xprompts/` and `.xprompts/`

Primary files:

- `docs/xprompt.md`
- `sdd/research/` notes only if they are used as live references
- tests and examples found by `rg`
- optionally chezmoi config files if they contain live standalone workflow references

Acceptance:

- User-facing docs consistently show `#!` for standalone workflows.
- Test fixtures match intended semantics.
- No embeddable workflow references are incorrectly migrated.

## Phase 7: Final Integration Sweep

Owner focus: end-to-end verification in both repos.

1. Run the targeted tests added by each earlier phase.
2. Run main repo checks:
   - `just install`
   - `just check`
3. If `../sase-nvim` changed, run its required check:
   - `just check` from `../sase-nvim`
4. Run manual smoke commands where safe:
   - `sase xprompt list | jq 'map(select(.kind == "standalone_workflow"))[:5]'`
   - `sase xprompt explain sync` still works by bare command argument if that command expects names, not references
   - `sase run '#!sync'` only if the workflow side effects are acceptable in the current workspace
5. Verify compatibility warnings are visible but not duplicated excessively.
6. Check that prompt input picker and nvim picker still work in both simple and standalone cases.

Acceptance:

- Main repo `just check` passes.
- `../sase-nvim` `just check` passes if modified.
- No path leaves literal standalone workflow references in prompts sent to agents.
- New syntax is documented, discoverable, and inserted automatically by picker/completion UIs.

## Suggested Phase Dependencies

- Phase 1 must land first.
- Phases 2 and 3 both depend on Phase 1 and can be split after the shared parser/kind API exists.
- Phase 4 depends on Phase 1, and benefits from Phase 2's final insertion semantics.
- Phase 5 depends on Phase 4's `sase xprompt list` API shape.
- Phase 6 can start after Phase 2 clarifies final warning/error text, but final migration should wait for Phase 3.
- Phase 7 must run last.

## Risk Notes

- The biggest regression risk is split-brain parsing because `#name` patterns are duplicated. Keep the shared parser
  small but real, then migrate call sites incrementally.
- `!` is a delimiter in the current Neovim token scanner and may also affect shell history expansion. Token scanners
  must be updated, and docs should quote examples.
- Compatibility warnings should be emitted in executable standalone contexts only. Inline expansion sites should reject
  legacy `#standalone`, because silent literal passthrough is the behavior this migration is meant to remove.
