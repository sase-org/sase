---
create_time: 2026-05-27 10:53:50
status: done
prompt: sdd/prompts/202605/indexed_agent_names.md
bead_id: sase-46
tier: epic
---
# Indexed Agent Name Aliases

## Goal

Support `foobar-@` as an indexed agent-name argument:

- `%n:foobar-@` / `%name:foobar-@` allocates the first available concrete name `foobar-<N>`.
- `%w:foobar-@` / `%wait:foobar-@` resolves to the highest existing concrete name `foobar-<M>`.
- `#resume:foobar-@` and the current `#fork:foobar-@` resume syntax resolve to the same latest concrete name.
- Multi-prompt launches split by `---` can name an earlier segment with `foobar-@` and refer to it from later segments
  in the same launch before that earlier child has finished writing all metadata.

The implementation should not broadly permit arbitrary user hyphenated names. `-@` is a controlled allocation syntax
whose generated names are allowed by the launch path; direct `%name:foo-1` should remain invalid unless the caller is an
internal bypass path that is already permitted today.

## Design Principles

- Centralize indexed-name semantics in `sase.agent.names`, not in each parser/caller.
- Use the existing durable name registry as the source of unavailable names for allocation.
- Use exact concrete names for persisted metadata (`agent_meta.wait_for`, `waiting.json`, chat resume lookups); do not
  persist `foobar-@`.
- Resolve `foobar-@` references before allocating a same-segment `%name:foobar-@`, so a prompt can wait/resume the
  current latest generation without accidentally pointing at itself.
- Preserve existing plan-chain hyphen semantics by only special-casing the template form and generated names from that
  form.
- Keep multi-prompt parent-side planning authoritative enough for later segments to refer to names created earlier in
  the same launch.

## Phase 1: Indexed Name Primitive, Parsing, and Validation

Add a small indexed-name helper module under `src/sase/agent/names/`, exported from `sase.agent.names`.

Responsibilities:

- Detect template names with a strict terminal `-@` marker.
- Extract and validate the base portion.
- Allocate `base-1`, `base-2`, ... from a mutable reservation set, defaulting to `get_reserved_agent_names()`.
- Resolve latest existing `base-<N>` by scanning reserved/known agent names and choosing the highest positive integer.
- Return `None` or raise a typed error for unresolved latest lookups, depending on caller needs.

Parser/validation changes:

- Extend directive argument parsing so `%name:foobar-@` and `%wait:foobar-@` are parsed as arguments, not as bare
  directives with leftover text.
- Add `PromptDirectives` state that distinguishes an exact explicit name from an indexed name template. This prevents
  generated hyphenated names from being rejected as ordinary user hyphen names while still keeping direct `%name:foo-1`
  invalid.
- Update `validate_launch_name_requests()` so `%name:foobar-@` validates the template/base and does not perform
  exact-name collision checks on the literal template.
- Reject ambiguous combinations such as forced reuse with an indexed template (`%name:!foobar-@`) unless a later phase
  explicitly designs semantics for it.

Tests:

- `tests/test_directives_types.py` for parsing `%n:foobar-@`, `%name(foobar-@)`, `%w:foobar-@`, comma-separated waits,
  fenced blocks, and no-existing-latest errors.
- `tests/test_agent_launch_validation.py` to prove `%name:foobar-@` is allowed, direct `%name:foo-1` remains rejected,
  and duplicate templates in one launch are not treated as duplicate exact names.
- New `tests/test_agent_names_indexed.py` for allocation gaps, latest resolution, registry-backed reservations, and
  invalid template forms.

## Phase 2: Single-Agent Runtime Resolution

Wire the indexed helper into the actual child runner and resume paths.

Runtime naming:

- In `extract_directives_and_write_meta()`, resolve a `%name:<base>-@` directive under `agent_name_allocation_lock()`.
- If `SASE_AGENT_PLANNED_NAME` was injected and it matches the template, use that concrete planned name.
- Otherwise allocate the next concrete name inside the lock and claim it before writing metadata.
- Claim generated names without calling ordinary hyphen validation, but do not allow a collision to overwrite an
  existing concrete owner.

Wait and resume resolution:

- Resolve `%wait:<base>-@` during directive extraction to a concrete latest name before `agent_meta.json` and
  `waiting.json` are written.
- Normalize `#fork:<base>-@` and legacy `#resume:<base>-@` in the shared resume-name lookup path so both chat loading
  and resume-derived child naming use the concrete latest name.
