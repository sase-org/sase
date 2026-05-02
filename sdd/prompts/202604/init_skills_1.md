---
plan: sdd/epics/202604/init_skills_1.md
---
Can you help me add support for managing all agent skills related to sase using a new `sase init-skills` command?

- We should add support for a new `skill: true` xprompt field that marks an xprompt as one that should be converted into
  an agent skill.
- `skill: true` indicates that the skill should be created for ALL agents supported by sase (gemini, claude, and codex).
  Alternatively, the `skill` field should also accept a list of agent provider names (gemini, claude, or codex). For
  example, `skill: [claude]` indicates that we should create an agent skill from this xprompt when `sase init-skills` is
  run for Claude Code only.
- We should also migrate all sase skills in my chezmoi repo to this repo and then run `sase init-skills` to
  re-initialize them in my chezmoi repo (we should only create skills in a chezmoi repo when the `use_chezmoi: true`
  sase.yml field is set).
- If any of the agent skill files that the `sase init-skills` command wants to create already exist, we should prompt
  the user y/n/d (yess/no/diff) to confirm, unless the `-f|--force` option is used (in which case we should just
  overwrite them all.

See the research performed by a previous agent in the @sdd/research/202604/init_skills_command.md file for inspiration. This is a
large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep in mind
that each phase will be completed by a distinct agent instance (i.e. a distinct `claude` / `gemini` / `codex` command).
Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
