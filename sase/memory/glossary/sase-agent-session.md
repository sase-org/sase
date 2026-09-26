---
keyword: Sase Agent Session
aliases:
  - agent session
---

A sase agent session is a sase agent whose agent turns run as a strictly sequential
chain. Its turns use `<session>--<suffix>` names. The first
`%id(<suffix>, session=<parent>)` attachment renames the original turn with its own
suffix and reserves the bare session name as the sase agent container, so a session
always has at least two turns. It was formerly called an agent family. It is distinct
from TUI sessions (`sase proc --session`), provider transcript sessions (`session_id`),
and question sessions.
