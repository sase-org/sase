---
plan: sdd/tales/202605/non_agent_child_model_badges.md
---
 Can you help me stop showing the "Model:" field in the agent metadata panel on the "Agents" tab of the
`sase ace` TUI (and stop adding the LLM provider emoji to the agent row) for non-agent child entries? For example, in
the `sase ace` snapshot below, the selected child entry is a bash workflow step, so it shouldn't show "CLAUDE(opus)" as
its model. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

### `sase ace` Snapshot

```
⭘                                                                                                     sase ace
  CLs  │  Agents  │  AXE                                                                                                                                                       Override CLAUDE(opus) 3h45m  ■ IDLE  ✉ 1
 14 Agents [4 running · 7 waiting · 1 unread · 2 done]   [view: file]   [group: by status (o)]   (auto-refresh in 2s)
┌─ (untagged) · 7 [R2 D2] ─────────────────────────────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running                 ││                                                                                                                              │
│  │  🤖 sase (RUNNING) ×4 @o0                                🏃‍♂️ 5m39s                 ││  AGENT DETAILS                                                                                                               │
│  │  ▎ oz ──────────────────────────────────────  1 agent · 1 running                 ││                                                                                                                              │
│  │  │  ▸ oz.cld ───────────────────────────────  1 agent · 1 running                 ││  Step: diff                                                                                                                  │
│  │  │  ≡ 🎭 sase (PLAN APPROVED) ×6 −3 @oz.cld.q            🏃‍♂️ 3m11s                 ││  Workflow: tmp_260512_102417                                                                                                 │
│  │  │    └─ 1/1.q 🎭 main (DONE) @oz.cld.q                                           ││  Model: CLAUDE(opus)                                                                                                         │
│  │  │    └─ 1/1.q 🎭 sase (RUNNING) @oz.cld.2               🏃‍♂️ 3m11s                 ││  VCS: GitHub                                                                                                                 │
│  │  │    └─ 1e/1 🐚 🎭 diff (DONE) @oz.cld.q ▼#gh                                    ││  Name: @oz.cld.q                                                                                                             │
│                                                                                      ││  Timestamps: BEGIN | 2026-05-12 10:24:13                                                                                     │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents                 ││              QUEST | 2026-05-12 10:33:09                                                                                     │
│  │  ▸ oy ─────────────────────────────────────────────────  2 agents                 ││                                                                                                                              │
│  │  🤖 sase (TALE DONE) ×8 @oy.r1.plan             10:35:55 · 10m20s                 ││  ──────────────────────────────────────────────────                                                                          │
│  │  🎭 sase (DONE) ×5 @oy                             10:09:17 · 48s                 ││                                                                                                                              │
│                                                                                      ││  BASH COMMAND                                                                                                                │
│                                                                                      ││                                                                                                                              │
│                                                                                      ││                                                                                                                              │
│                                                                                      ││  head_before="{{ checkout.head_before }}"                                                                                    │
│                                                                                      ││  if [ -z "$head_before" ]; then                                                                                              │
│                                                                                      ││    exit 0                                                                                                                    │
│                                                                                      ││  fi                                                                                                                          │
│                                                                                      ││  head_now=$(git rev-parse HEAD)                                                                                              │
│                                                                                      ││  diff_file=$(mktemp /tmp/sase-gh-XXXXXX.diff)                                                                                │
│                                                                                      ││  if [ "$head_now" != "$head_before" ]; then                                                                                  │
│                                                                                      ││    # Commits were made — show only the last commit's diff                                                                    │
│                                                                                      ││    git diff HEAD~1 HEAD > "$diff_file" 2>/dev/null                                                                           │
│                                                                                      ││    commit_msg=$(git log -1 --format='%s' HEAD)                                                                               │
│                                                                                      ││    echo "meta_commit_message=$commit_msg"                                                                                    │
│                                                                                      ││  else                                                                                                                        │
│                                                                                      ││    # No commits — show uncommitted changes                                                                                   │
│                                                                                      ││    git diff HEAD > "$diff_file" 2>/dev/null                                                                                  │
│                                                                                      ││    git ls-files --others --exclude-standard -z 2>/dev/null \                                                                 │
│                                                                                      ││      | while IFS= read -r -d '' f; do                                                                                        │
│                                                                                      ││          git diff --no-index /dev/null "$f" 2>/dev/null                                                                      │
│                                                                                      ││        done >> "$diff_file"                                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────────┘│  fi                                                                                                                          │
                                                                                        │  if [ -s "$diff_file" ]; then                                                                                                │
┌─ #chop · 3 [R1 W1 U1] ───────────────────────────────────────────────────────────────┐│    echo "diff_path=$diff_file"                                                                                               │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent · 1 running    ││  else                                                                                                                        │
│  │  🎭 sase (RUNNING) ×4 @refresh_docs.sase.3334a0a34211.update            🏃‍♂️ 15s    ││    rm -f "$diff_file"                                                                                                        │
│                                                                                      ││  fi                                                                                                                          │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agen    ││                                                                                                                              │
│  │  🎭 sase (WAITING) @refresh_docs.sase.3334a0a34211.polish                         ││                                                                                                                              │
│                                                                                      ││  ──────────────────────────────────────────────────                                                                          │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent    ││                                                                                                                              │
│  │  [agent] 🎭 refresh_docs (DONE) ×3 @o1                        10:36:58 · 📬 8s    ││  STEP OUTPUT                                                                                                                 │
└──────────────────────────────────────────────────────────────────────────────────────┘│                                                                                                                              │
                                                                                        │  No output available.                                                                                                        │
┌─ #sase-33 · 7 [R1 W6] ───────────────────────────────────────────────────────────────┐│                                                                                                                              │
│  ▶ Running ━━━━━━━━━━━━━━━━━━━  1 agent · 1 running                                  ││                                                                                                                              │
│  │  ⚡ 🎭 sase (RUNNING) ×4 ◆ @sase-33.1  🏃‍♂️ 14m31s                                  ││                                                                                                                              │
│                                                                                      ││                                                                                                                              │
│  ⏳ Waiting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents                                 ││                                                                                                                              │
│  │  ▸ sase-33 ───────────────────────────  6 agents                                  ││                                                                                                                              │
│  │  ⚡ 🎭 sase (WAITING) ◆ @sase-33                                                  ││                                                                                                                              │
│  │  ⚡ 🎭 sase (WAITING) ◆ @sase-33.6                                                ││                                                                                                                              │
│  │  ⚡ 🎭 sase (WAITING) ◆ @sase-33.5                                                ││                                                                                                                              │
│  │  ⚡ 🎭 sase (WAITING) ◆ @sase-33.4                                                ││                                                                                                                              │
│  │  ⚡ 🎭 sase (WAITING) ◆ @sase-33.3                                                ││                                                                                                                              │
│  │  ⚡ 🎭 sase (WAITING) ◆ @sase-33.2                                                ││                                                                                                                              │
└──────────────────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────── ○ files ───────────────────────────────────────────────────────────┘
 COPY c chat  n name  p prompt  s snap                                                                                                                                                                         RUNNING
```