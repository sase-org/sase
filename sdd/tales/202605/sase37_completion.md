---
create_time: 2026-05-12 18:55:53
status: done
prompt: sdd/prompts/202605/sase37_completion.md
---
# Complete sase-37 Archive Verification

## Context

The `sase-37` epic is open while all child beads are closed. Source review found the archive revive helper
(`mark_bundles_revived_by_suffixes`) exists, but the TUI revive implementation still calls `remove_bundle_by_identity`,
deleting bundle payloads after revive. This violates Phase 0 acceptance for preserving archive bundles and marking
`revived_at` / `times_revived` instead.

## Plan

1. Replace destructive TUI revive cleanup in single and batch revive flows with revival marking by suffix set,
   preserving the existing dismissed identity cleanup and artifact restoration behavior.
2. Update focused revive tests so they assert `mark_bundles_revived_by_suffixes` receives parent and child/follow-up
   suffixes, and destructive bundle removal is no longer part of normal TUI revive.
3. Run focused archive/revive tests, then run the project check command after `just install` if source files changed.
4. Re-check `sase bead show` for `sase-37` and all child beads, then update the linked epic plan frontmatter to
   `status: done`.
5. Close the `sase-37` bead.
