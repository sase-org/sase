---
plan: sdd/tales/202605/qwen_global_commit_stop_hook.md
---
 Why didn't the sase_stop_commit_hook seem to trigger for the "ru" sase agent even though it made changes? Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

### Additional Requirements

- The sase_commit_stop_hook is meant to be configured globally. We handle this for other providers by putting it in the settings.json file associated with that provider in my chezmoi repo.