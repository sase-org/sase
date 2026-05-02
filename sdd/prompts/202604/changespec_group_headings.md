---
plan: sdd/epics/202604/changespec_group_headings.md
---
 Can you help me add support for configurable (via the new `o` keymap on the CLs tab) ChangeSpec groups with headings that can be folded/expanded? The UX for this should take heavy inspiration from agent group headings on the
Agents tab. We should support 3 grouping/sorting strategies:

1. by project: level 1 headings should be project names and level 2 headings should be siblings (ex: "foobar" if ChangeSpecs named "foobar_1" and "foobar_2" exist and are matched by the current ChangeSpec query)
2. by date: level 1 headings only, which should be a date (ex: "Today"). When using this grouping/sorting strategy, we should use the latest TIMESTAMPS ChangeSpec field values to decide which group each ChangeSpec belongs to.
3. by status: level 1 headings only, which should be the ChangeSpec STATUS field value of the ChangeSpecs that are in that group.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 