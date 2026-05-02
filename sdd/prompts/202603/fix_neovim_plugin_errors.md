---
plan: sdd/tales/202603/fix_neovim_plugin_errors.md
---
Can you help me fix my Neovim (my neovim config lives in my chezmoi repo)? I keep getting errors when I use it: Think
this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
/home/bryan/.config/nvim/lua/plugins/treesitter.lua:25: module 'nvim-treesitter.configs' not found:
        no field package.preload['nvim-treesitter.configs']
        cache_loader: module 'nvim-treesitter.configs' not found
        cache_loader_lib: module 'nvim-treesitter.configs' not found
        no file '/usr/local/share/lua/5.1/nvim-treesitter/configs.lua'
        no file './nvim-treesitter/configs.lua'
        no file '/usr/local/share/lua/5.1/nvim-treesitter/configs/init.lua'
        no file '/usr/local/lib/lua/5.1/nvim-treesitter/configs.lua'
        no file '/usr/local/lib/lua/5.1/nvim-treesitter/configs/init.lua'
        no file '/usr/share/lua/5.1/nvim-treesitter/configs.lua'
        no file '/usr/share/lua/5.1/nvim-treesitter/configs/init.lua'
        no file '/home/bryan/.luarocks/share/lua/5.1/nvim-treesitter/configs.lua'
        no file '/home/bryan/.luarocks/share/lua/5.1/nvim-treesitter/configs/init.lua'
        no file './nvim-treesitter/configs.so'
        no file '/usr/local/lib/lua/5.1/nvim-treesitter/configs.so'
        no file '/usr/lib/x86_64-linux-gnu/lua/5.1/nvim-treesitter/configs.so'
        no file '/usr/lib/lua/5.1/nvim-treesitter/configs.so'
        no file '/usr/local/lib/lua/5.1/loadall.so'
        no file '/home/bryan/.luarocks/lib/lua/5.1/nvim-treesitter/configs.so'
        no file './nvim-treesitter.so'
        no file '/usr/local/lib/lua/5.1/nvim-treesitter.so'
        no file '/usr/lib/x86_64-linux-gnu/lua/5.1/nvim-treesitter.so'
        no file '/usr/lib/lua/5.1/nvim-treesitter.so'
        no file '/usr/local/lib/lua/5.1/loadall.so'
        no file '/home/bryan/.luarocks/lib/lua/5.1/nvim-treesitter.so'

# stacktrace:
  - ~/.config/nvim/lua/plugins/treesitter.lua:25 _in_ **init**
  - ~/.config/nvim/lua/config/lazy_plugins.lua:31
  - ~/.config/nvim/init.lua:50
2026-03-30T11:57:11 lazy.nvim  ERROR Failed to run `init` for **telescope-dap.nvim**

/home/bryan/.config/nvim/lua/plugins/dap/init.lua:133: module 'telescope' not found:
        no field package.preload['telescope']
        cache_loader: module 'telescope' not found
        cache_loader_lib: module 'telescope' not found
        no file '/usr/local/share/lua/5.1/telescope.lua'
        no file './telescope.lua'
        no file '/usr/local/share/lua/5.1/telescope/init.lua'
        no file '/usr/local/lib/lua/5.1/telescope.lua'
        no file '/usr/local/lib/lua/5.1/telescope/init.lua'
        no file '/usr/share/lua/5.1/telescope.lua'
        no file '/usr/share/lua/5.1/telescope/init.lua'
        no file '/home/bryan/.luarocks/share/lua/5.1/telescope.lua'
        no file '/home/bryan/.luarocks/share/lua/5.1/telescope/init.lua'
        no file './telescope.so'
        no file '/usr/local/lib/lua/5.1/telescope.so'
        no file '/usr/lib/x86_64-linux-gnu/lua/5.1/telescope.so'
        no file '/usr/lib/lua/5.1/telescope.so'
        no file '/usr/local/lib/lua/5.1/loadall.so'
        no file '/home/bryan/.luarocks/lib/lua/5.1/telescope.so'

# stacktrace:
  - ~/.config/nvim/lua/plugins/dap/init.lua:133 _in_ **init**
  - ~/.config/nvim/lua/config/lazy_plugins.lua:31
  - ~/.config/nvim/init.lua:50
2026-03-30T11:57:11 lazy.nvim  ERROR Failed to run `config` for overseer.nvim

...local/share/nvim/lazy/overseer.nvim/lua/overseer/dap.lua:4: module 'overseer.vscode' not found:
        no field package.preload['overseer.vscode']
        cache_loader: module 'overseer.vscode' not found
        cache_loader_lib: module 'overseer.vscode' not found
        no file '/usr/local/share/lua/5.1/overseer/vscode.lua'
        no file './overseer/vscode.lua'
        no file '/usr/local/share/lua/5.1/overseer/vscode/init.lua'
        no file '/usr/local/lib/lua/5.1/overseer/vscode.lua'
        no file '/usr/local/lib/lua/5.1/overseer/vscode/init.lua'
        no file '/usr/share/lua/5.1/overseer/vscode.lua'
        no file '/usr/share/lua/5.1/overseer/vscode/init.lua'
        no file '/home/bryan/.luarocks/share/lua/5.1/overseer/vscode.lua'
        no file '/home/bryan/.luarocks/share/lua/5.1/overseer/vscode/init.lua'
        no file './overseer/vscode.so'
        no file '/usr/local/lib/lua/5.1/overseer/vscode.so'
        no file '/usr/lib/x86_64-linux-gnu/lua/5.1/overseer/vscode.so'
        no file '/usr/lib/lua/5.1/overseer/vscode.so'
        no file '/usr/local/lib/lua/5.1/loadall.so'
        no file '/home/bryan/.luarocks/lib/lua/5.1/overseer/vscode.so'
        no file './overseer.so'
        no file '/usr/local/lib/lua/5.1/overseer.so'

```
