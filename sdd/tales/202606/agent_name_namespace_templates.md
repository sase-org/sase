---
create_time: 2026-06-09 11:20:07
status: done
prompt: sdd/prompts/202606/agent_name_namespace_templates.md
---
# Namespace-Aware Agent Name Template Allocation

## Goal

Update generic `%name` `@` template allocation so template tokens allocate unused namespaces, not just unused concrete
rendered names, while preserving fast parent-side planning for single launches, multi-prompt launches, multi-agent
xprompts, and multi-model fan-out.

I interpret "the period to the left of the @ example" as the first period after the `@` marker, because `foo.@.bar`
should allocate under the `foo.<X>` namespace. Concretely:

- `@.cld` renders candidate `0.cld` but reserves namespace `0`.
- `foo.@.bar` renders candidate `foo.0.bar` but reserves namespace `foo.0`.
- `foo.@x.bar` renders candidate `foo.0x.bar` but reserves namespace `foo.0x`.
- `foo-@` renders candidate `foo-0` and treats the whole rendered candidate as the namespace.
- `@` renders candidate `0` and treats the whole rendered candidate as the namespace.

A namespace is unavailable when any pre-existing or previously planned agent is named exactly that namespace, or has a
name below it using the dot separator. This should be implemented as exact namespace or `namespace + "."`, not raw
string prefix matching, so `research.1` does not collide with `research.10`.

## Current State

- Pure template parse/render/match/token-order helpers live in
  `../sase-core/crates/sase_core/src/agent_name_template.rs` and are exposed to Python through `sase_core_rs`.
- Registry-backed allocation is currently Python-side in `src/sase/agent/names/_templates.py`.
- `allocate_agent_name_template()` currently chooses the first rendered candidate that is not an exact member of the
  reserved-name set.
- `PlannedNameAllocator` in `src/sase/agent/multi_prompt_reference_allocator.py` caches a reserved-name snapshot, tracks
  latest planned template names, and has an explicit group API for fan-out.
- `launch_multi_prompt_agents()` groups template slots for one fan-out plan, but ordinary multi-agent xprompt expansion
  currently returns only `list[str]`, so the fact that several segments came from one xprompt file is lost before name
  planning.
- Child-side fallback in `src/sase/axe/run_agent_directives.py` still calls `allocate_agent_name_template()` when the
  parent did not provide a planned concrete name.

## Target Contract

- Every template allocation checks the namespace rendered by that same token.
- For templates with a period after `@`, the namespace template is the substring through the characters before that
  period. For templates without a period after `@`, the namespace template is the whole template.
- A grouped allocation may render multiple distinct concrete names under the same namespace in the same group. Those
  siblings do not block one another, but any prior registry or prior planned name outside the group does block the
  token.
- Duplicate templates in one group cannot render duplicate concrete names. Preserve existing unique-name behavior by
  allocating duplicate rendered shapes as separate occurrence groups, or reject them with a targeted error if an
  existing caller expects one concrete name per slot.
- All template names from one multi-agent xprompt file invocation share one token. Two invocations of the same xprompt
  in one submitted prompt must get different groups and therefore different namespaces.
- Generated multi-model names such as `@.cld` and `@.cdx` share one token, and token `X` is skipped when `X` or any
  `X.*` name already exists before the fan-out launch.
- Child-side allocation remains a compatibility fallback, but the normal path should be parent-side planned allocation
  with durable planned reservations.

## Implementation Plan

1. Add pure namespace-template primitives.
   - In `sase-core`, add a helper that returns the namespace template for a parsed template.
   - Expose it through `sase_core_py` and add Python wrappers in `src/sase/agent/names/_templates.py`.
   - Add Rust and Python tests for `@`, `@.cld`, `foo-@`, `foo.@.bar`, and `foo.@x.bar`.

2. Add an efficient namespace reservation index.
   - Build an index from a reserved-name snapshot by adding every name and each dotted prefix of that name. Example:
     `foo.0.final` contributes `foo`, `foo.0`, and `foo.0.final`.
   - Keep exact reserved names separately for duplicate concrete-name checks.
   - Update the index incrementally whenever a planned name is reserved.
   - Add an internal batch/group allocation API so parent planning can allocate several templates against one snapshot
     without rebuilding the namespace index per slot.

