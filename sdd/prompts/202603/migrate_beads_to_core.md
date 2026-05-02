---
plan: sdd/epics/202603/migrate_beads_to_core.md
---
#gh:sase Can you help me migrate the new ../sase-beads repo's functionality into sase's core and make some improvements
to it?

- The new command that will replace `sbd` is `sase bead`.
- When `sdd.version_controlled` is set, we should store these beads in a top-level sdd/beads/ directory. Otherwise, we
  use the .sase/sdd/beads/ directory.
- We should remove the `sase init-beads` command and start auto-initializing the .sase/sdd/beads/ directory when
  `sdd.version_controlled` is not set.
- We should update `ccommit` in the chezmoi repo so it automatically commits any changes to files in the sdd/beads/
  directory.
- We shouldn't need the `tools/sase_sbd` script anymore, so we can remove that.
- Make sure you update all references in the chezmoi repo appropriately.
- Don't bother deleting the ../sase-beads repo. I'll handle that.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