- Update `sase.scripts.agent_chat_from_name` and `sase.history.chat` only where central normalization is not already
  enough.

Tests:

- `tests/test_agent_names_extract.py` for `%name:foobar-@` child metadata and planned-name behavior.
- `tests/test_axe_run_agent_phases_wait_chats.py` or a focused sibling test for wait chat lookup after `%wait:foobar-@`.
- `tests/test_agent_chat_from_name.py` and `tests/history/test_chat_resume_refs.py` for `#fork:foobar-@` /
  `#resume:foobar-@`.

## Phase 3: Multi-Prompt Parent-Side Planning and Rewrites

Teach `PlannedNameAllocator` to handle indexed names across a multi-prompt launch.

Planning behavior:

- Maintain per-launch reservation sets for indexed bases so two segments with `%name:foobar-@` plan `foobar-1`, then
  `foobar-2`.
- Maintain per-launch latest-index maps so later segments can resolve `%w:foobar-@` and `#fork/#resume:foobar-@` to
  names planned earlier in the same launch, even before those children finish startup.
- Resolve indexed wait/resume references at the start of each segment before planning that segment's own name.
- Keep existing bare `%wait` and bare `#fork` previous-segment behavior intact.
- Ensure xprompt-expanded multi-agent prompts use the same path, since expansion already happens before
  `launch_multi_prompt_agents()`.

Tests:

- New or extended `tests/test_multi_prompt_launcher_launch.py` coverage:
  - segment 1 `%n:foobar-@`, segment 2 `%w:foobar-@` rewrites to `%w:foobar-1`;
  - segment 2 `#fork:foobar-@` and legacy `#resume:foobar-@` rewrite to the same latest planned name;
  - two `%n:foobar-@` segments allocate distinct concrete names;
  - a same-segment `%w:foobar-@` plus `%n:foobar-@` waits on the previously existing/latest name, not the newly
    allocated name.
- Add one end-to-end-ish launch test through `launch_agents_from_cwd()` to cover the path after `---` parsing and
  multi-agent xprompt expansion.

## Phase 4: Fanout, Edge Cases, and Hardening

Audit adjacent launch fanout paths so indexed names do not create inconsistent child names.

Scope:

- `%alt` / multi-model fanout: if a slot uses `%name:foobar-@`, allocate one concrete base and suffix the fanout
  children consistently, or explicitly reject this combination with a clear error if it would collide with existing
  fanout naming rules.
- Repeat launcher: decide whether `%repeat:N %name:foobar-@` should allocate one indexed batch base (`foobar-1.1`,
  `foobar-1.2`) or reject. Implement the chosen behavior with tests.
- Wait-check chop script: no marker format change should be needed because persisted waits are concrete names, but add a
  regression test proving `waiting.json` never contains `-@` and resolves normally.
- Mobile/dry-run launch: return the concrete planned name for `%name:foobar-@` when it is safely knowable, not the
  literal template.

Tests:

- Focused fanout/repeat tests in existing split-model and repeat launcher suites.
- A negative test for no existing `foobar-<N>` when resolving `%w:foobar-@` / `#fork:foobar-@`.
- Regression tests ensuring direct hyphenated names remain rejected outside internal bypasses.

## Phase 5: Integration Verification and Cleanup

Run targeted tests as each phase lands, then the repository check suite.

Suggested targeted sequence:

- `pytest tests/test_agent_names_indexed.py tests/test_directives_types.py tests/test_agent_launch_validation.py`
- `pytest tests/test_agent_names_extract.py tests/test_agent_chat_from_name.py tests/history/test_chat_resume_refs.py`
- `pytest tests/test_multi_prompt_launcher_launch.py tests/test_multi_prompt_launcher_fork.py tests/test_multi_prompt_launcher_wait_vcs.py`
- `pytest tests/test_repeat_launcher.py tests/test_directives_split_models.py tests/test_axe_chop_wait_checks.py`

Final verification:

- `just install`
- `just check`

Expected final user-visible examples:

```text
%n:build-@
Build the feature
---
%w:build-@
#fork:build-@
Review the result
```

If no prior `build-*` agents exist, the first segment is planned as `build-1`; the second segment waits on and resumes
`build-1`. A later `%n:build-@` plans `build-2`, and future `%w:build-@` / `#fork:build-@` resolve to `build-2`.
