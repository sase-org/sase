---
create_time: 2026-06-20 17:27:50
status: done
prompt: sdd/prompts/202606/sase_51_closeout.md
---
# SASE-51 Closeout Verification Plan

## Goal

Finish verification for epic `sase-51` and close it only after the remaining gaps found during review are handled.

## Remaining Work

1. Fix the config-fallback test isolation issue exposed by the maintained user config migration. The finalizer config
   fallback tests should not depend on whatever `~/.config/sase/sase.yml` happens to contain, and they must still cover
   legacy `sibling_repos` compatibility.
2. Investigate the `sase_core_rs` binding mismatch reported after `just install`. Use the configured linked `sase-core`
   checkout for workspace `10`; rebuild or document the external mismatch if it is outside this epic's scope.
3. Re-run the focused migration tests that cover linked-repo resolution, launch/deferred env refresh, finalizer
   behavior, config diagnostics, schema compatibility, and docs/config surface.
4. Run the required repo checks after any SASE file changes.
5. Update stale child-bead commit notes if verification confirms the current reachable phase commits differ from the
   displayed note hashes.
6. Update `sdd/epics/202606/linked_repos_rename_codex.md` frontmatter to `status: done`.
7. Close epic bead `sase-51`.
8. After closing the epic, run `just pyvision` if the recipe is available and confirm no unused-code fallout from the
   migration remains.
