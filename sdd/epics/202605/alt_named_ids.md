---
create_time: 2026-05-01 17:51:30
status: done
bead_id: sase-1w
prompt: sdd/prompts/202605/alt_named_ids.md
---
# Plan: Generalize Alternation Agent Naming IDs

## Goal

Agents launched from the same logical prompt through any `%alt(...)` / `%(...)` fan-out should share the same
`<name>.<id>` naming shape that multi-model fan-out uses today, but with the id semantics requested by the user:

- `%alt` and `%` shorthand arguments may be named, and that named argument supplies `<id>`.
- Unnamed alternatives use `<N>`, the first available positive integer in that alternation set.
- `%model` / `%m` with multiple model args continues to work because it is implemented through `%alt` under the hood.

The expected user-facing shape is:

- `%name:review %alt(sec=[[security pass]], perf=[[performance pass]]) Do work` launches `review.sec` and `review.perf`.
- `%name:review %(fast=[[fast pass]], [[slow pass]]) Do work` launches `review.fast` and `review.1`.
- Multiple alternation directives keep deterministic, collision-free ids, e.g. `%alt(left=a,right=b) %alt(red=x,blue=y)`
  should produce a clear product id such as `left.red`, `left.blue`, `right.red`, `right.blue` or an explicitly
  documented equivalent.
- Existing multi-model prompts should keep their current useful suffixes (`foo.cld-opus`, `foo.gem-flash3`, etc.) unless
  this plan explicitly changes a test expectation.

## Current Shape

Key code paths found during exploration:

- `src/sase/xprompt/_directive_alt.py`
  - `split_prompt_for_models()` delegates simple cases to Rust `plan_agent_launch_fanout(..., launch_kind="model")`.
  - `_apply_multi_model_naming()` is Python-only post-processing. It detects distinct `%model` values in the split
    prompts and injects `%name:<base>.<runtime-or-model-suffix>`.
  - Pure `%alt` is currently split but deliberately not renamed when no `%model` branch exists.
- `../sase-core/crates/sase_core/src/agent_launch/mod.rs`
  - Owns Rust fan-out parsing for `multi_prompt`, `alternatives`, `model`, and `repeat`.
  - `parse_directive_args()` currently returns only positional args, so named `%alt` args are not represented.
  - `LaunchFanoutSlotWire` has `prompt`, `launch_kind`, `slot_index`, `model`, `repeat_name`, and wait metadata, but no
    general alternation id.
- `src/sase/core/agent_launch_wire.py`
  - Mirrors the Rust wire structs. Any new slot metadata must be added here and round-tripped in tests.
- Launch sites:
  - TUI single-prompt path: `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` calls `split_prompt_for_models()`
    and `_launch_multi_model_agents()`.
  - CLI daemon/CWD path: `src/sase/agent/launcher.py` detects `split_prompt_for_models()` and hands the resulting
    prompts to `launch_multi_prompt_agents()`.
  - Multi-prompt path: `src/sase/agent/multi_prompt_launcher.py` calls `split_prompt_for_models()` inside each segment,
    then fake-plans those already-mutated prompts.
- Existing tests to preserve/extend:
  - `tests/test_directives_split_alternatives.py`
  - `tests/test_directives_split_models.py`
  - `tests/test_core_agent_launch_wire.py`
  - `tests/test_multi_prompt_launcher_xprompts_models.py`
  - `tests/test_multi_prompt_launcher_launch.py`

## Design Direction

Add a general fan-out slot identity rather than treating model naming as a special case bolted onto prompt strings.

Recommended wire additions:

- Add `alt_id: str | None` to `LaunchFanoutSlotWire`.
- Optionally add `alt_path: list[str]` or `alt_indices: list[int]` if keeping product-composition details simplifies
  Rust tests. If only one field is added, prefer `alt_id` because it directly serves naming.

Recommended naming helper:

- Create a Python helper in `src/sase/xprompt/_directive_alt.py` that accepts a `LaunchFanoutPlanWire` plus optional
  local xprompts and returns prompts with names injected.
