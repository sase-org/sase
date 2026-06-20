---
plan: sdd/tales/202606/correlated_alt_keys_fanout.md
---
 The prompt in the ~/tmp/bad_fanout_prompt.md file shows a fanout prompt that launched 4 sase agents. This is not what I wanted. Any keyword argument that is repeated across multiple alternation calls (like `a=` is in the prompt in the ~/tmp/bad_fanout_prompt.md file) should have all of those values rendered in the same agent prompt. This restricts the number of agents that should be launched in the fanout. In this case, it means that only two agents should have been launched (one with a `.a` suffix in its name and the other with a `.b` suffix in its name).

Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 