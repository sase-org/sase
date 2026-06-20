---
plan: sdd/tales/202606/agy_provider_final_gap.md
---
#gh:sase
%name:sase-50
%group:sase-50
%approve
%w:sase-50.1,sase-50.2,sase-50.3,sase-50.4,sase-50.5,sase-50.6,sase-50.7
Can you help me verify that all the work associated with the bead with ID sase-50 is complete?

Actually read through the source code and the git commits that are associated with that bead's work (they should have
the bead ID in the commit message) and ensure all of the work that the previous agents say is complete, is actually
complete. Also, run `sase bead show` on every child bead and ensure that any notes on those beads have been
addressed.

If not, plan out the remaining work using your /sase_plan skill (make sure to include closing the bead as the
final step of the plan) and complete it. Otherwise, close the bead using the `sase bead close` command. If
available, run the `just pyvision` command AFTER closing the epic bead (some symbols can be ignored while an epic
is open) to make sure we didn't leave any unused code behind.

Finally, find the plan file associated with this work (which should be in the sdd/epics/ directory, in a YYYYMM
subdirectory). If found, a `status` field should be added (or updated if it already exists) to the frontmatter of
the plan file with a value of `done`.