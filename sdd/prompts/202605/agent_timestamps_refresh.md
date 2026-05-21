---
plan: sdd/tales/202605/agent_timestamps_refresh.md
---
 The PLAN and CODE timestamps keep disappearing from this agent's (see the `sase ace` snapshot below) metadata panel on the "Agents" tab of the `sase ace` TUI (it seems like this happens on every auto-refresh maybe). Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                        sase ace (PID: 2991460)
  CLs  │  Agents  │  AXE                                                                                                                                                         CODEX(gpt-5.5)  ■ IDLE  ✉ 0
 3 Agents [1 running · 2 done]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 4s)
┌─ (untagged) · 3 [R1 D2] ────────────────────────────────────┐┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││                                                                                                                                            │
│  │  🤖 sase (TALE APPROVED) ×8 @awj.r1          🏃‍♂️ 5m59s    ││  AGENT DETAILS                                                                                                                             │
│                                                             ││                                                                                                                                            │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents    ││  Project: sase                                                                                                                             │
│  │  🤖 sase (TALE DONE) ×6 @awk         09:03:42 · 7m41s    ││  Workspace: #10                                                               ▌                                                            │
│  │  🤖 sase (TALE DONE) ×6 @awj         08:58:37 · 8m33s    ││  Model: CODEX(gpt-5.5)                                                        ▌ Refreshed                                                  │
│                                                             ││  VCS: GitHub                                                                  ▌                                                            │
│                                                             ││  PID: 2981407                                                                                                                              │
│                                                             ││  Name: @awj.r1                                                                                                                             │
│                                                             ││  Waiting for: awj                                                                                                                          │
│                                                             ││  Timestamps: WAIT  | 2026-05-21 08:49:21                                                                                                   │
│                                                             ││              RUN   | 2026-05-21 08:58:48                                                                                                   │
│                                                             ││              PLAN  | 2026-05-21 09:01:26                                                                                                   │
│                                                             ││              CODE  | 2026-05-21 09:02:48                                                                                                   │
│                                                             ││                                                                                                                                            │
│                                                             ││  ──────────────────────────────────────────────────                                                                                        │
│                                                             ││                                                                                                                                            │
│                                                             ││  AGENT XPROMPT                                                                                                                             │
│                                                             ││                                                                                                                                            │
│                                                             ││  #gh:sase #resume:awj %w:awj Also, can you help me make the manual refresh, which is triggered by the `y` keymap, faster by querying       │
│                                                             ││  the active agent index instead of whatever we are doing right now (it still takes ~3s to refresh, which is very slow)? #plan              │
│                                                             ││                                                                                                                                            │
│                                                             ││  ──────────────────────────────────────────────────                                                                                        │
│                                                             ││                                                                                                                                            │
│                                                             ││  AGENT PROMPT                                                                                                                              │
│                                                             ││                                                                                                                                            │
│                                                             ││                                                                                                                                            │
│                                                             ││  # Previous Conversation                                                                                                                   │
│                                                             ││                                                                                                                                        ▇▇  │
│                                                             ││  **User:**                                                                                                                                 │
│                                                             ││                                                                                                                                            │
│                                                             ││  %model:gpt-5.5                                                                                                                            │
│                                                             ││  #gh:sase @sdd/tales/202605/agents_refresh_on_notifications.md                                                                             │
│                                                             ││                                                                                                                                            │
│                                                             ││  The above plan has been reviewed and approved. Implement it now.                                                                          │
│                                                             ││                                                                                                                                            │
│                                                             ││  **Assistant:**                                                                                                                            │
│                                                             ││                                                                                                                                            │
│                                                             ││  I’ll read the approved plan and the always-loaded project memory first, then map the change to the existing code before editing.          │
│                                                             ││                                                                                                                                            │
│                                                             ││  The plan is narrowly scoped to notification polling and the auto-refresh event path, with tests in two existing files. I’m checking       │
│                                                             ││  those modules now so the edit follows the current async/coalescing behavior instead of introducing another load path.                     │
│                                                             ││                                                                                                                                            │
│                                                             ││  The existing bucket helper already excludes silent rows from active unread buckets and keeps muted rows separate, so the boolean          │
│                                                             ││  return can be driven directly by the existing `new_notifications` list. I’m going to make that return value explicit and wire the     ▁▁  │
│                                                             ││  event tick to schedule, not load, when the notification path is the trigger.                                                              │
│                                                             ││                                                                                                                                            │
│                                                             ││  The core wiring and test fakes are updated. I’m running the focused tests first; if they’re clean I’ll do the repo-required               │
│                                                             ││  install/check flow from this workspace.                                                                                                   │
│                                                             ││                                                                                                                                            │
│                                                             ││  The focused test run failed at collection because this workspace is missing installed dependencies (`textual`). That matches the          │
│                                                             ││  project memory warning, so I’m installing the editable environment before re-running tests.                                               │
│                                                             ││                                                                                                                                            │
│                                                             ││  The workspace install completed. I’m re-running the focused tests now, then I’ll run the full `just check` required for code changes.     │
│                                                             ││                                                                                                                                            │
│                                                             ││                                                                                                                                            │
└─────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────── ● files  ● tools ─────────────────────────────────────────────────────────────┘
 a approve  A artifacts  n name  N tag/untag  t tmux  T tmux (primary)  W new w/ wait  x kill  X cleanup (2 done)                                                                                   RUNNING


```