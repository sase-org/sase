---
plan: sdd/tales/202605/memory_read_home_search.md
---
 When I run the `sase memory read <path_to_memory_file>` command, we should search both the local / project-specific memory/ directory (if one exists) and the ~/memory/ directory for `<path_to_memory_file>`, not just the project-specific directory (which is the current behavior). For example, the below command should work once you've made this fix. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
bryan in 🌐 athena in sase on  master is 📦 v0.1.0 via  v22.14.0 via 🐍 v3.10.18
❯ SASE_AGENT=none sam read long/obsidian.md -r "foobar"
sase memory read: memory file does not exist: long/obsidian.md
```