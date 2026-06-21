---
plan: sdd/tales/202606/vcs_project_completion_replace_existing_tag.md
---
 When the `#+` functionality is used in the prompt input widget or in nvim to select a new project right after an existing VCS xprompt workflow invocation (ex: `#gh:sase #+`), then that existing VCS xprompt workflow is never replaced by the selected one. Instead, we wind up with something like what is shown in the ~/tmp/bad_project_expansion.txt file. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 