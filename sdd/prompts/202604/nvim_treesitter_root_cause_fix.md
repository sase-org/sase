---
plan: sdd/plans/202604/nvim_treesitter_root_cause_fix.md
---
#resume:p That still didn't fix it. Can you help me diagnose the root cause of this issue and (finally) fix it? Think
this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
Decoration provider "start" (ns=nvim.treesitter.highlighter):
Lua: ...l/share/nvim/runtime/lua/vim/treesitter/languagetree.lua:215: .../bbugyi/.local/share/nvim/runtime/lua/vim/treesitter.lua:196: attempt to call method 'range' (a nil value)
stack traceback:
        [C]: in function 'f'
        ...l/share/nvim/runtime/lua/vim/treesitter/languagetree.lua:215: in function 'tcall'
        ...l/share/nvim/runtime/lua/vim/treesitter/languagetree.lua:596: in function 'parse'
        ...al/share/nvim/runtime/lua/vim/treesitter/highlighter.lua:580: in function <...al/share/nvim/runtime/lua/vim/treesitter/highlighter.lua:557>
```
