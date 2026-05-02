---
plan: sdd/plans/202604/dynamic_memory_prompt_injection.md
---
#resume:q Actually, I just decided that it would be better if we just construct the dynamic memory and put it in a temp
file (I think we have an environment variable that we use to decide what the temp directory should be) that gets
referenced in a line that automatically gets injected into the agent prompt at the bottom that looks like this: "DYNAMIC
MEMORY: <tmp_memory_file_path>" (the file path should be prefixed with @). This means we can remove the special TUI
support that we added since the dynamic memory file will be visible in the prompt. The tier 2 section in the AGENTS.md
file should just explain how these lines are injected, so agents aren't confused by them. Can you help me make these
changes? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