- It should replace `_apply_multi_model_naming()` as the public naming policy.
- Base resolution should reuse the existing behavior:
  - first explicit `%name:<base>` across slots wins;
  - without explicit `%name`, derive from `#resume` via `allocate_resume_name`;
  - otherwise use one `get_next_auto_name()` base for the whole fan-out.
- Id resolution:
  - If a slot has `model`, keep current model-specific id behavior for backward compatibility, except allow a user-named
    `%alt` branch to override the id for that branch if it is the actual branch id.
  - If a slot has no model, use `slot.alt_id`.
  - If there is no named id for a branch, assign first available positive integers within the alternation product after
    accounting for user-provided ids.
- Sanitize/validate ids with the same practical constraints as agent-name suffixes. Reject or normalize whitespace and
  path-like characters explicitly in one place; do not let arbitrary named-arg keys become unsafe names.

Open design choice for Phase 1:

- Decide product id composition. I recommend dot-joining the per-directive ids after compacting numeric-only paths where
  helpful:
  - `%alt(a,b)` -> `1`, `2`
  - `%alt(foo=a, bar=b)` -> `foo`, `bar`
  - `%alt(foo=a, b) %alt(x, y)` -> `foo.1`, `foo.2`, `1.1`, `1.2`
  - `%alt(foo=a, bar=b) %alt(x=y, z=w)` -> `foo.x`, `foo.z`, `bar.x`, `bar.z`

## Phase 1: Core Fan-out Metadata and Named `%alt` Parsing

Owner: Rust/core-focused agent.

Scope:

- Update `../sase-core/crates/sase_core/src/agent_launch/mod.rs` so `%alt`/`%` argument parsing preserves both value and
  optional named key.
- Extend the Cartesian product representation to carry per-branch ids through `split_prompt_for_alternatives_rust()`.
- Add `alt_id` to `LaunchFanoutSlotWire` for `alternatives` and `model` plans.
- For unnamed args, allocate integer ids deterministically from `1..` while skipping ids already used by named args in
  the same directive.
- For repeated unnamed args across multiple directives, compose ids according to the Phase 1 decision above.
- Keep prompt replacement output unchanged except that named args insert only the value, not `name=value`.

Tests:

- Rust unit tests in `../sase-core/crates/sase_core/src/agent_launch/mod.rs`:
  - `%alt(sec=[[security]],perf=[[performance]])` yields prompts without `sec=`/`perf=` and slots with `alt_id`
    `sec`/`perf`.
  - `%(fast=a,b)` yields ids `fast` and `1`.
  - multiple `%alt` directives produce deterministic product ids.
  - `%model(opus,sonnet)` still exposes model metadata.
- Python wire tests in `tests/test_core_agent_launch_wire.py`:
  - `LaunchFanoutSlotWire.alt_id` round-trips through dict conversion.
  - Rust-backed `plan_agent_launch_fanout(..., "alternatives")` exposes `alt_id`.

Validation:

- Run Rust core tests for agent launch.
- Run Python `pytest tests/test_core_agent_launch_wire.py`.

## Phase 2: Python Directive API and General Name Injection

Owner: Python directive/naming agent.

Scope:

- Mirror the `alt_id` field in `src/sase/core/agent_launch_wire.py`.
- Replace `_apply_multi_model_naming(list[str])` with a helper that operates on a full `LaunchFanoutPlanWire`.
- Update `split_prompt_for_alternatives()` and `split_prompt_for_models()` so they preserve existing return signatures
  where needed, but internally use the richer plan.
- Add a new internal function if useful, e.g. `plan_prompt_variants_for_models()` or
  `apply_fanout_naming(plan, extra_xprompts=...)`, so launch paths that need ids are not forced through a lossy
  `list[str]`.
- Pure `%alt` fan-outs should now inject `%name:<base>.<id>` for each slot.
- Multi-model fan-outs should keep current naming expectations for existing model-only tests.
- Named `%alt` args that wrap model directives should be able to override or participate in the final id according to
  the documented Phase 1 rule.

Tests:

- Extend `tests/test_directives_split_alternatives.py`:
  - named args split to values only.
  - unnamed args still split as before.
- Extend `tests/test_directives_split_models.py`:
  - pure `%alt` now gets `%name:foo.<id>`.
  - `%(fast=..., ...)` uses `fast` and `1`.
  - `%alt(sec=%model:opus, perf=%model:sonnet)` produces names using `sec` and `perf` if that is the chosen override
    rule.
  - existing model suffix tests still pass.

