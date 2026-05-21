---
plan: sdd/tales/202605/prompt_input_lag_tier2_reconcile.md
---
 When I am typing in the prompt input widget, sometimes there is an ~3s lag that seems to occur randomly. I suspect that we are likely loading agents from disk during this time, which blocks the UI thread. I thought we made this MUCH faster recently though (see the sase-3s epic bead), so I don't understand why the lag is so long. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
