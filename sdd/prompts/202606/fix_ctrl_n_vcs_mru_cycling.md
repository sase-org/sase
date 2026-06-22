---
plan: sdd/tales/202606/fix_ctrl_n_vcs_mru_cycling.md
---
 We recently changed the way the `<ctrl+n>` keymap works in the prompt input widget. Namely, we made it so it
always clears the VCS xprompt workflow instead of cycling to the next VCS xprompt workflow in our list of recently used
VCS xprompt workflows. This is not correct. The `<ctrl+n>` keymap should only clear the VCS xprompt workflow in the
prompt when there is no next VCS xprompt workflow to select (e.g. the user hasn't pressed `<ctrl+p>` yet). Also, let's
add support back to the `<ctrl+n>` keymap for cycling to the end of the list if there is no VCS xprompt workflow in the
current prompt. As a consequence, for example, if the user presses `<ctrl+p><ctrl+p><ctrl+n><ctrl+n>`, the prompt should
wind up with the same VCS xprompt workflow as it started with (if any).

Can you help me make the necessary changes to fix this keymap? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
