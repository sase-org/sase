---
plan: sdd/tales/202605/init_memory_workspace_section.md
---
 The memory/short/sase.md file that is generated via the `sase init memory` command should include a section describing sase's ephemeral workspace directories. Can you help me make the necessary changes so the `sase init memory` command generates the contents in the ~/tmp/sase.md file instead of what is currently in the memory/short/sase.md file? The `project` variable (which I used jinja2-like syntax for) should be replaced with the name of the project that the memory/short/sase.md file was generated in (we shouldn't include this section for ~/memory/short/sase.md). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
