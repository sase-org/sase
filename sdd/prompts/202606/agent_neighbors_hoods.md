---
plan: sdd/tales/202606/agent_neighbors_hoods.md
---
 I want to rename the concept of "agent siblings" to "agent neighbors" that live in different neighborhoods, which we will call "hoods". A hood, say `foo.bar`, is an agent name namespace. So, we would say that a sase agent with a name of `foo.bar.baz` is in the `foo.bar` hood (keep in mind that `foo.bar` may or may not correspond with a sase agent). The `foo.bar` hood is then a "sub-hood" of the `foo` hood. Can you help me update the terminology used throughout the codebase and all of our documentation to adhere to this new nomenclature?

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
