---
keyword: Sase Monitor
aliases:
  - monitor
---

A sase monitor is a family-attached proc shell that runs one long command under a
detached supervisor, so the command outlives the agent that started it. Starting one
from inside an agent hands off and kills that agent's turn, and an agent has at most one
active monitor at a time; monitor members are named `<family>--mon`, then `--mon-0`,
`--mon-1`. A monitor settles as `completed`, `failed`, `timeout`, `stopped`, or `lost`,
and only the first three launch the follow-up agent recorded by `--next`. Inspect
monitors with `sase monitor`.
