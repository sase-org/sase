---
create_time: 2026-06-16 16:18:12
status: done
prompt: sdd/prompts/202606/prompt_frontmatter_panel_closure.md
---
# Plan: Close prompt frontmatter panel epic

## Context

The `sase-4r` child phase beads are closed and the phase commits are present in both this repo and the sibling
`sase-core` repo. Targeted source review and test runs show the implemented feature paths are present:

- Rust core/binding field schema and validation API.
- Python `PromptFrontmatter` model and stack round-trip.
- Prompt input frontmatter panel, raw mode, scalar/list editing, and typed `input`/`xprompts` sub-editors.
- Live local-xprompt completion, soft completion, and argument hints.
- Launch-time prompt `input:` collection/substitution, including the non-interactive error path.

The remaining gap is closure cleanup: `just pyvision` fails because six public adapter helper types/functions in
`src/sase/xprompt/frontmatter_schema.py` are still only protected by open-epic allowances in `_lint-pyvision`.

## Implementation Steps

1. Internalize or remove unused public adapter symbols while preserving the runtime API the panel actually uses.
2. Remove the stale `sase-4r(...)` pyvision allowances and their closing comment from `Justfile`.
3. Re-run targeted tests and `just pyvision`; run `just check` if source files changed.
4. Update `sdd/epics/202606/prompt_frontmatter_panel.md` frontmatter `status` to `done`.
5. Close the epic bead with `sase bead close sase-4r`.
