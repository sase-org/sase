---
bead_id: sase-4d
create_time: 2026-06-06 10:20:31
status: done
prompt: sdd/prompts/202606/sase_4d_pyvision_cleanup_2.md
---

# sase-4d Pyvision Cleanup Plan

## Context

After closing `sase-4d`, `just pyvision` reports `allocate_project_alias` and `ensure_project_alias_locked` as unused
public symbols in `src/sase/project_aliases.py`. Both are intentionally public because the `sase-github` workspace
provider imports them to allocate generated project aliases on first-use GitHub repo refs.

## Plan

1. Mark the two public alias helpers with `# pyvision: https://github.com/sase-org/sase-github.git` so pyvision
   validates the real external consumer instead of relying on an open-epic exemption.
2. Remove the temporary `sase-4d(...)` `--epic-symbol` exemptions from the `Justfile` pyvision lint recipe.
3. Re-run the targeted alias/GitHub tests and final repository checks required by the touched files.
4. Update the `sdd/epics/202606/github_project_aliases.md` frontmatter status to `done` once checks are green.
5. Close `sase-4d` as the final plan step.

## Required Post-Close Validation

Run `just pyvision` after the epic is closed to confirm the durable pragmas cover the external consumer.
