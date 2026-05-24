---
plan: sdd/tales/202605/agent_machine_commit_tags.md
---
 We currently have a concept of commit tags in sase. For example if the commit is associated with a SASE plan, then we add a `PLAN=<plan_file_path>` commit tag to the commit description. Can you help me start adding two new commit tags to every commit that sase makes? The new AGENT tag should have a value that corresponds with a sase agent name and the new MACHINE tag should have a value determined by the host name of the machine that the sase agent was running on. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
