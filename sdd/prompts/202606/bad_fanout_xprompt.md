---
plan: sdd/tales/202606/bad_fanout_xprompt.md
---
 The ~/tmp/bad_fanout_prompt.md file contains a prompt that should have launched 8 agents (4 opus, 4 GPT-5.5),
but it only launched 4 (all opus). I think it might be something wrong with how the `m_opus_codex` xprompt (which is
defined in the sase.yml file in my chezmoi repo) is / isn't expanded before determining the fanout shape. Can you help
me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 