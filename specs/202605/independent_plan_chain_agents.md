 Can you help me start splitting out all plan/question/feedback/coder agents out to their own independent agent entries (i.e. they show as their own entry on the "Agents" tab of the `sase ace`
TUI)? These should each continue to be named `<name>.plan/q/<N>/coder` using the same conventions that we do today.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

