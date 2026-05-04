---
plan: sdd/tales/202605/require_bang_for_multi_agent_xprompts.md
---
 We currently invoke standalone xprompt workflows via the `#!` prefix. We also support multi-prompts (using a
line containing just 3 dashes to separate the agent prompts) in `*.md` xprompt definitions. These too should be
considered standalong xprompt workflows since we cannot embed them in a prompt with other context (e.g. other xprompts
or user text). Can you help me make sure these need to be preficed with `#!` (instead of just `#`) too? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
