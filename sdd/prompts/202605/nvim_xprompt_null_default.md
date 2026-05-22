---
plan: sdd/tales/202605/nvim_xprompt_null_default.md
---
 #fork:a1y This worked, but I'm seeing a different error now (see below). Can you help me diagnose the root
cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


```
E5108: Lua: ...an/.local/share/nvim/lazy/sase-nvim/lua/sase/xprompt.lua:178: attempt to concatenate field 'default' (a userdata value)
stack traceback:
        ...an/.local/share/nvim/lazy/sase-nvim/lua/sase/xprompt.lua:178: in function 'input_detail_label'
        ...an/.local/share/nvim/lazy/sase-nvim/lua/sase/xprompt.lua:342: in function '_preview_lines'
        ...e/nvim/lazy/sase-nvim/lua/telescope/_extensions/sase.lua:27: in function 'define_preview'
        ...scope.nvim/lua/telescope/previewers/buffer_previewer.lua:438: in function 'preview'
        ...share/nvim/lazy/telescope.nvim/lua/telescope/pickers.lua:1209: in function 'refresh_previewer'
        ...share/nvim/lazy/telescope.nvim/lua/telescope/pickers.lua:1150: in function 'set_selection'
        ...share/nvim/lazy/telescope.nvim/lua/telescope/pickers.lua:910: in function 'move_selection'
        ...e/nvim/lazy/telescope.nvim/lua/telescope/actions/set.lua:35: in function 'run_replace_or_original'
        ...re/nvim/lazy/telescope.nvim/lua/telescope/actions/mt.lua:65: in function 'shift_selection'
        .../nvim/lazy/telescope.nvim/lua/telescope/actions/init.lua:83: in function 'run_replace_or_original'
        ...re/nvim/lazy/telescope.nvim/lua/telescope/actions/mt.lua:65: in function 'key_func'
        ...hare/nvim/lazy/telescope.nvim/lua/telescope/mappings.lua:290: in function <...hare/nvim/lazy/telescope.nvim/lua/telescope/mappings.lua:289>
Press ENTER or type command to continue
```

Sibling repos for this project are available in workspace-matched directories:
- core: /home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_10
- github: /home/bryan/.local/state/sase/workspaces/sase-org/sase-github/sase-github_10
- telegram: /home/bryan/.local/state/sase/workspaces/sase-org/sase-telegram/sase-telegram_10
- nvim: /home/bryan/.local/state/sase/workspaces/sase-org/sase-nvim/sase-nvim_10
- chezmoi: /home/bryan/.local/share/chezmoi
When editing a sibling repo, use its workspace-matched directory, not the primary checkout.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`, `sase-github`, `sase-telegram`, `sase-nvim`, `sase-core`)