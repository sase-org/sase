---
keyword: Sase Service
aliases:
  - service host
---

The sase service is the per-machine host process (`sase service run`) that starts,
restarts, and stops that machine's service procs, with at most one per SASE home.
`sase service init` registers it as a platform unit — a systemd user unit on Linux, a
launchd LaunchAgent on macOS — so it starts at boot or login; without one,
`sase service start` runs it detached. systemd/launchd supervises the sase service
itself, never each service proc. Say 'service proc' for what it runs and 'platform unit'
for its registration; bare 'service' is ambiguous.
