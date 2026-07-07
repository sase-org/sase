---
plan: sdd/tales/202607/chat_update_builtin_engine.md
---
 I believe that the sase-telegram repo uses the /update command to do something very similar to what we do from the updates tab on the admin center panel in sase's TUI, but I think we strangely require the user to configure a custom script that performs this update for us. This should be unnecessary since we have all of the mechanics already built and being used by the TUI. Can you help me consolidate these two update paths by having the sase-telegram /update command use the same logic that the TUI currently uses? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 