---
plan: sdd/tales/202605/nvim_telescope_preview_newlines.md
---
 Can you help me fix this error I am seeing in nvim? I think it likely has something to do with the recent
commit we made to the sase-nvim repo. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


```
E5108: Lua: ...e/nvim/lazy/sase-nvim/lua/telescope/_extensions/sase.lua:28: 'replacement string' item contains newlines
stack traceback:
        [C]: in function 'nvim_buf_set_lines'
        ...e/nvim/lazy/sase-nvim/lua/telescope/_extensions/sase.lua:28: in function 'define_preview'
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