---
plan: sdd/tales/202605/kill_edit_force_name_reuse.md
---
 When I kill an agnt using the `,x` keymap on the agents tab, we currently populate the prompt input widget with that agent's prompt after killing it. Can you help me make it so, if that prompt contained a `%n` / `%name` directive, that we prepend `!` to the directive's argument value to specify that we want to overwrite the previous agent's name? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
