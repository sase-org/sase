---
create_time: 2026-05-31 12:09:53
status: done
prompt: sdd/prompts/202605/remove_long_memory_subheading.md
---
# Plan: Remove Generated Long-Memory Subheading

## Goal

Update the `sase amd init` generated `AGENTS.md` content so the Tier 2 long-term memory section no longer includes the
extra `#### Long-Term Memory Files` subheading or the blank line immediately before that subheading. After the code
change, run `sase amd init` from this workspace so the generated `AGENTS.md` is refreshed.

## Current Understanding

- `src/sase/amd/_memory.py::render_managed_agents()` renders the managed `AGENTS.md` template used by direct
  `sase amd init` and by memory initialization sync.
- `src/sase/amd/_agents_doc.py` parses both current and legacy managed `AGENTS.md` shapes. Its
  `#### Long-Term Memory Files` recognition should remain so older files can still be read and curated descriptions can
  still be preserved.
- Tests in `tests/main/test_amd_init.py` and `tests/main/test_init_memory_handler.py` directly assert the unwanted
  heading is present. Those assertions need to become absence checks.
- `tests/main/test_amd_list.py` contains a hand-built inventory fixture with the heading. It can remain as legacy-shape
  parser coverage unless it conflicts with the changed behavior.

## Implementation Steps

1. Edit `render_managed_agents()` to stop emitting the blank line before `#### Long-Term Memory Files` and the heading
   itself, while preserving a single blank line between the long-memory instructions paragraph and the first
   `memory/long/*.md` entry.
2. Update focused tests that assert generated output to expect the heading to be absent and continue checking the Tier 2
   heading plus long-memory entries.
3. Run targeted tests covering AMD generation, AMD inventory parsing, and memory-init sync.
4. Run `sase amd init` from this workspace to refresh the generated `AGENTS.md` and provider shims.
5. Because this repo requires it after file changes, run `just install` if needed and then `just check`.

## Validation

- Confirm generated `AGENTS.md` no longer contains `#### Long-Term Memory Files`.
- Confirm existing parser behavior remains compatible with older documents containing that heading.
- Confirm command execution succeeds and reports whether generated agent markdown documents were updated or already
  current.
