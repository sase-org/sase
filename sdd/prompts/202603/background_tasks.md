---
plan: sdd/epics/202603/background_tasks.md
---
#gh:sase #resume:o I like Option C (hybrid) from the sdd/research/202603/send_cmds_to_axe.md file. Let's just migrate the `Y`
(sync), `M` (mail), and `a` (accept) commands for now. NOTE: We should only run the actual mail command (after the user
selects 'y' to mail) for the `M` (mail) keymap. Can you help me write an implementation plan for this?

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
