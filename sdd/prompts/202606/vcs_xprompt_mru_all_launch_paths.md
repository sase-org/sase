---
plan: sdd/tales/202606/vcs_xprompt_mru_all_launch_paths.md
---
 When we use the `<ctrl+p>` keymap in the prompt input widget to pre-fill the widget with the VCS xprompt workflow that was used previously, and then type in a prompt and then submit that prompt, VCS xprompt workflow history does not seem to be updated properly. We should now consider the VCS xprompt workflow that the user just submitted in the most recent prompt to be the most recent one that was used (i.e. the next time the user uses the `<ctrl+p>` keymap in the prompt input widget for the first time, that VCS xprompt workflow should be shown first). Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 