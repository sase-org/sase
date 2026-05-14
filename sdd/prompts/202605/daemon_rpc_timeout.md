---
plan: sdd/tales/202605/daemon_rpc_timeout.md
---
 It looks like the sase daemon is having an issue with RPCs (see the below output of the `sase daemon doctor` command). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
SASE daemon status: running
Run root: /home/bryan/.sase/run/sase-host
Socket: /home/bryan/.sase/run/sase-host/sase-daemon.sock
Log: /home/bryan/.sase/run/sase-host/daemon.log
PID: 3065686
Host: sase-host
Started: 2026-05-14T18:32:19Z
Build: 0.1.1
Detail: daemon metadata points at live pid 3065686
RPC: timed out talking to local daemon at /home/bryan/.sase/run/sase-host/sase-daemon.sock
Doctor: error
- storage_layout: ok - runtime files are under the host-local layout
- lock_metadata: ok - daemon metadata points at live pid 3065686
- process_liveness: ok - metadata pid 3065686 is live
- socket_rpc_health: error - timed out talking to local daemon at /home/bryan/.sase/run/sase-host/sase-daemon.sock
- projection_db: unknown - projection health requires live daemon RPC
- source_exports: unknown - source-export diagnostics require live daemon RPC
- indexing: unknown - indexing health requires live daemon RPC
- scheduler: unknown - scheduler health requires live daemon RPC
- mobile_http: skipped - mobile HTTP is disabled or metrics endpoint was not published
Repair actions:
- daemon_verify: read_only - Verify daemon projections against source stores.
  Command: sase daemon verify -H /home/bryan/.sase --run-root /home/bryan/.sase/run/sase-host --socket-path /home/bryan/.sase/run/sase-host/sase-daemon.sock
- daemon_stop: runtime_only - Stop the live daemon owned by this host.
  Command: sase daemon stop -H /home/bryan/.sase --run-root /home/bryan/.sase/run/sase-host --socket-path /home/bryan/.sase/run/sase-host/sase-daemon.sock
```