---
create_time: 2026-05-31 11:21:55
status: wip
prompt: sdd/prompts/202605/revert_agents_md_titles.md
---
# Revert AMD-Generated AGENTS.md Memory Titles

## Goal

Restore the AMD-managed `AGENTS.md` memory section titles to the pre-`7013ddf01` tier-oriented wording while preserving
the dynamic-memory removal from `e8c2f14bb`.

## Context

Recent related commits show two separate changes:

- `7013ddf01 chore: update AGENTS memory section headings` changed generated headings from tier names to source-oriented
  names:
  - `## Tier 1 (short-term) Memory` became `## Short-Term Memory Files`.
  - `## Tier 2 (dynamic) Memory` became `## Dynamic Memory Files`.
  - `## Tier 3 (long-term) Memory` became `## Long-Term Memory Files`.
  - The nested `#### Long-Term Memory Files` heading was removed.
- `e8c2f14bb feat: remove dynamic memory runtime` later removed the dynamic-memory section entirely, leaving only the
  new short/long headings.

The requested revert should therefore restore the pre-heading-change title style for the remaining sections only:

- `## Tier 1 (short-term) Memory`
- `## Tier 3 (long-term) Memory`
- `#### Long-Term Memory Files` above the long-memory list

It should not restore `## Tier 2 (dynamic) Memory`, the `### DYNAMIC MEMORY` prompt text, or any dynamic-memory runtime
behavior.

## Implementation Plan

1. Update `src/sase/amd/_memory.py` so `render_managed_agents()` emits the restored Tier 1 and Tier 3 headings, plus the
   restored long-memory list subheading, without reintroducing dynamic-memory rendering.
2. Update focused AMD and memory-init tests in `tests/main/test_amd_init.py` and
   `tests/main/test_init_memory_handler.py` so they assert the restored titles and continue to assert that dynamic
   memory is absent.
3. Run focused tests for the touched rendering paths:
   - `pytest tests/main/test_amd_init.py tests/main/test_init_memory_handler.py`
4. Run `sase amd init` from this workspace using the workspace CLI (`.venv/bin/sase`) to refresh the checked-in
   `AGENTS.md` and verify the command output matches the updated generator.
5. Inspect the resulting diff to ensure only AMD title-related files changed and no canonical memory files under
   `memory/short/` or `memory/long/` were modified.
6. Run the repo validation required for code changes. If the focused test run is clean, run `just check`; if the command
   reports stale generated output first, refresh only the relevant generated AMD artifacts and rerun.

## Validation

- Focused pytest passes.
- `.venv/bin/sase amd init` exits successfully and leaves `AGENTS.md` with the restored headings.
- `just check` passes.
- Final text sweep confirms dynamic-memory headings and prompt sections were not reintroduced into active generator
  output.
