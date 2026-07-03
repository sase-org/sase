---
plan: sdd/tales/202607/model_alias_descriptions.md
---
 Can you help me start showing a good description for the currently highlighted model alias that describes what that model alias is used for somewhere on the "Models" panel?

- Custom model aliases (defined by users in sase's config but not used internally by sase) should be expected to have a new `description` field (that doesn't need to be configured for builtin model aliases).
- We should probably improve the config schema so this `description` field is required for custom model aliases but not for builtin ones (might require we define them using separate config fields).
- Make sure to update the sase.yml file in my chezmoi repo appropriately.
- I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! 

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 