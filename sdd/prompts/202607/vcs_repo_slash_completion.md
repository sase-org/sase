---
plan: sdd/epics/202607/vcs_repo_slash_completion.md
---
 Can you help me add good completion for GitHub repos when the user presses the `/` key an the argument provided to the `#gh` xprompt workflow?

- For example, typing `#gh:bbugyi200/` should trigger a completion menu for all valid, public GitHub repos in the `bbugyi200` GitHub organization.
- This needs to work both in the prompt input widget and in editors via LSP support ideally or (if LSP support is not possible / desirable here) the sase-nvim plugin.
- We should also be careful to provide support for this in a VCS-agnostic way such that it will be easy to add support for similar completion for, say, GitLab or some companies' internal VCS system later on when they write the sase plugin (ex: sase-gitlab) for their VCS.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! 

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 