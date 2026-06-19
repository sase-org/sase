---
plan: sdd/tales/202606/finalizer_opened_siblings.md
---
 Can you help me have the commit finalizer start only checking sibling repos that it knows the agent opened using the `sase workspace open` command? This change will allow us to stop having to worry about cleaning up sibling workspace repos which might be dirty from unexpectedly terminated agent runs, for example. See the "research.u.image" sase agent for an example of the type of false positive I'm talking about.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 