3. Make registry planned reservations namespace-aware.
   - Add a planned-template reservation helper that receives `(candidate_name, namespace, artifacts_dir)`.
   - For group reservations, reserve all `(name, namespace)` pairs atomically and allow repeated namespaces inside the
     group.
   - Recheck against the current registry under the allocation lock so stale parent snapshots cannot allocate `0.cld`
     after another launcher has planned `0.cdx`.
   - Keep ordinary explicit concrete name claims exact-name based unless they came from template allocation.

4. Update template allocation paths.
   - Change `allocate_agent_name_template()` and `allocate_auto_names()` to use namespace availability.
   - Update `PlannedNameAllocator._allocate_template_name()` and `planned_names_for_template_group()` to use the same
     namespace index and group namespace allowance.
   - Track group token plus group-owned namespaces, so later slots in the same group can reuse the token even though an
     earlier sibling already registered a descendant name.
   - Preserve current latest-reference behavior: `%wait:<template>` and `#fork:<template>` still resolve to planned
     names first, then the latest existing concrete match.

5. Preserve xprompt-file grouping through expansion.
   - Add a metadata-preserving expansion path, for example `expand_multi_agent_xprompts_with_metadata()`, returning
     segment records with `prompt` and optional `template_group`.
   - Keep the existing `expand_multi_agent_xprompts()` API as a string-only compatibility wrapper.
   - Give every multi-agent xprompt invocation a unique group id, such as `xprompt:<name>:<counter>`, and assign that id
     to all segments rendered from that file invocation, including recursive expansions.
   - Thread the group metadata through `launch_agents_from_cwd()`, daemon/query dispatch paths that expand multi-agent
     xprompts, and `launch_multi_prompt_agents()`.

6. Apply grouping in multi-prompt and fan-out planning.
   - Extend `launch_multi_prompt_agents()` with an optional `segment_template_groups` sequence matching the expanded
     segments.
   - When a segment has an xprompt group, pass that group to `PlannedNameAllocator` for explicit templates and any
     fan-out slots produced from that segment.
   - When no xprompt group exists but a multi-model or `%alt` fan-out produces multiple template names, keep the
     existing fan-out group behavior.
   - Ensure group allocation is rollback-safe with the existing uncommitted planned reservation cleanup.

7. Keep child fallback correct.
   - In `run_agent_directives.py`, planned names that match the template remain accepted.
   - Fallback calls to `allocate_agent_name_template()` automatically pick namespace-safe names.
   - Metadata should continue to write `agent_name_template` for template-originated names.

8. Tests and verification.
   - Add unit tests for namespace-template derivation and occupied namespace indexing.
   - Update `tests/test_agent_name_templates.py` so `@.cld` skips `0` when `0` or `0.cdx` exists, and `foo.@.bar` skips
     `0` when `foo.0` or `foo.0.any` exists.
   - Update auto-name tests so `@` skips names with existing descendants like `0.cdx`.
   - Update planned-name tests for stale snapshots: a stale allocator must not allocate `0.cld` after a fresh allocator
     planned `0.cdx`.
   - Add xprompt integration tests showing `research.@.cdx`, `research.@.cld`, `research.@.final`, and
     `research.@.image` all use one `research.<X>` prefix, and that an existing `research.0` or `research.0.any` forces
     `research.1.*`.
   - Add a two-invocation test for the same multi-agent xprompt producing two distinct namespaces.
   - Add multi-model tests showing existing `0`, `0.cld`, or `0.any` forces generated fan-out to `1.cld` and `1.cdx`.
   - Run targeted pytest for agent-name templates, auto names, multi-prompt launch planning, multi-agent xprompt
     expansion, directives split models, and planned launch names; run `cargo test -p sase_core agent_name_template` in
     the sibling core workspace; then run `just install` and `just check` after implementation changes.

## Performance Notes

- Avoid scanning all registered names per token. Build the occupied-namespace set once from the registry snapshot and
  update it incrementally as names are planned.
- Keep the token iterator unchanged and stop as soon as a token passes namespace checks.
- Group allocations should render and check all candidate names for one token in memory, then perform one atomic
  registry reservation batch.
- Stale-snapshot recovery should be rare; when it happens, mark the rejected namespace occupied and continue rather than
  rebuilding the world repeatedly.

## Main Risks

- Xprompt expansion currently discards origin metadata, so threading segment group metadata is the main integration
  surface.
- The existing default template group heuristic may already share tokens for some unrelated templates. The new explicit
  xprompt/fan-out group ids should make the requested sharing intentional while preserving legacy behavior where tests
  cover it.
- Registry exact-name reservation is not enough for namespace allocation; planned template reservations need the
  namespace value to prevent stale-snapshot races.
