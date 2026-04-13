# Structured Agentic Software Engineering (SASE) - Agent Instructions

## Tier 1 (short-term) Memory

The following memory files contain core (always loaded) context:

- @memory/short/build_and_run.md
- @memory/short/glossary.md
- @memory/short/gotchas.md
- @memory/short/workspaces.md

## Tier 2 (dynamic) Memory

When your prompt matches keywords from dynamic memories, we append a `### DYNAMIC MEMORY` section at the bottom of your
prompt listing individual `.sase/memory/` file paths — one per matched memory:

```
### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md
- @.sase/memory/long-generated-skills.md
```

File names use a prefix that encodes the source tier: `long-` means the file originates from a long-term (tier 3) memory
source. If a `long-` prefixed file appears in your dynamic memory section, it contains the same content as the
corresponding tier 3 file below — you do NOT need to separately read the tier 3 file.

## Tier 3 (long-term) Memory

The below files contain detailed reference material. Read them when working in their domain.

- **memory/long/axe_agent_runner.md** - Orchestrator/lumberjack/runner hierarchy, agent phases, deferred workspaces,
  runner pool, zombie detection. Read when modifying the axe scheduler or agent runner.
- **memory/long/bead_system.md** - Bead model, dependency semantics, ready/close behavior, JSONL persistence, workspace
  merging. Read when modifying the bead/issue tracker.
- **memory/long/changespec_lifecycle.md** - Status transitions, suffix semantics, parent-child invariants, archive
  movement, mentor draft flags. Read when modifying ChangeSpec status logic or transitions.
- **memory/long/config.md** - Merge chain precedence, dual list strategies, schema maintenance, local config disabling,
  auto-scoping. Read when modifying config loading, adding config fields, or changing merge behavior.
- **memory/long/external_repos.md** - Chezmoi repo and plugin repo (sase-github, sase-google, sase-telegram, sase-nvim)
  locations and workflows. Read when cross-repo work is needed.
- **memory/long/generated_skills.md** - Skill file generation pipeline, CLI/skill contract synchronization, commit
  skills per runtime. Read when modifying skill source files or the commit workflow.
- **memory/long/tui_development.md** - AceApp architecture, reactive patterns, prefix-key modes, keymap resolution,
  modal lifecycle, widget messaging. Read when modifying the TUI.
- **memory/long/xprompt_system.md** - Loading priority, reference/directive syntax, workflow steps, Cartesian product,
  Jinja2 gotchas. Read when modifying xprompt processing or adding new directives.
