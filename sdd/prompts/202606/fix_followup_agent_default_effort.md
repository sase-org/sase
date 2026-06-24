---
plan: sdd/tales/202606/fix_followup_agent_default_effort.md
---
 It doesn't look like coder agents (the model that is run for these is cofigured via the `worker_models` config field) are using the "xhigh" effort level even though that is what I have set for the `default_effort` field in the sase.yml file in my chezmoi repo. Every sase agent that doesn't specify a model explicitly, via the `%effort:<effort>` directive or the `@<effort>` input suffix used with the `%model` directive, should use the effort level specified by the `default_effort` config field. Can you help me diagnose the root cause of this issue and fix it?

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 