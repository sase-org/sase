---
plan: sdd/plans/202605/revert_coder_suffix_1.md
---
 #resume:tl.plan.r1 Can we revert the ".coder" change made (i.e. commit c165bf15) and the more recent ".coder" fix? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### Additional Requirements

- This is the only machine that has this change right now, so you don't need to retain any legacy support for ".coder". Just make sure to fix any artifact files on this machine by changing ".coder" back to
".code".