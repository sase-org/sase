---
plan: sdd/tales/202607/agy_model_alias_removal.md
---
 Can you help me get rid of the hacky `agy` and `agy_pro` model aliases that are currently configured in the sase.yml file in my chezmoi repo?

- I'm pretty sure we did this because the model names have spaces and parentheses in them but we should be able to support both of these by quoting the argument used with the `%model` directive.
- For example, we should be able to use `%m("agy/Gemini 3.5 Flash (High)")` instead of needing to use `%m(@#agy)`.
- I'm not sure if xprompt directives or xprompts support quoted arguments like this currently but if not, you should add such support.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 