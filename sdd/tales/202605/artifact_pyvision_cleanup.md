---
create_time: 2026-05-05 10:07:28
status: wip
prompt: sdd/prompts/202605/artifact_pyvision_cleanup.md
---
# Artifact Pyvision Cleanup Plan

## Context

After closing `sase-23.1`, `just pyvision` reports stale `# pyvision: public_api_methods.txt` pragmas added by the
artifact wire/facade work. The symbols are now imported by tests or other Python code, so the pragmas are no longer
needed and are treated as errors once the epic bead is closed.

## Plan

1. Remove only the unnecessary pyvision pragmas reported by `just pyvision` from:
   - `src/sase/core/artifact_facade.py`
   - `src/sase/core/artifact_wire.py`
2. Re-run `just pyvision` to verify no stale artifact pragmas remain.
3. Run the required repo verification after the local edit.
