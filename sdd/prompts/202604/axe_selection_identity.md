---
plan: sdd/plans/202604/axe_selection_identity.md
---
 The selected entry on the AXE tab keeps jumping from "xpad" to "housekeeping" on another machine (see the `sase ace` snapshot below). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

### `sase ace` Snapshot
```
⭘                                                                                                                    sase ace
  CLs (6)  │  Agents (1 x4)  │  AXE (6 .1)                                                                                                                                                                                                        ✉ 4
┌─────────────────────────────────┐
│  [*] sase axe                   │ [RUNNING]  │  PID: 722848  │  Cmd: xpad  │  Project: pat  │  WS: 1  │  Runtime: 1m 34s  │  (auto-refresh in 5s)
│    └─ [*] checks                │───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
│    └─ [*] comments              │
│    └─ [*] gchat                 │  bash: cannot set terminal process group (722848): Inappropriate ioctl for device
│    └─ [*] hooks                 │  bash: no job control in this shell
│    └─ [*] housekeeping          │  bash: /home/build/nonconf/google3/java/com/google/ads/publisher/scripts/xfp/bashrc.sh: No such file or directory
│    └─ [*] waits                 │  bash: /home/build/nonconf/google3/ads/publisher/qubos/admanager/tools/aliases.sh: No such file or directory
│  ◌ [*] xpad                     │  Apr 27, 2026 2:33:25 PM com.google.common.flags.Flag warnIfDeprecated
│                                 │  WARNING: Flag --com.google.apps.framework.rpc.RunStubby3Module.stubby_enable_security_manager is deprecated: DEPRECATED. If true, enables GJSM (go/gjsm) for Stubby server.
│                                 │  Apr 27, 2026 2:33:25 PM com.google.security.uberproxy.UberproxyGroupsDynamic isRunningInTpc
│                                 │  INFO: We are not running in Borg. [CONTEXT ratelimit_period="60 MINUTES" ]
│                                 │  Launchpad is running at http://bbugyi.c.googlers.com:5555
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
└─────────────────────────────────┘
 x kill                                                                                                                                                                                                                               RUNNING   [*1]
```