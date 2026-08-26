---
keyword: Sase Gate
aliases:
  - gate
  - gates
---

A sase gate is a durable, command-backed request for one user decision, created when
work must pause for the user. Each gate is a bundle under
`~/.sase/interaction_requests/<kind>/<request-id>/` holding the hashed request, the
reviewed content, and the argv commands its options run; a notification row is only its
transport projection, so ACE, Telegram, mobile, and `sase gate` all answer the same
bundle. An option query such as `(approve AND commit) OR reject` names the mutually
exclusive branches; answering selects a non-empty subset of exactly one branch, runs
those options' commands, and writes `response.json` once, while a gate's declared
actions are repeatable and never answer it. Typed kinds (plan, epic plan, question,
launch, task triage) have their own front doors; `sase gate create` builds a `custom`
one. A gate settles only as answered, cancelled, or timed out — the statuses
`sase gate wait` reports. Unrelated to the pytest suite gate and `just check`'s lint
gates.
