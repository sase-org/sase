---
plan: sdd/tales/202603/fix_normal_mode_freeze.md
---
Sometimes when I transfer a large prompt into the prompt input widget (e.g. using the `<ctrl+i>` keymap from the prompt
history panel), then go into NORMAL mode and try to use a motion (e.g. `gg` to go to the top of the prompt), the entire
TUI freezes. I need to kill the tmux pane and open a new one to restart `sase ace` in order to mitigate this when it
happens. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a
plan using your `/sase_plan` skill before making any file changes.
