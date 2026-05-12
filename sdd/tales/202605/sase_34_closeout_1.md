---
create_time: 2026-05-12 13:31:03
status: done
prompt: sdd/prompts/202605/sase_34_closeout_1.md
---
# sase-34 Closeout Verification Plan

## Context

The `sase-34` epic removes config-local xprompt workflow support and migrates scheduled Athena workflows to repo-backed
`xprompts/*.yml` files. All child beads are closed, but verification found small documentation drift in the closeout:
`docs/configuration.md` still lists the removed `workflows` config section in its table of contents, and the bundled
workflow table in `docs/xprompt.md` does not list the actual inputs for the two audit workflows.

## Plan

1. Fix the remaining documentation drift:
   - Remove the stale `workflows` table-of-contents entry from `docs/configuration.md`.
   - Update `docs/xprompt.md` so the audit workflow rows list `project`, `gh_ref`, and `threshold`.

2. Re-run targeted verification for the epic:
   - Confirm config workflow loader APIs and config schema support are removed.
   - Confirm the migrated Athena workflow references are qualified as `#!sase/...`.
   - Confirm `sase xprompt explain` can load the three migrated repo-backed workflows.
   - Run focused Python tests that cover config workflow removal and VCS-selected workflow discovery.

3. Update the epic plan frontmatter status to `done`.

4. Run repository checks required for the local edits.

5. Close the `sase-34` epic bead.
