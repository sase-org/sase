---
keyword: Sase Agent
aliases:
  - agent
---

A sase agent is an agent session or a single agent that does not belong to a session. It
owns an ordered sequence of sase shells, and its name never ends in `--<suffix>` because
that suffix is reserved for agent shells. A one-shell agent may share its shell name,
while a session uses the bare name for its container.
