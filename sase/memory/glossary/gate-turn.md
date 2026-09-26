---
keyword: Gate Turn
---

A gate turn is a session-attached turn — like a monitor turn or an agent turn — that
owns one durable command-backed decision. It publishes the decision, outlives the agent
that created it, runs the option commands the reviewer selects, and hands their outcome
to the next session member. A gate carrying a `turn` block (`turn_kind: "gate"`) is a
gate turn. Creating a gate turn from inside an agent hands off and kills that agent's
turn; if the creator had no agent session yet, attaching the gate turn promotes it into
one. Members are named `<session>--gate`, then `--gate-0`, `--gate-1` — the same suffix
scheme a sase monitor uses for `--mon`. A gate turn settles as `completed`, `failed`,
`timeout`, `stopped`, or `lost`, and launches only the follow-up recorded for the branch
the reviewer selected. A gate turn contains no LLM and never keeps its creator alive
while awaiting a human. Inspect gate turns with `sase gate`. Formerly called a gate
shell.
