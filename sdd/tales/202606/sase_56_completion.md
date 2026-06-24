---
create_time: 2026-06-23 20:07:00
status: done
prompt: sdd/prompts/202606/sase_56_completion.md
---
# Remaining Verification Fixes for `sase-56`

## Objective

Finish the last gaps found while verifying `sase-56` before closing the epic bead.

## Plan

1. Align the linked `sase-core` agent-launch directive alias helper with the migrated directive registry so
   `%a`/`%approve` canonicalize to `plan` and `%t` canonicalizes to `tale` everywhere Rust code uses directive names.
2. Update stale ACE user-facing documentation that still describes the old `a` key auto-approve cycle instead of the new
   Auto-Approve menu.
3. Run focused tests for the changed Rust and Python surfaces, then run the repository verification commands needed for
   closure.
4. Update the epic plan file frontmatter from `status: wip` to `status: done`.
5. Close bead `sase-56`.
