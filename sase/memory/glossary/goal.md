---
keyword: Goal
aliases: [goals, ⌖]
---

A goal is a person-owned durable outcome record with identity `goal:<id>` (shown as
`⌖<id>`). It moves through `active`, `review`, `done`, and `dropped`; Running versus
Idle is derived from agent liveness and never stored. `@goal:<id>` cites a goal in a
prompt and never binds one; see [[glossary/artifact-reference]] for the citation
mechanics and [[decisions/goal-ledger]] for the storage contract.

Not to be confused with a plan's `goal:` frontmatter field (one line of intent, no
record behind it), a task bead (agent work tracking), or agent status (liveness, not
outcomes).
