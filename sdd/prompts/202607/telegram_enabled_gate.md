---
plan: sdd/tales/202607/telegram_enabled_gate.md
---
 Can you help me start having the outbound and inbound chops of the sase-telegram plugin start checking for the existence of a ~/.sase/telegram_is_enabled file?

- If this file does not exist, these chops should exit quietly and quickly. Otherwise, they should continue to do what they do now.
- Also, move the telegram chop configuration from the sase_athena.yml file to the sase.yml file.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 