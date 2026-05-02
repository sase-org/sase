---
plan: sdd/plans/202604/codex_config_churn.md
---
 Can you help me figure out why codex keeps leaving these lines (see the command output below for context) and stop it from doing so in the future? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 
```
❯ chez update -v -a
Already up to date.
.codex/config.toml has changed since chezmoi last wrote it [diff,overwrite,all-overwrite,skip,quit]? a
diff --git a/.codex/config.toml b/.codex/config.toml
old mode 100600
new mode 100664
index 876ad6323a49b07985eb48564e911fd73e8f2308..cd45a299e4806ddff2463c87350541aa3be726c6
--- a/.codex/config.toml
+++ b/.codex/config.toml
@@ -4,21 +4,3 @@ personality = "pragmatic"

 [projects."/home/bryan"]
 trust_level = "trusted"
-
-[projects."/home/bryan/projects/github/sase-org/sase_101"]
-trust_level = "trusted"
-
-[projects."/home/bryan/projects/github/sase-org/sase_102"]
-trust_level = "trusted"
-
-[projects."/home/bryan/projects/github/sase-org/sase"]
-trust_level = "trusted"
-
-[projects."/home/bryan/projects/github/sase-org/sase_104"]
-trust_level = "trusted"
-
-[projects."/home/bryan/projects/github/sase-org/sase_100"]
-trust_level = "trusted"
-
-[tui.model_availability_nux]
-"gpt-5.5" = 1
```

### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`)