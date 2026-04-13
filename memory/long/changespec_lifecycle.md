---
keywords: [changespec, status transition, suffix strip, archive, sibling, draft flag, mentor draft, parent-child]
---

# ChangeSpec Lifecycle

## Sections

Every ChangeSpec contains these sections: NAME, DESCRIPTION, PARENT, CL/PR, BUG, STATUS, KICKSTART, TEST_TARGETS,
COMMITS, HOOKS, COMMENTS, MENTORS, TIMESTAMPS. The `CL:` and `PR:` headers in the raw `.gp` file both map to the same
`cl` field internally.

## Status Lifecycle

Valid statuses: WIP, Draft, Ready, Mailed, Submitted, Reverted, Archived.

Transition graph:

- **WIP** → Draft or Ready (can skip Draft entirely)
- **Draft** → Ready
- **Ready** → Mailed or Draft (bidirectional with Draft)
- **Mailed** → Submitted
- **Submitted, Reverted, Archived** — terminal (no outbound transitions)

## Suffix Semantics

When a ChangeSpec transitions **Ready → Draft**, a `_<N>` suffix is appended to its name (e.g., `my_change` →
`my_change_1`). When transitioning **Draft/WIP → Ready**, the suffix is stripped back to the base name.

**Sibling auto-revert:** Stripping the suffix triggers `revert_sibling_draft_changespecs()`, which auto-reverts all
other WIP/Draft ChangeSpecs sharing the same base name. This ensures only one version of a change is active at Ready.

**Outside the lock:** Suffix operations (append and strip) run _outside_ the ChangeSpec file lock because they invoke
VCS operations like `provider.rename_branch()`, which can be slow. There is a brief inconsistency window between the
status write (inside lock) and the rename (outside lock) — this is by design.

## Parent-Child Invariant

- Children must be **WIP, Draft, or Reverted** before a parent can transition to Ready
- If the parent is WIP/Draft, children cannot transition to anything beyond WIP/Draft/Reverted

Both directions are enforced in the transition handlers.

## PARENT Reference Auto-Update

When a ChangeSpec is renamed (suffix append/strip), `update_parent_references_atomic()` scans all ChangeSpecs in the
project file and rewrites any `PARENT:` field that references the old name to point to the new name. This runs inside
the lock.

## Archive Movement

Terminal statuses (Submitted, Reverted, Archived) are moved from the active project file (`<project>.gp`) to the archive
file (`<project>-archive.gp`). The move uses an **add-then-remove** strategy: the ChangeSpec block is appended to the
archive first, then removed from the active file. This prevents data loss if the process is interrupted.

## Mentor Draft Flags

Each MentorEntry has an `is_draft: bool` field, serialized as a `#Draft` suffix on the profiles line in the `.gp` file.

- **Ready → Draft:** `set_mentor_draft_flags()` sets `is_draft=True` on the last mentor entry
- **Draft → Ready:** `clear_mentor_draft_flags()` sets `is_draft=False` and rebuilds the full profiles list by
  re-matching all commits against mentor profiles
