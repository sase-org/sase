---
create_time: 2026-05-23 11:38:22
status: done
---
# Plan: Home SASE Memory Header

## Goal

Start generating home-level `memory/short/sase.md` files with the same H1 used by project memory:

```markdown
# SASE = Structured Agentic Software Engineering
```

instead of:

```markdown
# SASE Memory
```

This should be a generator and test change. Do not hand-edit memory files as the implementation step unless the user
explicitly approves modifying those memory files. The checked-in project `memory/short/sase.md` already has the desired
header.

## Current Behavior

`src/sase/main/init_memory/roots.py` renders both project and home `memory/short/sase.md` through
`_render_sase_memory(entries, project_name=...)`.

- When `project_name` is provided, it emits `# SASE = Structured Agentic Software Engineering` and the project-only
  ephemeral workspace section.
- When `project_name` is `None`, it emits `# SASE Memory` and omits the ephemeral workspace section.

`src/sase/main/init_memory_handler.py` intentionally calls `_plan_memory_root` and `_initialize_memory_root` with a
`project_name` only for the project root. The home root is passed without a project name so it does not receive
project-specific workspace guidance.

`tests/main/test_init_memory_handler.py` currently codifies the old home behavior with
`assert home_memory.startswith("# SASE Memory")`.

## Design

1. Update only the home header branch in `_render_sase_memory`.
   - Replace the `project_name is None` branch's `# SASE Memory` H1 with
     `# SASE = Structured Agentic Software Engineering`.
   - Keep the workspace section guarded by `project_name is not None`, so home memory continues to omit project-specific
     ephemeral workspace guidance.

2. Keep the memory README header unchanged for now.
   - `_render_memory_readme()` emits `# SASE Memory` for `memory/README.md`, not `memory/short/sase.md`.
   - The user asked specifically about home `memory/short/sase.md` files, so changing the README would be unnecessary
     scope creep.

3. Do not modify checked-in or home memory files during this first implementation unless approved.
   - The repository `memory/short/sase.md` already has the new H1.
   - Actual home memory files should be updated by running the normal `sase memory init` flow after the generator change
     is reviewed, not by ad hoc edits.

## Tests

Update `tests/main/test_init_memory_handler.py` so home memory expectations match the new H1:

- Change the existing `home_memory.startswith("# SASE Memory")` assertion to
  `home_memory.startswith("# SASE = Structured Agentic Software Engineering")`.
- Add or preserve assertions that home memory does not include the project-only ephemeral workspace section.
- Optionally assert both project and home memory start with the same new H1 in the broader project/global split test, so
  the intended shared heading is covered near the home-specific sibling behavior too.

## Verification

Run focused tests first:

```bash
python -m pytest tests/main/test_init_memory_handler.py
```

Because the implementation will change repository files, finish with the repository-required check:

```bash
just check
```

If the implementation changes only this plan file and no code, do not run the full check just for planning.

## Risks and Follow-ups

- The home root may be either the real home directory or the chezmoi source home. This plan is safe for both because the
  header is generated through the shared home root rendering path.
- Existing home memory files will remain unchanged until `sase memory init` is run in the relevant environment.
- Any historical SDD files that mention the old header should be left alone unless a separate docs cleanup is requested.
