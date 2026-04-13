# Structured Agentic Software Engineering (SASE) - Agent Instructions

## Tier 1 (short-term) Memory

The following memory files contain core (always loaded) context:

- @memory/short/build_and_run.md
- @memory/short/glossary.md
- @memory/short/gotchas.md
- @memory/short/workspaces.md

## Tier 2 (dynamic) Memory

When your prompt matches keywords from memory-tagged xprompts, sase injects a `DYNAMIC MEMORY: @<path>` line at the
bottom of your prompt. The `@` reference resolves to the matched tier 3 content automatically. You do not need to take
any action -- the content is included in your context.

## Tier 3 (long-term) Memory

The below files contain detailed reference material. Read them when working in their domain.

- **memory/long/external_repos.md** - Chezmoi repo and plugin repo (sase-github, sase-google, sase-telegram, sase-nvim)
  locations and workflows. Read when cross-repo work is needed.
- **memory/long/generated_skills.md** - Skill file generation pipeline, CLI/skill contract synchronization, commit
  skills per runtime. Read when modifying skill source files or the commit workflow.
