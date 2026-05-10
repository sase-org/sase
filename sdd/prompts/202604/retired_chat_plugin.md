---
plan: sdd/epics/202604/retired_chat_plugin.md
---
 I want to create a new ../retired chat plugin repo (I've already created it with an empty README.md file--give that file good contents after this repo is implemented) that provides a chop integration with Google Chat that offers all of
the same functionality as our sase-telegram chop integration. See the @~/tmp/gchat_cli_skill.md file for instructions on how to use a CLI tool to read and write from Google Chat. Google Chat supports markdown, but might not have all of
the features that Telegram does, so we might need to, for example, use numbered text options instead of buttons. Can you help me implement this integration? This is a large piece of work that should be split into phases. I'll let you
decide how many phases to create, but keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` / `codex` command). Think this through thoroughly and create a plan using your
`/sase_plan` skill before making any file changes.



### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `sase-telegram`)
