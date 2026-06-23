---
plan: sdd/epics/202606/xprompt_effort_levels.md
---
 I want to be able to specify an effort level (ex: "xhigh") when I specify a model / LLM provider in xprompts. Can you help me implement this? See the below bullets for extra requirements. See the the sdd/research/202606/xprompt_thinking_level_consolidated.md file, which contains related research performed by another agent, for context and inspiration.

- Make sure that the effort level is displayed in a uniform way across all proiders in the agent metadata panel on the "Agents" tab of the `sase ace` TUI (e.g. as a suffix on the "Model:" field?).
- A new config field should be added that user's can configure (in their ~/.config/sase/sase.yml file, for example, but all configuration files supported by sase should be supported) that allows them to configure the default effort level that they want.
- Edit my sase.yml and agent CLI settings files in my chezmoi repo so I no longer set default effort levels on a per-provider level, but do so through sase's default effort level (see the above bullet).
- We should add both a new `%effort:<effort>` directive and add support for a new `@<effort>` suffix on model / LLM providers (e.g. input arguments to the `%model` directive). More information on these can be found in the sdd/research/202606/xprompt_thinking_level_consolidated.md file.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `agy` /
`codex` / `qwen` / `opencode` command). Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.

 