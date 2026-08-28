---
keyword: Sase Gate
aliases:
  - gate
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
one. A gate carrying a `shell` block is a gate shell and settles as `completed`,
`failed`, `timeout`, `stopped`, or `lost`; a gate with no `shell` block settles only as
answered, cancelled, or timed out. `sase gate wait` reports the latter and is for
non-agent callers — an agent observes a gate shell through the family it hands off to,
never by waiting. Unrelated to the pytest suite gate and `just check`'s lint gates.
