---
plan: sdd/tales/202605/agents_header_counts.md
---
 Can you help me change the format of the agent count header shown at the top of the "Agents" tab of the
`sase ace` TUI? Namely, let's put the total in parentheses after "Agents" and let's add two new counts: `<N> waiting`
(these are currently counted as running, which is not correct) and `<M> read`. Also, we should change the order that the
counts are displayed in. For example, in the below `sase ace` snapshot, `Agents: 1 unread · 4 running · 17 total` should
be replaced with `Agents(17): 3 running · 1 waiting · 1 unread · 12 read`. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents (4 x13)  │  AXE (8)                                                                                                                                                        CODEX(gpt-5.5)  ■ IDLE  ✉ 7
 Agents: 1 unread · 4 running · 17 total   [view: file]   [group: by status (o)]   (auto-refresh in 2s)
┌─ (untagged) · 13 ───────────────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││                                                                                                                                       │
│  │  sase (PLAN APPROVED) ×6 @bj.plan                            🏃‍♂️ 2m22s    ││  AGENT DETAILS                                                                                                                        │
│  │  sase (PLAN APPROVED) ×6 @bi.plan                            🏃‍♂️ 4m07s    ││                                                                                                                                       │
│                                                                             ││  Project: sase                                                                                                                        │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agen    ││  Workspace: #102                                                                                                                  ▆▆  │
│  │  sase (WAITING) @bk                                                      ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                  │
│                                                                             ││  Model: CODEX(gpt-5.5)                                                                                                                │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  10 agents    ││  VCS: GitHub                                                                                                                          │
│  │  sase (PLAN DONE) ×6 @bh.plan                     11:26:32 · 🎉 8m04s    ││  PID: 3748219                                                                                                                         │
│  │  sase (PLAN DONE) ×6 @be.plan                        11:01:47 · 9m53s    ││  Name: @bj.plan                                                                                                                       │
│  │  sase (PLAN DONE) ×6 @bd.plan                        10:51:05 · 9m40s    ││  Timestamps: BEGIN | 2026-05-09 11:25:41                                                                                              │
│  │  sase (EPIC CREATED) ×6 @au.plan                     04:36:45 · 7m51s    ││              PLAN  | 2026-05-09 11:27:19                                                                                              │
│  │  sase (PLAN DONE) ×6 @as.plan                        04:11:58 · 7m56s    ││              CODE  | 2026-05-09 11:27:38                                                                                              │
│  │  sase (PLAN DONE) ×6 @ar.plan                       04:19:44 · 17m21s    ││  ARTIFACTS:                                                                                                                           │
│  │  sase (PLAN DONE) ×6 @ap.plan                       04:08:02 · 14m23s    ││    • ~/.sase/plans/202605/artifact_footer_tab_first.md                                                                                │
│  │  ▎ ak ─────────────────────────────────────────────────────  3 agents    ││                                                                                                                                       │
│  │  │  sase (PLAN DONE) ×6 @ak.plan                    03:32:26 · 14m50s    │└───────────────────────────────────────────────────────── ● files  ○ thinking ─────────────────────────────────────────────────────────┘
│  │  │  ▸ ak.code ─────────────────────────────────────────────  2 agents    │┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  │  │  sase (PLAN DONE) ×8 @ak.code.r1.code.r1.plan    11:00:17 · 10m59s    ││                                                                                                                                       │
│  │  │  sase (PLAN DONE) ×8 @ak.code.r1.plan            03:52:44 · 11m09s    ││  /home/bryan/.sase/plans/202605/artifact_footer_tab_first.md                                                                          │
│                                                                             ││                                                                                                                                       │
│                                                                             ││     1 # Plan: Move Artifact Viewer Tab Hint To Footer Start                                                                           │
│                                                                             ││     2                                                                                                                                 │
│                                                                             ││     3 ## Goal                                                                                                                         │
│                                                                             ││     4                                                                                                                                 │
│                                                                             ││     5 Make the artifact viewer tmux pane footer place the `<tab>: Ace` hint at the beginning of the footer line whenever the          │
│                                                                             ││     6 return-to-Ace pane shortcut is available.                                                                                       │
│                                                                             ││     7                                                                                                                                 │
│                                                                             ││     8 This should preserve all existing navigation behavior: `<tab>` still focuses the original Ace pane and keeps the                │
│                                                                             ││     9 artifact viewer open, while `j`/`k`, `n`/`p`, `r`, and `q` continue to behave as they do today.                                 │
│                                                                             ││    10                                                                                                                                 │
│                                                                             ││    11 ## Current Behavior                                                                                                             │
│                                                                             ││    12                                                                                                                                 │
│                                                                             ││    13 The tmux artifact viewer path launches `python -m sase.ace.tui.graphics.viewer`, which calls                                    │
│                                                                             ││    14 `run_artifact_sequence_loop()` in `src/sase/ace/tui/graphics/_viewer_loop.py`.                                                  │
│                                                                             ││    15                                                                                                                                 │
│                                                                             ││    16 The footer text is built by `print_page_prompt()` from the ordered tuple returned by `page_loop_available_keys()`. That         │
│                                                                             ││    17 tuple currently appends the return-to-Ace key after page and artifact navigation keys:                                          │
│                                                                             ││    18                                                                                                                                 │
│                                                                             ││    19 - page navigation: `j`, `k`                                                                                                     │
│                                                                             ││    20 - artifact navigation: `n`, `p`                                                                                                 │
│                                                                             ││    21 - return-to-Ace: `<tab>`                                                                                                        │
│                                                                             ││    22 - utility actions: `r`, `q`                                                                                                     │
│                                                                             ││    23                                                                                                                                 │
│                                                                             ││    24 In a multi-page or multi-artifact viewer this renders `<tab>: Ace` in the middle of the footer action list instead of as        │
│                                                                             ││    25 the first visible action.                                                                                                       │
└─────────────────────────────────────────────────────────────────────────────┘│    26                                                                                                                                 │
                                                                               │    27 ## Design                                                                                                                       │
