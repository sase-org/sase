 Can you help me start removing any `.code` / `.plan` part in an agent name before adding `.r<N>` when
constructing an agent name for agents that contained the `#resume` prompt? Also, just increment `<N>` instead of adding
a new `.r<N>` if possible. These agent names are getting way too long (see the `sase ace` snapshot below). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents (22 x3)  │  AXE (8)                                                                                                                                        Override CODEX(gpt-5.5) 30h45m  ■ IDLE  ✉ 2
 Agents: 1/25   [view: file]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 25 ───────────────────────────────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4 agents · 4 running    ││                                                                                                                       │
│  │  sase (PLAN APPROVED) ×8 @ma.code.r1.code.r1.code.r1              3m05s    ││  AGENT DETAILS                                                                                                        │
│  │  ⚡ sase (RUNNING) ×4 ◆ sase-1t.1 @sase-1t.1                                    6m12s    ││                                                                                                                   ▆▆  │
│  │  ⚡ sase (RUNNING) ×4 ◆ sase-1s.3 @sase-1s.3                                      12s    ││  Project: sase                                                                                                        │
│  │  ⚡ sase (RUNNING) ×4 ◆ sase-1r.2 @sase-1r.2                                      18s    ││  Workspace: #103                                                                                                      │
│                                                                                             ││  Embedded Workflows: gh(gh_ref=sase), resume(name=ma.code.r1.code.r1.code)                                   │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  18 agent    ││  Model: CODEX(gpt-5.5)                                                                                                │
│  │  ▸ sase-1r ────────────────────────────────────────────────────────────────  8 agents    ││  VCS: GitHub                                                                                                          │
│  │  ⚡ sase (WAITING) ◆ sase-1r @sase-1r.land                                               ││  PID: 916968                                                                                                          │
│  │  ⚡ sase (WAITING) ◆ sase-1r.9 @sase-1r.9                                                ││  Name: @ma.code.r1.code.r1.code.r1                                                                      │
│  │  ⚡ sase (WAITING) ◆ sase-1r.8 @sase-1r.8                                                ││  Timestamps: BEGIN | 2026-05-01 13:20:02                                                                              │
│  │  ⚡ sase (WAITING) ◆ sase-1r.7 @sase-1r.7                                                ││              PLAN  | 2026-05-01 13:22:14                                                                              │
│  │  ⚡ sase (WAITING) ◆ sase-1r.6 @sase-1r.6                                                ││                                                                                                                       │
│  │  ⚡ sase (WAITING) ◆ sase-1r.5 @sase-1r.5                                                ││  ──────────────────────────────────────────────────                                                                   │
│  │  ⚡ sase (WAITING) ◆ sase-1r.4 @sase-1r.4                                                ││                                                                                                                       │
│  │  ⚡ sase (WAITING) ◆ sase-1r.3 @sase-1r.3                                                ││                                                                                                                       │
│  │  ▸ sase-1s ────────────────────────────────────────────────────────────────  4 agents    │└───────────────────────────────────────────────── ● files  ○ thinking ─────────────────────────────────────────────────┘
│  │  ⚡ sase (WAITING) ◆ sase-1s @sase-1s.land                                               │┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  │  ⚡ sase (WAITING) ◆ sase-1s.6 @sase-1s.6                                                ││                                                                                                                       │
│  │  ⚡ sase (WAITING) ◆ sase-1s.5 @sase-1s.5                                                ││  /home/bryan/.sase/plans/202605/conditional_one_hour_headings.md                                                      │
│  │  ⚡ sase (WAITING) ◆ sase-1s.4 @sase-1s.4                                                ││                                                                                                                       │
│  │  ▸ sase-1t ────────────────────────────────────────────────────────────────  6 agents    ││      1 # Conditional one-hour heading visibility                                                                      │
│  │  ⚡ sase (WAITING) ◆ sase-1t @sase-1t.land                                               ││      2                                                                                                                │
│  │  ⚡ sase (WAITING) ◆ sase-1t.6 @sase-1t.6                                                ││      3 ## Goal                                                                                                        │
│  │  ⚡ sase (WAITING) ◆ sase-1t.5 @sase-1t.5                                                ││      4                                                                                                                │
│  │  ⚡ sase (WAITING) ◆ sase-1t.4 @sase-1t.4                                                ││      5 In `BY_DATE` grouping, suppress one-hour headings when their enclosing 4-hour window contains only one         │
│  │  ⚡ sase (WAITING) ◆ sase-1t.3 @sase-1t.3                                                ││        visible                                                                                                        │
│  │  ⚡ sase (WAITING) ◆ sase-1t.2 @sase-1t.2                                                ││      6 ChangeSpec or agent entry. Keep 4-hour headings visible as they are today. When the 4-hour window contains     │
│                                                                                             ││        two or more                                                                                                    │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents    ││      7 entries, keep showing one-hour headings so dense windows remain scannable.                                     │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1s.2 @sase-1s.2                            13:20:31 · 9m51s    ││      8                                                                                                                │
│  │  ⚡ sase (DONE) ×5 ◆ sase-1r.1 @sase-1r.1                           13:23:01 · 19m03s    ││      9 This applies to both grouped surfaces that currently emit one-hour headings:                                   │
│  │  sase (PLAN DONE) ×7 @ma.code.r1.code.r1.code.r1.plan                13:08:21 · 8m48s    ││     10                                                                                                                │
│                                                                                             ││     11 - CLs tab `BY_DATE`: `Today` / `Yesterday` date buckets render `date bucket -> 4-hour window -> one-hour       │
│                                                                                             ││        heading -> CL`.                                                                                                │
│                                                                                             ││     12 - Agents tab `BY_DATE`: date buckets render `date bucket -> 4-hour window -> one-hour heading -> agent`.       │
│                                                                                             ││     13                                                                                                                │
│                                                                                             ││     14 ## Current behavior and relevant code                                                                          │
│                                                                                             ││     15                                                                                                                │
│                                                                                             ││     16 - ChangeSpec grouping emits every `hour_subgroup` under `BY_DATE` Today / Yesterday:                           │
│                                                                                             ││     17   - `src/sase/ace/tui/models/changespec_groups/_tree.py`                                                       │
│                                                                                             ││     18   - `src/sase/ace/tui/models/changespec_groups/_keys.py`                                                       │
│                                                                                             ││     19   - `src/sase/ace/tui/models/changespec_groups/_buckets.py`                                                    │
│                                                                                             ││     20 - Agent grouping emits every `one_hour` under every real 4-hour `BY_DATE` window:                              │
│                                                                                             ││     21   - `src/sase/ace/tui/models/agent_groups/_tree.py`                                                            │
│                                                                                             ││     22   - `src/sase/ace/tui/models/agent_groups/_keys.py`                                                            │
│                                                                                             ││     23   - `src/sase/ace/tui/models/agent_groups/_buckets.py`                                                         │
│                                                                                             ││     24 - Banner rendering should not need a behavioral change. The visible rows are driven by the tree builders,      │
│                                                                                             ││        and renderers                                                                                                  │
│                                                                                             ││     25   already style the one-hour rows correctly when they exist.                                                   │
│                                                                                             ││     26 - Fold/navigation/jump-hint behavior depends on the same group-key enumeration functions, so enumeration       │
│                                                                                             ││        must match tree                                                                                                │
│                                                                                             ││     27   emission exactly.                                                                                            │
│                                                                                             ││     28                                                                                                                │
│                                                                                             ││     29 ## Design                                                                                                      │
│                                                                                             ││     30                                                                                                                │
│                                                                                             ││     31 Treat this as a model/tree-shape rule, not a display-only rendering rule.                                      │
│                                                                                             ││                                                                                                                       │
│                                                                                             ││    ▾ 98 more lines below                                                                                              │
│                                                                                             ││                                                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────── Lines 1-31 of 129 ──────────────────────────────────────────────────┘
 COPY c chat  E file path  n name  p prompt  s snap                                                                                                                                                            RUNNING
```