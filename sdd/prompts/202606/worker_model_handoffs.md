---
plan: sdd/tales/202606/worker_model_handoffs.md
---
 Can you help me improve the recently added worker_model functionality?

- The worker model should be used to implement sase plans (i.e. as the modl for "coder" agents). Make sure to update both the provider and model (see the recently implemented, but obsolete, ~/.sase/plans/202606/plan_handoff_provider_drop.md plan file for context).
- I believe that the worker model is already used for phase agents that implement a phase bead (which is a child of an epic bead). This is correct but make sure that if the phase bead has a model set, that model is prioritized.
- The agent that creates the Epic thread and phase threads and launches the Epic should also use the worker model.
- Make sure that the agent that lands the epic lead and closes the epic lead continues to use the current default/overridden default model (NOT the worker model).

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
