---
keyword: Agent Clan
---

An agent clan is a named, rootless container for agents that run in parallel. Every
member is named inside the clan's hood (`<clan>.<suffix>`) and declares `%clan:<clan>`;
the clan name is reserved and is never itself an agent.

An agent clan node's status aggregates its member agent nodes, except that a clan with
exactly one running member (`STARTING` included) shows exactly that node's status — its
label, styling, and row overlays such as `FINALIZING` — rather than a generic `RUNNING`.
Only a member that needs the user (asking, awaiting plan review, or failed) outranks it.
