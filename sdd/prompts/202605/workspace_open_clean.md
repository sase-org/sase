---
plan: sdd/tales/202605/workspace_open_clean.md
---
 Can you help me change the behavior of the `sase workspace open` command? Namely:

- Let's add a new `-c|--clean` option that prepares the workspace for use.
- This will be used by agents to prepare sibling workspace directories in the future, so we need to perform all of the steps we normally do to prepare a workspace directory for use by a new agent (e.g. stash any uncommitted changes, checkout master, sync the repo, etc...).

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


Sibling repos for this project are available in workspace-matched directories:
- core: /home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_10
- github: /home/bryan/.local/state/sase/workspaces/sase-org/sase-github/sase-github_10
- telegram: /home/bryan/.local/state/sase/workspaces/sase-org/sase-telegram/sase-telegram_10
- nvim: /home/bryan/.local/state/sase/workspaces/sase-org/sase-nvim/sase-nvim_10
- chezmoi: /home/bryan/.local/share/chezmoi
When editing a sibling repo, use its workspace-matched directory, not the primary checkout.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`, `sase-github`, `sase-telegram`, `sase-nvim`, `sase-core`)