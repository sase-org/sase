---
plan: sdd/tales/202606/worker_models_mapping.md
---
 Can you help me change the way the `worker_model` config works?

- We should rename this field to `worker_models`.
- It should start accepting a mapping of model / provider names to model names.
- These key-value pairs are pairs of (primary, worker) models. In other words, we should index this map using the
  primary model / provider name to figure out what model we should use for the worker model.
- Provider names can be used instead of model names (ex: `claude` instead of `claude/opus`) to indicate the default that
  should be used for that provider. These provider entries should only be used if the current model uses that provider
  but is not explicitly configured via the `worker_models` field.
- Make sure to update the sase.yml file in my chezmoi repo to use the following value for this field:
  ```
  claude: codex/gpt-5.5
  codex: claude/opus
  ```

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
