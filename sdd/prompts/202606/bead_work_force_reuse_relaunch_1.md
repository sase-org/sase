---
plan: sdd/tales/202606/bead_work_force_reuse_relaunch_1.md
---
 When I just tried to re-launch the sase-4q epic using the `sase bead work sase-4q -y` command (see the output below) I got an error because those agent names exist. Can you help me make it so we always use the special `!` agent name suffix so we always overwrite the old phase/land agents, if any exist)? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

```
> sase bead work sase-4q -y
Epic sase-4q is already ready; retrying remaining non-closed phases.
Epic sase-4q — Prompt Stash - stash & restore prompt-input drafts: 4 phase agent(s) in 4 wave(s) plus 1 land agent (sase-4q).
  Wave 0: sase-4q.1 → sase-4q.1
  Wave 1: sase-4q.2 → sase-4q.2
  Wave 2: sase-4q.3 → sase-4q.3
  Wave 3: sase-4q.4 → sase-4q.4
  Land waits on: sase-4q.1, sase-4q.2, sase-4q.3, sase-4q.4
Error: agent launch failed for epic sase-4q: Agent name 'sase-4q' is taken. Try 'sase-4q1'.
```