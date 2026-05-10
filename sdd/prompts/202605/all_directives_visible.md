---
plan: sdd/tales/202605/all_directives_visible.md
---
 Can you help me make sure that all directives are visible when the user presses `<ctrl+t>` and their cursor is to the right of a "%" character? It looks like we are not showing some of them (I think they are just getting cut off). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### `sase ace` snapshot
```
 ⭘                                                                                                     sase ace
  CLs  │  Agents (2 x1)  │  AXE (9)                                                                                                                                                         CODEX(gpt-5.5)  ■ IDLE  ✉ 1
 3 Agents [2 running · 1 done]   [view: collapsed]   [group: by status (o)]   (auto-refresh in 5s)
┌─ (untagged) · 3 [R2 D1] ──────────────────────────────────┐┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ▶ Running ━━━━━━━━━━━━━━━━━━━━━  2 agents · 2 running    ││                                                                                                                                                         │
│  │  sase (RUNNING) ×6 @d6.code.r1             🏃‍♂️ 2m56s    ││  AGENT DETAILS                                                                                                                                          │
│  │  sase (TALE APPROVED) ×6 @d7.plan          🏃‍♂️ 6m18s    ││                                                                                                                                                         │
│                                                           ││  Project: sase                                                                                                                                          │
│  ✓ Done ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1 agent    ││  Workspace: #100                                                                                                                                        │
│  │  sase (PLAN DONE) ×6 @d6.plan      22:26:17 · 5m42s    ││  Embedded Workflows: gh(gh_ref=sase)                                                                                                                    │
│                                                           ││  Model: CODEX(gpt-5.5)                                                                                                                                  │
│                                                           ││  VCS: GitHub                                                                                                                                            │
│                                                           ││  PID: 3384869                                                                                                                                           │
│                                                           ││  Name: @d7.plan                                                                                                                                     ▆▆  │
│                                                           ││  Timestamps: BEGIN | 2026-05-09 22:28:05                                                                                                                │
│                                                           ││              PLAN  | 2026-05-09 22:30:11                                                                                                                │
│                                                           ││              CODE  | 2026-05-09 22:30:49                                                                                                                │
│                                                           ││  DELTAS:                                                                                                                                                │
│                                                           ││    ~ src/sase/llm_provider/config.py  +49 ~1                                                                                                            │
│                                                           ││    ~ src/sase/llm_provider/registry.py  +3 ~4                                                                                                           │
│                                                           ││    ~ src/sase/xprompt/_directive_alt.py  +2 ~4                                                                                                          │
│                                                           ││    ~ tests/test_llm_provider_providers.py  +56                                                                                                          │
│                                                           ││  ARTIFACTS:                                                                                                                                             │
│                                                           ││    • sdd/tales/202605/other_model_alias.md                                                                                                              │
│                                                           ││                                                                                                                                                         │
│                                                           ││  ──────────────────────────────────────────────────                                                                                                     │
│                                                           ││                                                                                                                                                         │
│                                                           ││  AGENT XPROMPT                                                                                                                                          │
│                                                           ││                                                                                                                                                         │
│                                                           ││  #gh:sase Can you help me add support for configuring an "other" model in sase.yml (update mine to configure opus in my chezmoi repo) that can be       │
│                                                           ││  used via `%model:other`? This is meant to be an alternative / secondary model. Using `%m:other` instead of the model name explicitly allows for        │
│                                                           ││  more generic multi-agent xprompts that will run a different model for each step depending on what default/other models you have configured at the      │
│                                                           ││  time of agent launch. #plan                                                                                                                            │
│                                                           ││                                                                                                                                                     ▆▆  │
│                                                           ││  ──────────────────────────────────────────────────                                                                                                     │
│                                                           ││                                                                                                                                                         │
│                                                           ││  AGENT PROMPT                                                                                                                                           │
│                                                           ││                                                                                                                                                         │
│                                                           ││                                                                                                                                                         │
│                                                           ││  Can you help me add support for configuring an "other" model in sase.yml (update mine to configure opus in my chezmoi                                  │
│                                                           ││  repo) that can be used via `%model:other`? This is meant to be an alternative / secondary model. Using `%m:other`                                      │
│                                                           ││  instead of the model name explicitly allows for more generic multi-agent xprompts that will run a different model for                                  │
│                                                           ││  each step depending on what default/other models you have configured at the time of agent launch. Think this through                                   │
│                                                           ││  thoroughly and create a plan using your `/sase_plan` skill before making any file changes.                                                             │
│                                                           ││                                                                                                                                                         │
│                                                           ││  ### DYNAMIC MEMORY                                                                                                                                     │
│                                                           ││                                                                                                                                                         │
│                                                           ││  - @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)                                                                │
│                                                           ││                                                                                                                                                         │
└───────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────────── ● files [2/3]  ○ thinking ───────────────────────────────────────────────────────────────┘
┌─ Prompt ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ┌─ directives ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ ▸ %alt  (variants)  split a prompt into text/model variants                                                                                                                                                      │ │
│ │   %approve  flag  alias %a  run autonomously without plan approval prompts                                                                                                                                       │ │
│ │   %edit  flag  alias %e  return editor text to the prompt bar before launch                                                                                                                                      │ │
│ │   %epic  flag  plan first and auto-approve the plan as an epic                                                                                                                                                   │ │
│ │   %hide  flag  alias %h  hide the agent from the default Agents tab                                                                                                                                              │ │
│ │   %model  :model or (models)  alias %m  choose one or more provider/model targets                                                                                                                                │ │
│ │   %name  :agent  alias %n  assign, auto-generate, or force-reuse an agent name                                                                                                                                   │ │
│ │   %plan  flag  alias %p  create a plan first, then wait for approval                                                                                                                                             │ │
│ └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                                                                                                                                      │
│  #gh:sase %                                                                                                                                                                                                          │
│                                                                                                                                                                                                                      │
│                                                                                                                                                                                                                      │
│                                                                                                                                                                                                                      │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────  send   normal  [^C] cancel ─┘

```

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)