┌─ #blog · 3 ─────────────────────────────────────────────────────────────────┐│    28                                                                                                                                 │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3 agents                ││    29 Treat return-to-Ace as the primary pane-control action and order it before viewer-local navigation in the footer.               │
│  │  ▎ 260507 ─────────────────────────────────────  3 agents                ││    30                                                                                                                                 │
│  │  │  ▸ 260507.ajh ──────────────────────────────  3 agents                ││    31 The smallest coherent change is to update `page_loop_available_keys()` so `_RETURN_TO_ACE_KEY` is added first when              │
│  │  │  sase (DONE) ×5 @260507.ajh           May 7 17:21 · 6m                ││    32 `return_pane_available=True`. Because `print_page_prompt()` already renders labels in `page_loop_available_keys()`              │
│  │  │  sase (DONE) ×7 @260507.ajh.r1.r1  May 7 17:35 · 6m35s                ││    33 order, this moves `<tab>: Ace` to the start of the action list without adding a second formatting path.                         │
│  │  │  sase (DONE) ×7 @260507.ajh.r1     May 7 17:28 · 6m51s                ││    34                                                                                                                                 │
└─────────────────────────────────────────────────────────────────────────────┘│    35 For the tmux sequence loop, `print_page_prompt(..., show_position=False)` means the footer line itself will begin with          │
                                                                               │    36 `<tab>: Ace` when the return pane is available. For the standalone page loop, existing page-position text may still             │
┌─ #chop · 1 ─────────────────────────────────────────────────────────────────┐│                                                                                                                                       │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running               ││    ▾ 34 more lines below                                                                                                              │
│  │  ⚡ sase (RUNNING) ×4 @pysplit.agent_cleanup_modal  🏃‍♂️ 43s               ││                                                                                                                                       │
└─────────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────── Lines 1-36 of 70 ───────────────────────────────────────────────────────────┘
 COPY c chat  E file path  n name  p prompt  s snap                                                                                                                                                            RUNNING
```