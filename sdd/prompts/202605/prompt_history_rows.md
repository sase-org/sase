---
plan: sdd/tales/202605/prompt_history_rows.md
---
 Can you help me make the entries in the prompt history panel MUCH easier to reason about by fitting them all on one line and adding some more (compact) data to that line (ex: the datetime that
prompt was run)? I've pasted a snapshot of what the prompt history panel looks like currently below for reference. I want you to lead the design on this one. Just make sure it looks beautiful! Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (5 x4)  │  AXE (8)                                                                                                                                      Override CODEX(gpt-5.5) 29h12m  ■ IDLE  ✉ 23+4
 Agents: 2/9   [view: file]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 9 ──────────────────────────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││                                                                                                                                             │
│  │  sase (RUNNING) ×4 @th                                       7s    ││  AGENT DETAILS                                                                                                                              │
│  │  ⚡ sase (RUNNING) ×4 ◆ sase-1r.7 @sase-1r.7              1m46s    ││                                                                                                                                         ▄▄  │
│          █▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█          │
│  ⏳ Waiti█                                                                                                                                                                                                █          │
│  │  ▸ sas█  Select Prompt from History                                                                                                                                                                    █          │
│  │  ⚡ sa█                                                                                                                                                                                                █          │
│  │  ⚡ sa█  * = sase  ~ = home                                                                                                                                                                            █          │
│  │  ⚡ sa█                                                                                                                                                                                                █          │
│          █  ▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎  █          │
│  ✓ Done ━█  ▊  Type to filter...                                                                                                                                                                       ▎  █          │
│  │  sase █  ▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎  █          │
│  │  sase █                                                                                                                                                                                                █          │
│  │  ▸ sas█  History                                                                                       Preview                                                                                         █          │
│  │  ⚡ sa█  ┌───────────────────────────────────────────────────────────────────────────────────────────┐ ┌────────────────────────────────────────────────────────────────────────────────────────────┐  █          │
│  │  ⚡ sa█  │ * sase                                      | #gh:sase I continue to have problems        │ │ #gh:sase I continue to have problems where multiple `sase axe` processes wind up running,  │  █          │
│          █  │ whe...                                                                                    │ │ which causes a variety of problems. Can you help me make it virtually impossible for that  │  █──────────┘
│          █  │ * sase                                      | #gh:sase Something happened that broke      │ │ to ever happen? #plan                                                                      │  █──────────┐
│          █  │ p...                                                                                      │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase Why are we using ".coder"          │ │ --- Metadata ---                                                                           │  █          │
│          █  │ inste...                                                                                  │ │ Branch: sase                                                                               │  █          │
│          █  │ * sase                                      | #gh:sase Why are we using ".coder"          │ │ Workspace: home                                                                            │  █          │
│          █  │ inste...                                                                                  │ │ Created: 260501_145610                                                                     │  █          │
│          █  │ * sase                                      | #gh:sase Why are we using ".coder"          │ │ Last Used: 260501_145611                                                                   │  █          │
│          █  │ inste...                                                                                  │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase Why are we using ".coder"          │ │                                                                                            │  █          │
│          █  │ inste...                                                                                  │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase Why are we using ".coder"          │ │                                                                                            │  █          │
│          █  │ inste...                                                                                  │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase Something happened that broke      │ │                                                                                            │  █          │
│          █  │ p...                                                                                      │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase This `fix_just` chop just ran      │ │                                                                                            │  █          │
│          █  │ w...                                                                                      │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase %name:sase-1r.8 %approve           │ │                                                                                            │  █          │
│          █  │ %w:sas...                                                                                 │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase %name:sase-1r.7 %approve           │ │                                                                                            │  █          │
│          █  │ %w:sas...                                                                                 │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase %name:sase-1r.6 %approve           │ │                                                                                            │  █          │
│          █  │ %w:260...                                                                                 │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase %name:sase-1r.6 %approve           │ │                                                                                            │  █          │
│          █  │ %w:sas...                                                                                 │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase #gh:sase %name:sase-1r.5           │ │                                                                                            │  █          │
│          █  │ %appro...                                                                                 │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase %name:sase-1r.5 %approve           │ │                                                                                            │  █          │
│          █  │ #bd/wo...                                                                                 │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase This `fix_just` chop just ran      │ │                                                                                            │  █          │
│          █  │ w...                                                                                      │ │                                                                                            │  █          │
│          █  │ * sase                                      | %w:1h #gh:sase %name:sase-1r.5 %approve     │ │                                                                                            │  █          │
│          █  │ ...                                                                                       │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase This `fix_just` chop just ran      │ │                                                                                            │  █          │
│          █  │ w...                                                                                      │ │                                                                                            │  █          │
│          █  │ * sase                                      | #gh:sase Can you help me start removing     │ │                                                                                            │  █          │
│          █  └───────────────────────────────────────────────────────────────────────────────────────────┘ └────────────────────────────────────────────────────────────────────────────────────────────┘  █          │
│          █                                                                                                                                                                                                █          │
│          █                                            j/k ↑/↓ ^n/^p: navigate • Enter: submit • ^g: edit • ^i: load • ^x: cancelled • ^y: copy • Esc/q: cancel                                            █          │
│          █                                                                                                                                                                                                █          │
│          █▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█          │
│                                                                       ││                                                                                                                                             │
│                                                                       ││    ▾ 48 more lines below                                                                                                                    │
│                                                                       ││                                                                                                                                             │
└───────────────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────── Lines 1-36 of 84 ──────────────────────────────────────────────────────────────┘
┌─ Prompt ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  #gh:sase .                                                                                                                                                                                                          │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────  cancel ─┘

```