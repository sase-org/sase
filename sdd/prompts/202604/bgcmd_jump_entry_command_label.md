---
plan: sdd/tales/202604/bgcmd_jump_entry_command_label.md
---
 Can you help me start showing the command that was run from the "Jump to Entry" panel (see the `sase ace` snapshot below)? In other words, let's start using entries of the form `bgcmd #<N>: <command>` instead of just
`bgcmd #<N>`. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                                    sase ace
  CLs (2)  │  Agents (x2)  │  AXE (5 x1 .3)                                                                                                                                                                                                       ✉ 2
┌─────────────────────────────────┐
│  [*] sase axe                   │ [RUNNING]  │  PID: 3932408  │  Cmd: xpad  │  Project: bug  │  WS: 1  │  Runtime: 2h 3m 31s  │  (auto-refresh in 5s)
│    └─ [*] checks                │───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
│    └─ [*] comments              │
│    └─ [*] hooks                 │  bash: cannot set terminal process group (3932408): Inappropriate ioctl for device
│    └─ [*] housekeeping          │  bash: no job control in this shell
│    └─ [*] waits                 │  bash: /home/build/non╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
│  ◌ [✓] rabbit test -c opt       │  bash: /home/build/non║                                                                                                                                ║
│  //j...                         │  Apr 24, 2026 1:15:52 ║                                                                                                                                ║
│  ◌ [*] xpad                     │  WARNING: Flag --com.g║                                                   ─── ✦ Jump to Entry ✦ ───                                                    ║) for Stubby server.
│  ◌ [*] rabbit test -c opt       │  Apr 24, 2026 1:15:53 ║                                                                                                                                ║
│  //j...                         │  INFO: We are not runn║                                                                                                                                ║
│                                 │  Launchpad is running ║    ── CLs (2) ───────────────────────────────────────────────────────────────                                                  ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║      [1] yserve_read_grow                                                Mailed                                                ║
│                                 │                       ║      [2] yserve_write_grow_1                                              Draft                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║    ── Agents (2) ────────────────────────────────────────────────────────────                                                  ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║      [3] yserve_read_grow/20260424143711                                   DONE                                                ║
│                                 │                       ║      [4] yserve_read_grow/20260424143638                                   DONE                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║    ── AXE (9) ───────────────────────────────────────────────────────────────                                                  ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║      [5] sase axe                                                                                                              ║
│                                 │                       ║        [6] checks                                                                                                              ║
│                                 │                       ║        [7] comments                                                                                                            ║
│                                 │                       ║        [8] hooks                                                                                                               ║
│                                 │                       ║        [9] housekeeping                                                                                                        ║
│                                 │                       ║        [0] waits                                                                                                               ║
│                                 │                       ║      [a] bgcmd #1                                                                                                              ║
│                                 │                       ║      [b] bgcmd #2                                                                                                              ║
│                                 │                       ║      [c] bgcmd #3                                                                                                              ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║  ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────  ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ║                                            press key to jump · ` back · esc cancel                                             ║
│                                 │                       ║                                                                                                                                ║
│                                 │                       ╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
│                                 │
│                                 │
│                                 │
│                                 │
│                                 │
└─────────────────────────────────┘
 x kill                                                                                                                                                                                                                         RUNNING   [*2]  [✓1]


```