---
plan: sdd/tales/202607/gh_first_use_project_display.md
---
 When the `#gh` VCS xprompt workflow is used with a new project, the GitHub org and repo need to be specified (ex: `#gh:foo-org/foo`). After this first use however, the user can just use `#gh:foo` to specify this project. The first agent that uses this project should not, however, look special. For example, it should show `foo` as its project, but we seem to be showing `foo-org/foo` instead (see #sshot for a real example with the `bbugyi200/actstat` project). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  