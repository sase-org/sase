---
plan: sdd/epics/202604/dynamic_tag_panels.md
---
  Can you help me generalize the concept of the pinned panel on the agents tab by using agent tags to dynamically determine how many panels on the left there should be?

- This means we should only use two levels of nested agent groups now (since each agent tag will be given its own panel).
- This also means that an agent can only ever have one tag (which was always my intent) 
- This also means we should get rid of the concept of pinned agent entries all together (make sure we remove all references to this) 
- We also need a way to navigate to the different dynamic side panels now. We used to use the 'o' key to navigate to and from the pinned panel. And we used to use the 'J' and 'K' keys to move agent entries around. Moving agent entries around is no longer necessary so we will use J and K to navigate to these dynamic panels.
- We should also support a new %tag directive so an agent's tag can be specified explicitly in the prompt.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

