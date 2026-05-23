---
create_time: 2026-05-22 20:18:56
status: done
prompt: sdd/prompts/202605/init_memory_workspace_section.md
---
# Plan: Project Workspace Section in `sase init memory`

## Goal

Update `sase init memory` so the generated project-level `memory/short/sase.md` includes the ephemeral workspace
directory guidance from `~/tmp/sase.md`, with `{{ project }}` rendered to the project name. The home-level
`~/memory/short/sase.md` target must not include this project-specific workspace section.

This should change the generator and tests, not hand-edit the existing checked-in `memory/short/sase.md` memory file.
That file is governed by the repository instruction that memory files should not be modified without explicit approval.

## Current Behavior

`src/sase/main/init_memory_handler.py` has a single `_render_sase_memory(entries)` renderer used by both project and
home memory roots. It currently emits:

- `# SASE Memory`
- the sibling repository section

Because project and home generation share the renderer, adding the workspace section directly would incorrectly include
it in the home memory target too.

`~/tmp/sase.md` shows the desired project memory content shape:

- `# SASE = Structured Agentic Software Engineering`
- `## Ephemeral <project>_<N> Workspace Directories`
- text warning agents to stay inside the ephemeral workspace clone and its isolated environment
- the existing sibling repository section

## Design

1. Split project-specific memory rendering from home memory rendering with an explicit option rather than relying on
   path inspection inside the renderer.
   - Keep home memory behavior unchanged except for any shared sibling-section helper needed to avoid duplication.
   - Pass a project name only for `Path.cwd()` project memory generation.

2. Render the workspace section only when a project name is provided.
   - Use the exact placeholder replacement semantics implied by `~/tmp/sase.md`: `{{ project }}` becomes the resolved
     project name in prose and in the `` `<project>_<N>` `` directory pattern.
   - Ensure the generated output contains no literal `{{ project }}`.

3. Resolve the project name robustly for managed workspaces.
   - Prefer the managed-checkout marker (`.sase/checkout.json`) when present, since it already records that `sase_10`
     belongs to project `sase`.
   - Fall back to Git metadata when available, then to the root directory name.
   - Strip a trailing `_<digits>` suffix only as a fallback so an ephemeral checkout like `sase_10` still renders
     `sase_<N>`.

4. Preserve validation behavior.
   - The new section must not introduce additional `memory/...` references or alter reachability validation.
   - Provider shims, README generation, sibling repo validation, and chezmoi deployment should keep their current flow.

## Tests

Add focused coverage in `tests/main/test_init_memory_handler.py`:

- Project memory includes the new heading and workspace section.
- Project memory substitutes the project name and contains no `{{ project }}` placeholder.
- Home memory does not include the ephemeral workspace section.
- A managed checkout marker with `project_name: project` in a `project_10` directory renders `project_<N>`, not
  `project_10_<N>`.
- Existing sibling-repo behavior remains split between project config and global config.

## Verification

Run the targeted init-memory tests first:

```bash
python -m pytest tests/main/test_init_memory_handler.py
```

Then run the repository-required final check because implementation files changed:

```bash
just check
```
