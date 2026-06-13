---
plan: sdd/tales/202606/worker_models.md
---
 We recently migrated the `worker_model` config field to a `worker_models` field that maps primary models/providers to the worker models that should be used when those primary models/providers are used. Can you help me improve this feature?

- If a provider/model that is configured via this field is used in a user prompt (e.g. by including the `%model` directive explicitly in their prompt) and that agent creates a sase plan, then the coder agent that implements that plan (assuming the user approves it) should have its model chosen based on this config field (i.e. use whatever is configured).
- Make sure taht this new field has strong support in the TUI (e.g. it should have good support in the model override panel).
- Also, make sure that primary model overrides effect which worker models we use (i.e. if the primary model/provider changes via a user override, the worker model should change with it).

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
