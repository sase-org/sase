---
create_time: 2026-05-29 20:26:28
status: done
prompt: sdd/prompts/202605/dynamic_memory_tier2.md
---
# Plan: Conditional Tier 2 Dynamic Memory Section

## Goal

Change AMD-managed `AGENTS.md` generation so the Tier 2 dynamic memory documentation section is emitted only when at
least one `memory/long/*.md` file has a `keywords` field in YAML frontmatter.

## Context

- `sase amd init` plans managed `AGENTS.md` writes through `src/sase/amd/_planner.py`.
- The actual managed content is rendered by `render_managed_agents()` in `src/sase/amd/_memory.py`.
- `sase memory init` also reuses this renderer through `plan_amd_memory_sync()`, so the same conditional behavior should
  naturally apply there.
- `_split_frontmatter()` already parses YAML frontmatter in `_memory.py`, which is the right local primitive for this
  change.
- Dynamic memory discovery elsewhere is based on `memory/long/*.md` frontmatter containing a `keywords` field; this
  change should keep AMD documentation aligned with that behavior.

## Implementation

1. Add a small helper in `src/sase/amd/_memory.py` that scans long-term memory markdown files and returns true when any
   parsed frontmatter mapping contains the `keywords` key.
2. In `render_managed_agents()`, compute that flag from the same `long_paths` tuple already used for the Tier 3 section.
3. Split the current Tier 2 lines into a conditional block. Keep Tier 1 and Tier 3 rendering unchanged.
4. Treat unreadable files or malformed frontmatter as having no keywords, matching the renderer's existing defensive
   behavior.

## Tests

1. Update or add `tests/main/test_amd_init.py` coverage showing managed `AGENTS.md` omits `## Tier 2 (dynamic) Memory`
   when long-term memory exists but none has `keywords` frontmatter.
2. Add coverage showing `sase amd init` includes the Tier 2 section when at least one long-term memory file has a
   `keywords` field.
3. Add or adjust `tests/main/test_init_memory_handler.py` assertions so the shared `sase memory init` renderer path
   stays covered for the keyword-present case.

## Verification

1. Run the focused AMD/init-memory tests.
2. Run `just install`, then `just check` because repo files changed.
3. Run `sase amd init` in the home context needed to update `~/AGENTS.md`.
4. Verify `~/AGENTS.md` no longer contains `## Tier 2 (dynamic) Memory` or the sample `### DYNAMIC MEMORY` block when no
   home long-term memory has `keywords` frontmatter.
