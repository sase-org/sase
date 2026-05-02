---
plan: sdd/epics/202604/llm_provider_plugins.md
---
  Can you help me migrate sase's LLM provider functionality to plugins (e.g. using pluggy)? The jetski provider should be migrated to the sase-google repo. All other providers should be defined as built-in plugins. This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but
keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` /
`codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (matched: `sase-google`)