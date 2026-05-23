---
create_time: 2026-05-23 17:38:37
status: done
prompt: sdd/prompts/202605/wait_derived_agent_names.md
---
# Wait-Derived Agent Names Plan

## Goal

Agents whose name is auto-generated and whose prompt waits on exactly one other agent should derive their name from that
dependency, mirroring the existing fork-derived `.f<N>` behavior. The new names should use `.w<N>`, for example
`%wait:foo do work` should produce `foo.w1` unless the prompt supplies an explicit `%name`.

## Current Behavior

- Fork-derived names are centralized in `src/sase/agent/names/_resume.py`:
  - `first_resume_agent_name()` finds the first top-level `#fork` or legacy `#resume`.
  - `allocate_resume_name()` allocates `<base>.f<N>` and reserves legacy `.r<N>` slots.
- The runner applies fork-derived names in `src/sase/axe/run_agent_directives.py` after directive extraction and before
  falling back to `get_next_auto_name()`.
- Parent-side launch result planning in `src/sase/agent/multi_prompt_references.py` currently plans explicit names or
  plain auto names, so `%wait:foo` launched through `launch_agents_from_cwd()` would otherwise still be preplanned as
  `a`.
- Repeat and model/alt fan-out already special-case fork-derived names:
  - `src/sase/agent/repeat_launcher.py` uses `foo.f<N>` for `%r:N #fork:foo`.
  - `src/sase/xprompt/_directive_alt.py` uses a fork-derived base before adding fan-out suffixes.
- The Rust launch facade strips repeat/name directives but leaves the derived-name policy in Python, so this change
  should stay in the Python repo.

## Design

1. Add wait-derived allocation helpers to the public `sase.agent.names` API.
   - Reuse the existing allocation lock and active-name scan.
   - Allocate `<waited_name>.w<N>` for the first free `.w` slot.
   - Treat existing descendants such as `foo.w1.codex` as reserving `foo.w1`.
   - Do not let `.f<N>` and `.w<N>` reserve each other; they represent different derivation modes.

2. Add a single-wait target helper for prompts where the parent can safely inspect the wait directive.
   - Return a target only when exactly one `%wait`/`%w` agent dependency is present after normal directive parsing.
   - Return no target for multiple agent waits or duration/time-only waits.
   - Preserve fork precedence: prompts that also contain `#fork` should keep the existing `.f<N>` behavior.

3. Update runner metadata naming in `extract_directives_and_write_meta()`.
   - Keep explicit `%name:<value>` as the top priority.
   - Keep fork-derived `.f<N>` ahead of wait-derived `.w<N>`.
   - Use `.w<N>` when no explicit/fork/repeat/planned name applies and `directives.wait` has exactly one dependency.
   - Preserve auto-dismiss suppression.

4. Update parent-side name planning.
   - Teach `PlannedNameAllocator` to preplan `.w<N>` for prompts whose name is safely knowable in the parent.
   - Keep the current conservative rule that prompts containing unexpanded `#` references are not preplanned, except
     explicit `%name` already handled before that rule.
   - Track reserved wait-derived names per base during a multi-prompt/fan-out launch so sibling slots do not collide
     before child metadata exists.

5. Update repeat and model/alt fan-out naming.
   - For repeat prompts without explicit `%name`, keep `#fork` as `.f<N>` and add `%wait:foo` single-dependency support
     as `.w<N>`.
   - For model/alt fan-out without explicit `%name`, use a wait-derived base before falling back to plain auto names.

6. Add focused regression tests.
   - `tests/test_agent_names.py`: wait allocation first slot, gap filling, descendant reservation, and multiple
     allocation from one snapshot.
   - `tests/test_agent_names_extract.py`: `%wait:foo` gets `foo.w1`; explicit `%name` wins; `#fork` plus `%wait` keeps
     `.f<N>`; multiple waits fall back to normal auto naming.
   - `tests/test_launch_planned_agent_name.py` and `tests/test_multi_prompt_launcher_launch.py`: parent-side planned
     names for single/multiple wait-derived launches.
   - `tests/test_repeat_launcher.py`: repeat with a single `%wait` uses `foo.w<N>` and fills gaps.
   - `tests/test_directives_split_models.py`: model/alt fan-out with a single `%wait` uses a `.w<N>` base.

## Verification

- Run focused tests covering the touched paths.
- Run `just install` then `just check` before finishing, because this repo requires `just check` after file changes.
