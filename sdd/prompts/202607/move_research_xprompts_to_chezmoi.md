---
plan: sdd/tales/202607/move_research_xprompts_to_chezmoi.md
---
 Can you help me move the `#research_swarm` xprompt definition and the definitions of all other related (e.g. `#research`) xprompt definitions from the default xprompts provided by sase to  my chezmoi repo? Also, let's define two new custom model aliases: `@research` and `@research_assist`.

- `@research` should be configured to use "codex/gpt-5.5" and `@research_assist` should be configured to use "claude/opus".
- The `@research` model alias should be used by the first research agent and the 3rd (the consolidator) launched by the `#research_swarm` xprompt.
- The `@research_assist` model alias should be used for the 2nd research agent launched by the `#research_swarm` xprompt.
- The 4th agent launched by the `#research_swarm` xprompt should continue to hardcode the "codex/gpt-5.5" model.

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  