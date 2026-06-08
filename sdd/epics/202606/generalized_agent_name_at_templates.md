---
create_time: 2026-06-08 15:01:44
bead_id: sase-4g
tier: epic
status: done
prompt: sdd/prompts/202606/generalized_agent_name_at_templates.md
---
# Generalized Agent Name `@` Templates

## Goal

Generalize the current terminal `-@` agent-name template into a reusable `@` placeholder that can appear anywhere in a
new agent name. The placeholder is replaced with the first token from the same auto-name sequence used by generated
agent names:

```text
0, 1, 2, ..., 9, a, b, ..., z, 00, 01, ...
```

The same allocator should power:

- Explicit template names, such as `%name:build-@`, `%name:@.cld`, `%name:research.@.final`.
- Intra-launch references, such as `%wait:build-@` and `#fork:research.@.final`.
- Generated names, by treating unnamed launches as if they had `%name:@`.
- Fan-out generated names, by treating unnamed model/alt branches as templates such as `%name:@.cld`.

This plan intentionally separates pure template semantics from launch-surface wiring. Each phase is suitable for a
separate agent instance.

## Current State

- `src/sase/agent/names/_indexed.py` owns the existing terminal `-@` syntax.
  - Allocation currently produces positive integers: `build-1`, `build-2`, ...
  - Latest-reference resolution currently selects the highest positive integer concrete name.
- Auto-generated names use the alphanumeric shortlex sequence in `src/sase/agent/names/_auto.py`.
- `src/sase/agent/multi_prompt_references.py::PlannedNameAllocator` already reserves planned names and rewrites indexed
  `%wait` / `#fork` references within a multi-prompt launch.
- Multi-model and `%alt` fan-out currently inject concrete `%name:<base>.<suffix>` lines in
  `src/sase/xprompt/_directive_alt.py`.
- Child-side fallback allocation happens in `src/sase/axe/run_agent_directives.py`, which still allocates terminal `-@`
  templates if the parent did not resolve them first.
- Fan-out shape is Rust-backed in `../sase-core/crates/sase_core/src/agent_launch/mod.rs`, while registry-backed name
  ownership is still Python-side.

## Target Contract

- A template is an agent name containing exactly one `@` marker. Examples: `@`, `build-@`, `@.cld`, `research.@.final`.
- Multiple `@` markers are rejected for now. Historical artifact names containing literal `@` remain readable, but new
  `%name` values use `@` as template syntax.
- A concrete candidate is produced by replacing `@` with a token from the auto-name sequence.
- Allocation chooses the first token whose rendered candidate is available according to the durable name registry and
  planned reservations.
- `build-@` remains valid, but new allocations start at `build-0`.
- Template references in `%wait` and `#fork` resolve in this order:
  1. A planned concrete name earlier in the same launch batch.
  2. The highest existing concrete token under the alphanumeric sequence.
  3. A typed error if no concrete name exists.
- Forced reuse (`%name:!foo`) cannot be combined with templates.
- Names containing the reserved agent-family separator `--` remain invalid for user-authored names after template
  rendering, unless an existing trusted internal bypass is enabled.
- Parent-side planning should be the normal path for launch batches. Child-side template allocation remains as a
  compatibility fallback and final safety net.

## Phase 1 - Template Primitives and Compatibility API

Scope:

- Add a small pure "agent name template" API, preferably backed by `sase-core` for parser/render/match/order semantics
  and exposed through the existing Python binding boundary.
- Add or mirror a thin Python adapter under `src/sase/agent/names/` for registry-backed callers.
- Keep the old public "indexed" functions as compatibility wrappers during the transition.

Key design points:

- Define one sequence implementation and use it for both plain auto names and template tokens.
- Parse and validate exactly-one-marker templates.
- Render `template + token -> concrete name`.
- Match `template + concrete name -> token | None`.
- Compare tokens by auto-sequence order, not lexical or decimal integer order.
- Treat `-@` as just another template shape, not a special suffix.

Tests:

- Rust unit tests for parser/render/match/order.
- Python tests for wrapper behavior:
  - `@` renders `0`, `1`, ...
  - `build-@` renders `build-0`, `build-1`, ...
  - `@.cld` renders `0.cld`, `1.cld`, ...
  - `research.@.final` renders `research.0.final`, `research.1.final`, ...
  - multiple markers are rejected.
  - legacy `build-1` and new `build-a` both match `build-@`.

Done when:

- No launch behavior changes yet, except compatibility tests proving the new primitives can reproduce the planned
  template behavior.

## Phase 2 - Registry-Backed Allocation and Directive Validation

Scope:

- Replace positive-integer indexed allocation with generic template allocation.
- Make `get_next_auto_name()` and `allocate_auto_names()` delegate to the same template allocator using `@`.
- Update directive extraction and launch validation to recognize any `@` template, not only terminal `-@`.

Implementation areas:

