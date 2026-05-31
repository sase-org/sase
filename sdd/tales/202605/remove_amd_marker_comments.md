---
create_time: 2026-05-31 11:30:32
status: done
prompt: sdd/prompts/202605/remove_amd_marker_comments.md
---
# Remove AMD Marker Comments From AGENTS.md

## Goal

Stop emitting and depending on the `<!-- sase-amd:... -->` HTML comments in AMD-managed `AGENTS.md` files. AMD should
identify its generated short-memory and long-memory surfaces from the visible Markdown structure:

- the Tier 1 short-memory section and its `- @memory/short/*.md` bullets;
- the Tier 3 long-memory section, `#### Long-Term Memory Files`, and its description-list entries.

The resulting generated `AGENTS.md` should be cleaner for agents to read, while `sase amd init`, `sase memory init`, and
`sase amd list` remain deterministic and migration-safe.

## Current Understanding

The marker comments are not essential to the current writer path. `sase amd init` and AMD-enabled `sase memory init`
render the full managed `AGENTS.md` body from `render_managed_agents()` whenever `amd_h1_title` is active, rather than
doing surgical marker-block replacement. Long-memory description preservation already scans existing
`**\`memory/long/\*.md\`\*\*` entries without using the marker constants.

The main places that still care about markers are:

- `src/sase/amd/_memory.py`, which imports and emits all four marker constants.
- `src/sase/amd/inventory.py`, which classifies an `AGENTS.md` as `managed` only when all four comments are present.
- focused AMD and memory-init tests that assert the comments are present.
- the checked-in root `AGENTS.md`, which needs regeneration after the renderer changes.

So the right fix is not a fragile string replacement. It is to make AMD's visible section shape the contract.

## Deterministic Parsing Contract

Add a small AMD document parser, either in `src/sase/amd/_memory.py` if it stays compact or in a new private module such
as `src/sase/amd/_agents_doc.py` if sharing with inventory would otherwise create clutter.

The parser should operate line-by-line and ignore legacy `<!-- sase-amd:... -->` comment lines during transition. It
should recognize:

- Short-memory section start: `## Tier 1 (short-term) Memory`.
- Legacy short-memory heading for migration only: `## Short-Term Memory Files`.
- Long-memory section start: `## Tier 3 (long-term) Memory`.
- Legacy long-memory heading for migration only: `## Long-Term Memory Files`.
- Long-memory list anchor: `#### Long-Term Memory Files` when present.
- Section end: the next `## ` heading at the same level.

Within the short section, parse only top-level bullets matching exactly `- @memory/short/... .md` after whitespace
normalization. Do not treat arbitrary prose mentions as AMD short-memory entries.

Within the long list area, parse entries matching:

```text
**`memory/long/<path>.md`**
Description text, possibly wrapped across adjacent nonblank lines.
```

Normalize description whitespace the same way the current code does, and continue stripping the historical
`_Read when ..._` suffix so existing curated descriptions survive.

Keep a narrow legacy fallback for first-time migration from older custom `AGENTS.md` files that contain long-memory
description-list entries outside the AMD headings. That fallback should be used only for preserving descriptions, not
for declaring a document AMD-managed.

## Implementation Steps

1. Add the structural parser and use it from `_existing_agents_long_descriptions()`.
   - Prefer parsed Tier 3 entries when the AMD long section is present.
   - Fall back to the existing broad long-entry scan only when no AMD long section is recognizable, preserving current
     migration behavior for curated descriptions in arbitrary legacy files.

2. Update `render_managed_agents()` to stop emitting marker comment lines.
   - Preserve the visible Tier 1 / Tier 3 headings restored by the previous change.
   - Preserve the `#### Long-Term Memory Files` subheading.
   - Keep deterministic ordering for short refs and long-memory entries.
   - Keep trailing newline behavior stable.

