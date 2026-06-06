---
plan: sdd/tales/202606/home_provider_shim_refs.md
---
 It doesn't seem like claude sase agents ever read the `~/memory/long/obsidian.md` file (which they should be
told to do by the ~/CLAUDE.md file). See the sase agent named "33" for an example of an agent that should have probably
read that file, but didn't. I'm pretty sure this is because the `@AGENTS.md` references in the home directory need to be
absolute paths. Can you help me fix this issue? I think it is the `sase amd init` command that creates these files so
that is what you will need to update. Use `@~/AGENTS.md` instead of `@/home/bryan/AGENTS.md` so this works on other
machines. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