- `src/sase/agent/names/_auto.py`
- `src/sase/agent/names/_indexed.py` or a replacement `_templates.py`
- `src/sase/agent/names/__init__.py`
- `src/sase/xprompt/directives.py`
- `src/sase/agent/launch_validation.py`
- `src/sase/axe/run_agent_directives.py`

Key design points:

- `allocate_indexed_agent_name("build-@")` should become a compatibility wrapper around
  `allocate_agent_name_template("build-@")` and return `build-0` when free.
- `is_indexed_agent_name_template()` can remain temporarily as an alias for `is_agent_name_template()` so existing call
  sites can migrate incrementally.
- `PromptDirectives` should grow template-neutral names, for example `name_template` / `name_template_base`, while
  preserving old fields until downstream code is migrated.
- Child-side fallback should:
  - accept any single-marker template.
  - use `SASE_AGENT_PLANNED_NAME` when it is a valid concrete rendering of the template.
  - allocate under the name allocation lock otherwise.
  - write `agent_name_template` metadata for any template-originated name.

Tests:

- Update `tests/test_agent_names_indexed.py` or split it into template tests.
- Update `tests/test_directives_name.py` for `%name:@`, `%name:@.cld`, `%name:build-@`.
- Update `tests/test_directives_wait.py` for generic template reference resolution.
- Update `tests/test_agent_names_auto_name.py` to prove plain auto names use the template path.
- Add child-runner tests where `%name:@.cld` accepts a matching planned name and falls back safely without one.

Done when:

- Single-agent launches and child-side directive parsing support generic templates.
- Existing `-@` behavior is still accepted, with the new alphanumeric token sequence.

## Phase 3 - Parent-Side Planned Template Allocation

Scope:

- Generalize `PlannedNameAllocator` from "indexed" names to generic templates.
- Resolve and reserve template names before spawning every slot in a launch plan.
- Rewrite `%wait:<template>` and `#fork:<template>` references against the current launch's planned names.

Implementation areas:

- `src/sase/agent/multi_prompt_references.py`
- `src/sase/agent/multi_prompt_launcher.py`
- `src/sase/agent/launch_executor.py`
- `src/sase/agent/launch_validation.py`

Key design points:

- Rename internal `_indexed_*` fields and methods to template-neutral names.
- Keep planned reservations rollback-safe: if a later slot fails before spawn, release reservations for children that
  were not actually started.
- Preserve current intra-batch semantics:
  - `%name:build-@` followed by `%wait:build-@` resolves the wait to the planned concrete name from the earlier slot.
  - Two identical `%name:build-@` slots allocate distinct names, such as `build-0` and `build-1`.
  - Related legacy research-style templates such as `research.cdx-@` and `research.final-@` continue to share a token
    within one workflow when the existing grouping heuristic applies.
- Add a template group abstraction for call sites that know multiple concrete names should share the same token. This is
  needed before multi-model `@.cld` / `@.cdx` fan-out can be fully correct.

Tests:

- Update `tests/test_multi_prompt_launcher_launch_planning.py`:
  - `build-@` uses `build-0`, `build-1`, ...
  - `%wait:build-@` rewrites to the earlier planned concrete name.
  - `#fork:build-@` rewrites to the earlier planned concrete name.
  - concurrent launch batches reserve distinct template names.
  - uncommitted planned reservations are released on failure.
- Add generic-shape cases:
  - `%name:@.cld`
  - `%name:research.@.final`
  - `%wait:research.@.final`

Done when:

- Multi-prompt launches use generic template planning with concurrency safety.
- No call site depends on terminal `-@` for planned allocation.

## Phase 4 - Auto-Name Injection and Fan-Out Naming

Scope:

- Implement the user's requested unification: generated names should be represented as `%name:@` or derived template
  forms before allocation.
- Update model and alt fan-out naming so generated fan-out names come from the same template allocator.

Implementation areas:

- `src/sase/xprompt/_directive_alt.py`
- `src/sase/agent/multi_prompt_launcher.py`
- `src/sase/agent/launch_cwd.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_multi_model.py`
- `src/sase/main/query_handler/special_cases.py`

Key design points:

- For unnamed single-agent launches, normalize internally to a `%name:@` template while preserving user-facing raw
  prompt artifacts.
- Preserve the old `name_explicit=False` semantics for truly generated names. If the child sees an injected `%name:@`,
  carry an internal flag or env hint so generated names are not treated as user-explicit names for validation and
  metadata semantics.
- For unnamed multi-model fan-out, inject per-slot templates such as:
  - `%name:@.cld`
  - `%name:@.cdx`
  - `%name:@.gem_flash25`
- Allocate those templates as one group so a two-model fan-out produces `0.cld` and `0.cdx`, not `0.cld` and `1.cdx`.
- For explicit template bases plus fan-out, allow and preserve the user's shape:
  - `%name:review-@` with `%m(opus,gpt-5.5)` becomes grouped templates like `review-@.cld` and `review-@.cdx`,
    allocating `review-0.cld` and `review-0.cdx`.
- For explicit concrete bases plus fan-out, preserve existing concrete behavior:
  - `%name:review` with `%m(...)` remains `review.cld`, `review.cdx`, etc.

