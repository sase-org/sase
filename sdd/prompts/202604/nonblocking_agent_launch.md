---
plan: sdd/plans/202604/nonblocking_agent_launch.md
---
When I pass multiple models to the `%model` directive, we run one agent per model argument. This works well, but it
takes a few seconds after the user hits `<enter>` from the prompt input widget before the user's thread is unblocked
again. Can you help me make launching agents (one or many) from the TUI unblock instantly (or much faster at least) so
the user can immediately do something else in the TUI after hitting `<enter>`? Think this through thoroughly and create
a plan using your `/sase_plan` skill before making any file changes.
