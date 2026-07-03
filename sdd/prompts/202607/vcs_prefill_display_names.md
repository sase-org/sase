---
plan: sdd/tales/202607/vcs_prefill_display_names.md
---
 When I use the `<ctrl+space>` keymap to open up the prompt input widget with the last VCS xprompt workflow prepended to the start of the prompt, I'm currently getting the following VCS xprompt workflow: `#gh:gh_sase-org__sase`. This is the full, real name of the project, but we should only EVER show the configured project name to the user, so the VCS xprompt workflow that was inserted should have been `#gh:sase`. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 