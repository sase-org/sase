---
plan: sdd/tales/202605/memory_list_home_context.md
---
 Can you help me improve the `sase memory list` command (current output is shown below)?

- We should be counting lines in the AGENTS.md file too!
- We should also be showing the ~/AGENTS.md file and ~/memory/ files in this output since these files should be loaded
  into every agent's context (regardless of what directory the agent is launched from).

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### CURRENT OUTPUT

```
❯ sase memory
╭─────────────────────────────────────────────────────────────────────────────────────────── SASE Memory Context ───────────────────────────────────────────────────────────────────────────────────────────╮
│ Directory              /home/bryan/projects/github/sase-org/sase                                                                                                                                          │
│ Project                sase                                                                                                                                                                               │
│ Instruction roots      5 (CLAUDE.md, GEMINI.md, QWEN.md, OPENCODE.md, AGENTS.md)                                                                                                                          │
│ Loaded files           5                                                                                                                                                                                  │
│ Referenced-only files  3                                                                                                                                                                                  │
│ Available files        1                                                                                                                                                                                  │
│ Missing references     0                                                                                                                                                                                  │
│ Loaded lines           121                                                                                                                                                                                │
│ Approx loaded tokens   1570                                                                                                                                                                               │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭──────────────────────────────────────────────────────────────────────────────────────────── Memory Files (9) ─────────────────────────────────────────────────────────────────────────────────────────────╮
│ Status      Path                                        Lines  Approx tokens  Reference detail                                                                                                            │
│ loaded      memory/short/build_and_run.md                  36            466  AGENTS.md -> @memory/short/build_and_run.md                                                                                 │
│ loaded      memory/short/glossary.md                       38            477  AGENTS.md -> @memory/short/glossary.md                                                                                      │
│ loaded      memory/short/gotchas.md                        10            143  AGENTS.md -> @memory/short/gotchas.md                                                                                       │
│ loaded      memory/short/rust_core_backend_boundary.md     12            178  AGENTS.md -> @memory/short/rust_core_backend_boundary.md                                                                    │
│ loaded      memory/short/sase.md                           25            306  AGENTS.md -> @memory/short/sase.md                                                                                          │
│ referenced  memory/long/generated_skills.md                50            481  AGENTS.md -> memory/long/generated_skills.md (+1 refs)                                                                      │
│ referenced  memory/long/llm_provider_hooks.md              14            214  AGENTS.md -> memory/long/llm_provider_hooks.md                                                                              │
│ referenced  memory/long/tui_jk_baseline.md                 64            844  AGENTS.md -> memory/long/tui_jk_baseline.md                                                                                 │
│ available   memory/long/llm_provider_hooks/codex.md       523           5016  present on disk, not reached                                                                                                │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────────────────────────────────────────────── Notes ──────────────────────────────────────────────────────────────────────────────────────────────────╮
│ @path loads file contents into agent context.                                                                                                                                                             │
│ Plain memory/... paths are visible references only.                                                                                                                                                       │
│ Dynamic memory under .sase/memory is prompt-dependent: keyword matches are generated during agent launch, not by this list.                                                                               │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```