Validation:

- `pytest tests/test_directives_split_alternatives.py tests/test_directives_split_models.py tests/test_core_agent_launch_wire.py`

## Phase 3: Launch Path Integration for TUI, CLI, and Multi-prompt

Owner: launch integration agent.

Scope:

- Update TUI multi-model/alt launch path to use the richer named variants. The current
  `_launch_multi_model_agents(model_prompts, ...)` can either be renamed to a general fan-out launcher or accept
  already-named prompts while using a more accurate `fanout_kind`.
- Update `src/sase/agent/launcher.py` alt-split daemon/CWD path so all `%alt` fan-outs, not just model fan-outs, use the
  new naming behavior.
- Update `src/sase/main/query_handler/special_cases.py` messages only if needed to avoid misleading “multi-model”
  wording for pure alternations.
- Update `src/sase/agent/multi_prompt_launcher.py`:
  - when a segment fans out through `%alt`, each sub-agent gets its planned named prompt;
  - the following bare `%wait` targets the final launched slot's planned name, preserving current multi-model behavior.
- Ensure local xprompt model shorthand handling still has access to `extra_xprompts` for model alias naming.

Tests:

- Extend `tests/test_multi_prompt_launcher_xprompts_models.py` with pure `%alt` segment cases and following bare
  `%wait`.
- Add/extend CLI/TUI launch tests to assert spawned prompts contain `%name:<base>.<id>` for pure alternations.
- Preserve current multi-model launch tests.

Validation:

- `pytest tests/test_multi_prompt_launcher_xprompts_models.py tests/test_multi_prompt_launcher_launch.py tests/test_agent_launch_executor.py`

## Phase 4: Collision, Resume, and UX Hardening

Owner: polish/integration agent.

Scope:

- Add tests for active-name collisions:
  - auto base allocation skips occupied bases.
  - explicit `%name:<base>` still lets `claim_agent_name(..., explicit=True)` handle collisions as today.
  - generated suffix ids do not collide within the same fan-out when named ids include numeric strings.
- Add tests for `#resume` base allocation with pure `%alt`.
- Audit prompt history/raw prompt persistence to ensure user input is preserved, while child prompts contain injected
  names only at spawn time.
- Audit docs/help text if `%alt` is documented in command catalog, xprompt docs, or user-facing help.

Tests:

- Focused additions to `tests/test_agent_names.py`, `tests/test_agent_names_auto_name.py`, or new directive-naming tests
  as appropriate.
- Run all tests touched by Phases 1-3.

Validation:

- `just install` if this workspace has not been set up recently.
- `just check` before final completion, per repo memory.

## Sequencing Notes

- Do Phase 1 before Python implementation work. Without `alt_id` in Rust fan-out plans, Python can only infer ids from
  rewritten prompt strings, which would be brittle and would reimplement core parsing across the boundary.
- Do Phase 2 before launch integration. It should provide one Python naming API that all launch sites can share.
- Keep implementation agents from overlapping write sets:
  - Phase 1 owns `../sase-core/crates/sase_core/src/agent_launch/mod.rs` and wire metadata shape changes plus the Python
    mirror in a minimal pass if needed for tests.
  - Phase 2 owns `src/sase/xprompt/_directive_alt.py`, `src/sase/core/agent_launch_wire.py`, and directive tests.
  - Phase 3 owns launch-site files and launch tests.
  - Phase 4 owns cleanup, docs/help, and collision/resume tests.

## Risks

- The current public `split_prompt_for_models()` API returns only prompts, so adding ids requires either a new internal
  plan-returning API or careful preservation of existing call sites.
- Model naming currently depends on Python provider/model alias maps, including local xprompts. Keep that logic in
  Python; Rust should only provide generic slot identity and raw model metadata.
- Named args for `%alt` use the same parser surface as xprompt arguments. `foo=bar` must mean “branch id `foo`, branch
  prompt `bar`” inside `%alt`, but existing non-alt directive named-arg behavior should not change.
- Numeric named ids can conflict with generated numeric ids. The rule must be deterministic and tested.
