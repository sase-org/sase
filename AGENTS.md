# Structured Agentic Software Engineering (SASE) - Agent Instructions

## Tier 1 (short-term) Memory

The following memory files contain core (always loaded) context:

- @memory/short/build_and_run.md
- @memory/short/glossary.md
- @memory/short/gotchas.md
- @memory/short/workspaces.md

## Tier 2 (dynamic) Memory

When a user prompt matches keywords from dynamic memories, we append a `### DYNAMIC MEMORY` section at the bottom of
that prompt listing individual `.sase/memory/` file paths — one per matched memory:

```
### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (matched: `chezmoi`, `plugin`)
- @.sase/memory/long-generated-skills.md (matched: `commit skill`)
```

File names use a prefix that encodes the source tier: `long-` means the file originates from a long-term (tier 3) memory
source. If a `long-` prefixed file appears in your dynamic memory section, it contains the same content as the
corresponding tier 3 file below — you do NOT need to separately read the tier 3 file.

## Tier 3 (long-term) Memory

The below files contain detailed reference material. Read them when working in their domain.

**`memory/long/external_repos.md`**  
Chezmoi repo and plugin repo (`sase-github`, `sase-google`, `sase-telegram`, `sase-nvim`) locations and workflows.  
_Read when cross-repo work is needed._

**`memory/long/generated_skills.md`**  
Skill file generation pipeline, CLI/skill contract synchronization, commit skills per runtime.  
_Read when modifying skill source files or the commit workflow._
