---
plan: sdd/epics/202604/agent_cleanup_panel.md
---
 Can you help me replace the existing `X` and `,X` keymaps with a single `X` keymap that triggers a nice panel
that offers single-keypress options (ex: dismiss all done, kill/dismiss all, kill all with tag @foo, etc...) as well as
a custom selection option that gives the user more granular (but still simple with minimal keypresses) control over
which agent/workflow entries get dismissed/killed? While making this change, we should also try to migrate as much of
the backend logic (the stuff our later web/mobile apps might need) for dismissing/killing agent/workflow entries to the
../sase-core repo (our Rust backend).

I want you to lead the design on this one. Just make sure it looks beautiful! This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

