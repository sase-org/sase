---
keyword: Sase Monitor
aliases:
  - monitor
  - monitor turn
---

A sase monitor is a monitor turn that runs one long command under a detached supervisor,
so the command outlives the agent that started it. Starting one from inside an agent
stages a handoff that the host adopts after the turn completes through `/sase_final`,
and an agent has at most one active monitor at a time; monitor members are named
`<session>--mon`, then `--mon-0`, `--mon-1`. A monitor settles as `completed`, `failed`,
`timeout`, `stopped`, or `lost`, and only the first three launch the follow-up agent
recorded by `--next`. Inspect monitors with `sase monitor`.
