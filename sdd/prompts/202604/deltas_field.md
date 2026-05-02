---
plan: sdd/epics/202604/deltas_field.md
---
 I want to add a new DELTAS ChangeSpec field that contains a list of all of the files that the ChangeSpec added, modified, or deleted.

- These entries will need to be updated anytime the real file changes for the CL associated with this ChangeSpec change (ex: after rewinds, new commits, etc...).
- We should also show some visual indicator that shows whether the file was added, modified, or deleted. I want you to lead the design on this one. Just make sure it looks beautiful!

Can you help me make this change? This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

 