Tests:

- Update `tests/test_directives_split_models.py`:
  - no-name multi-model fan-out injects `@.<suffix>` templates and resolves to grouped concrete names.
  - bare `%name` behaves the same as no `%name`.
  - explicit concrete base behavior is unchanged.
  - explicit template base is now allowed and grouped.
- Update `tests/test_multi_prompt_launcher_xprompts_models.py`:
  - following bare `%wait` waits on the last generated concrete name.
  - local xprompt model aliases still influence suffixes.
- Add launch-surface parity tests for TUI, cwd, and CLI query handler paths.

Done when:

- Auto-generated names and generated fan-out names no longer call a separate auto-name path except through the shared
  template allocator.

## Phase 5 - Repeat, Retry, Resume, History, and Reference Cleanup

Scope:

- Finish the migration across peripheral naming features.
- Decide and document how templates interact with repeat batches and resume/retry derived names.

Implementation areas:

- `src/sase/agent/repeat_launcher.py`
- `src/sase/agent/names/_resume.py`
- `src/sase/agent/names/_retry.py`
- `src/sase/history/chat.py`
- `src/sase/history/prompt.py`
- `src/sase/agent/retry_prompt.py`
- `src/sase/agent/launch_validation.py`

Key design points:

- Keep `%repeat` plus a template name rejected unless this phase deliberately implements grouped repeat templates.
  Current repeat semantics already build `<base>.<k>` names, and mixing them with `@` should not be half-supported.
- Resume and wait derived names (`.f<N>`, `.w<N>`) can stay integer-based unless the user explicitly wants them moved to
  the alphanumeric sequence. This plan only changes the `@` placeholder and plain auto names.
- History sanitization should strip injected internal `%name:@...` directives from resume prompts when appropriate, just
  as it strips existing auto `%name` directives today.
- Agent chat resolution by template should use generic template matching and sequence ordering, not terminal `-@`.

Tests:

- Update `tests/test_repeat_launcher.py` for template rejection wording and `%name:@` handling.
- Update history resume/sanitize tests so injected template names do not leak into retry prompts.
- Update `tests/test_agent_chat_from_name.py` to resolve generic template references.
- Add regression tests for old `build-1` histories remaining resolvable through `build-@`.

Done when:

- All non-launch naming features either support generic templates or reject them with clear errors.

## Phase 6 - Built-In Prompts, Docs, and Terminology Cleanup

Scope:

- Update shipped xprompts and documentation to prefer the new generalized syntax where it improves readability.
- Remove or de-emphasize "indexed agent name" terminology after compatibility wrappers are no longer central.

Implementation areas:

- `src/sase/default_xprompts/`
- `xprompts/`
- tests that assert exact built-in xprompt text, especially `tests/test_xprompt_loader_config.py`
- user-facing docs and help text mentioning `-@` or "indexed agent names"

Key design points:

- Existing `research.cdx-@` and similar prompts may remain valid. Change them only when the new form makes dependency
  relationships clearer.
- Candidate update patterns:
  - Keep `research.cdx-@` / `research.final-@` if the role-before-token shape is preferred.
  - Or move to `research.@.cdx` / `research.@.final` if grouping by shared token should be visually obvious.
- Update examples to show `@`, `@.cld`, `build-@`, and `research.@.final`.
- Add a short migration note: old terminal `-@` still works, but allocations now start at token `0` and proceed through
  the alphanumeric sequence.

Tests:

- Run focused xprompt loader tests after text updates.
- Run the launch/name-related subset from prior phases.
- Final phase should run `just install` and `just check`.

Done when:

- User-facing examples and test expectations match the generalized syntax.
- Internal names and docs no longer imply that only terminal `-@` is supported.

## Cross-Phase Acceptance Criteria

- `%name:@` allocates the same concrete name `get_next_auto_name()` would have returned before this work.
- `%name:build-@` allocates `build-0` first, then `build-1`, ..., `build-a`, ...
- `%name:@.cld` allocates `0.cld` first when free.
- `%name:research.@.final` allocates `research.0.final` first when free.
- `%wait:<template>` and `#fork:<template>` resolve to planned same-batch names before falling back to historical names.
- Concurrent multi-prompt batches cannot choose the same rendered template name.
- Forced reuse plus any template is rejected.
- Literal historical names containing `@` remain loadable/resolvable as stored artifact data.
- No runtime-specific branches are introduced for Claude, Gemini, Codex, Qwen, or OpenCode.

## Suggested Verification Matrix

Run focused tests after each phase:

```bash
pytest tests/test_agent_names_auto_name.py tests/test_agent_names_indexed.py tests/test_directives_name.py tests/test_directives_wait.py
pytest tests/test_multi_prompt_launcher_launch_planning.py tests/test_multi_prompt_launcher_xprompts_models.py
pytest tests/test_directives_split_models.py tests/test_repeat_launcher.py tests/test_agent_launch_validation.py
```

Run final repository verification after code changes:

```bash
just install
just check
```
