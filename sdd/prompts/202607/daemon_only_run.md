---
plan: sdd/tales/202607/daemon_only_run.md
---
 The `sase run` command currently has a `-d|--daemon` option that launches the agent exactly as if it had been launched from the TUI. In practice, this has been the only way that I use the `sase run` command for a while now (running in the foreground where the user needs to keep that shell window open runs against sase's philosophy). Can you help me remove the `-d|--daemon` option and make that the default and only way that sase agents are launched via the `sase run` command? Make sure to remove all references to this old way of using the `sase run` command and make sure that we remove any logic from the codebase that is no longer needed.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 