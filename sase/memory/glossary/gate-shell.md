---
keyword: Gate Shell
---

A gate shell is a family-attached shell — like a proc shell or an agent shell — that
owns one durable command-backed decision. It publishes the decision, outlives the agent
that created it, runs the option commands the reviewer selects, and hands their outcome
to the next family member. Creating a gate shell from inside an agent hands off and
kills that agent's turn; if the creator had no agent family yet, attaching the gate
shell promotes it into one. Members are named `<family>--gate`, then `--gate-0`,
`--gate-1` — the same suffix scheme a sase monitor uses for `--mon`. A gate shell
settles as `completed`, `failed`, `timeout`, `stopped`, or `lost`, and launches only the
follow-up recorded for the branch the reviewer selected. A gate shell contains no LLM
and never keeps its creator alive while awaiting a human. Inspect gate shells with
`sase gate`.
