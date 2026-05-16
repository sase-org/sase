---
plan: sdd/tales/202605/ace_tmux_option_1.md
---
  I want to add a new `--tmux` option to the `sase ace` command that allows agents to run the
`sase ace` command in a new tmux window named `sase_tmux_<N>`, where `<N>` is the first available (parallel agents might
use this at the same time) positive integer.

- This command should output the information required (tmux session and tmux window name?) for the agent to send
  emulated keypresses to the TUI.
- The agent should also be able to use this information to capture the contents of the tmux pane, which should be what
  the TUI is showing at the moment the capture was taken.

Can you help me implement this? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 