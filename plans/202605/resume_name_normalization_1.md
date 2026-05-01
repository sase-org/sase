---
create_time: 2026-05-01 15:09:47
status: wip
---
# Resume-derived agent name normalization

## Goal

Shorten automatically generated names for agents launched from prompts containing `#resume`.

Current behavior appends `.r<N>` directly to the literal resumed agent name. When the resumed target is a plan/coder
follow-up, repeated resumes can create names such as:

- `ma.code.r1.code.r1.code.r1`

The desired behavior is:

- strip workflow role segments `.code` and `.plan` before deriving the resume name
- when a resume-derived name already has an `.r<N>` segment, increment that retry/resume number instead of appending
  another `.r<N>`
- keep explicit `%name` / `%n` names authoritative
- preserve the existing collision avoidance behavior across active and done visible agents

## Relevant Code

The central allocator is `src/sase/agent/names/_resume.py`:

- `first_resume_agent_name(prompt)` extracts the first top-level `#resume` target.
- `allocate_resume_name(resume_name)` currently returns the first free `<resume_name>.r<N>`.
- `allocate_resume_names(resume_name, count)` shares one active-name snapshot across repeat batches.
- `_active_resume_reserved_names(resume_name)` scans active names and reserves existing `.r<N>` slots.

Call sites already delegate to these helpers:

- `src/sase/axe/run_agent_phases.py` for ordinary single-agent launches containing `#resume`
- `src/sase/agent/repeat_launcher.py` for `%r:N #resume:...`
- `src/sase/xprompt/_directive_alt.py` for multi-model fanout naming

Because the call sites share the allocator, the fix should live in `_resume.py` rather than duplicating normalization at
each launch path.

## Design

Add a small normalization layer for resume-derived names:

1. Parse the resumed target into dot-delimited segments.
2. Remove role segments equal to `code` or `plan`.
3. Treat `.r<N>` segments as resume-generation markers.
4. If the stripped name contains one or more `.r<N>` markers, collapse the name back to the base before the first resume
   marker and allocate from the next available generation after the highest existing marker. Examples:
   - `ma.code` -> base `ma`, allocate `ma.r1`
   - `ma.code.r1.code` -> base `ma`, allocate `ma.r2`
   - `ma.code.r1.code.r1.code` -> base `ma`, allocate `ma.r2` or the next free `ma.r<N>` if `ma.r2` is taken
   - `foo.plan.r3` -> base `foo`, allocate at least `foo.r4`
5. If no `.r<N>` marker is present after stripping roles, keep the current behavior: allocate the lowest available
   `<base>.r<N>`.
6. Preserve names that merely contain substrings like `decode`, `codegen`, or `planning`; only exact dot segments `code`
   and `plan` are removed.

Collision handling should continue to use the active-name snapshot. The reserved-name scanner should look for existing
resume generations under the normalized base, including descendants such as `foo.r2.claude`, so batch allocation and
multi-model naming remain stable.

## Implementation Steps

1. Add private helpers in `src/sase/agent/names/_resume.py`, likely:
   - `_normalize_resume_name_for_allocation(resume_name: str) -> tuple[str, int]`
   - `_resume_generation_floor(resume_name: str) -> int`
2. Update `allocate_resume_name()` and `allocate_resume_names()` to allocate against the normalized base and a minimum
   starting generation.
3. Update `_active_resume_reserved_names()` to scan active names using the normalized base.
4. Add focused tests in `tests/test_agent_names.py` for:
   - stripping `.code` and `.plan`
   - incrementing an existing `.r<N>` instead of nesting `.r<N>`
   - preserving non-role substrings
   - honoring collisions/gaps after normalization
5. Add repeat-batch coverage in `tests/test_repeat_launcher.py` for `%r:N #resume:<name-with-code-and-r>` so injected
   `%wait` directives chain through the normalized names.

## Verification

Run the targeted tests first:

```bash
pytest tests/test_agent_names.py::TestResumeAgentNames tests/test_repeat_launcher.py::TestSpawnRepeatBatch
```

Because this repo requires the full check after edits, run:

```bash
just install
just check
```

If `just check` is not available in the workspace, fall back to `just lint` and `just test`, and report that fallback.
