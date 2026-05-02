---
plan: sdd/tales/202604/dynamic_memory_2.md
---
Can you help me implement a solution for memory/dynamic.md (see the @sdd/research/202604/dynamic_memory_implementation.md file for
relevant research--let's go with something like the recommended solution)? git should ignore this file. It should be
deleted before starting a sase agent and possibly re-created before agent creation (if an xprompt matches some of the
text in the prompt). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any
file changes.

### Additional Requirements

- We should maintain the tier 3 memory files. Be creative and think of some xprompts you can create that use this memory
  system, but you shouldn't migrate the tier 3 files over two to tier 2 (dynamic memory) xprompts.