3. Replace marker-based inventory management detection with structural detection.
   - `managed`: both AMD memory sections are recognizable by visible headings.
   - `incomplete managed structure` or similar yellow state: one AMD memory section is recognizable but the other is
     absent or malformed.
   - `custom`: no AMD memory structure is recognizable.
   - Treat legacy markered files that still have valid visible structure as `managed`; old comments should neither be
     required nor harmful.

4. Use parsed AMD entries for `sase amd list` memory counts when a document has AMD structure.
   - For custom documents, keep the existing broad memory-reference counting so the inventory remains useful for
     hand-written files.
   - This makes the managed count reflect AMD's actual visible contract instead of incidental prose mentions.

5. Remove marker constants from active runtime code once no longer used.
   - Delete them from `src/sase/amd/constants.py` and `__all__` if no compatibility import remains necessary.
   - Remove imports from tests.
   - Historical SDD/research documents can remain historical unless there is active user-facing documentation that still
     describes marker comments as the design.

6. Regenerate the checked-in root `AGENTS.md` with the workspace CLI after code and tests are updated.
   - Expected generated diff: the four HTML marker comments disappear.
   - Memory bullets and long-memory description entries remain unchanged.
   - Do not modify `memory/short/*` or `memory/long/*` files.

## Test Plan

Update focused tests rather than relying on broad snapshots:

- `tests/main/test_amd_init.py`
  - Generated managed `AGENTS.md` contains Tier 1 and Tier 3 sections.
  - It contains expected short-memory bullets and long-memory entries.
  - It does not contain `sase-amd:` comments.
  - Existing curated long-memory descriptions still survive first migration.

- `tests/main/test_init_memory_handler.py`
  - AMD-enabled memory init generates marker-free `AGENTS.md`.
  - Description frontmatter insertion/preservation continues to work.
  - Reachability validation still sees generated short and long memory references through the overlay.

- `tests/main/test_amd_list.py`
  - Marker-free managed fixture classifies as `managed`.
  - Legacy markered-but-structurally-valid fixture still classifies as `managed`.
  - Partial visible AMD structure reports the new yellow state.
  - Managed memory counts come from parsed bullets/list entries.
  - Custom `AGENTS.md` files still get broad short/long reference counts.

Run:

```bash
.venv/bin/python -m pytest tests/main/test_amd_init.py tests/main/test_init_memory_handler.py tests/main/test_amd_list.py tests/test_memory_inventory.py
.venv/bin/sase amd init
just check
```

Then do a scoped final sweep:

```bash
rg -n "sase-amd|SHORT_MEMORY_START_MARKER|LONG_MEMORY_START_MARKER|SHORT_MEMORY_END_MARKER|LONG_MEMORY_END_MARKER" \
  AGENTS.md src/sase/amd tests/main
```

The sweep should find no active runtime, focused-test, or generated root `AGENTS.md` dependency on the marker comments.

## Risks And Guardrails

- Do not call a hand-written document managed just because it mentions memory paths. Management detection must be based
  on AMD's visible heading structure, not the broad memory-reference regex.
- Do not remove the legacy description-preservation fallback too aggressively; existing tests intentionally preserve a
  curated `memory/long/*.md` description from a previous arbitrary `AGENTS.md`.
- Do not make marker removal depend on parsing comments. Old comments should be ignored during migration, then disappear
  on the next generated write.
- Keep this change in the Python AMD layer. It does not cross the Rust core backend boundary.
- Avoid touching canonical memory files unless a later implementation reveals a genuine description-frontmatter need;
  this plan expects no memory-file edits.

## Acceptance Criteria

- Newly generated AMD-managed `AGENTS.md` files have no `sase-amd` HTML comments.
- `sase amd init` and AMD-enabled `sase memory init` remain idempotent.
- `sase amd list` can classify marker-free generated documents as managed.
- Existing markered generated documents migrate cleanly to marker-free output.
- The checked-in root `AGENTS.md` loses only the marker comments in its AMD-managed memory sections.
- Focused tests and `just check` pass.
