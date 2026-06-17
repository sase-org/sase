# Structured Agentic Software Engineering (SASE) - Agent Instructions

IMPORTANT: You should not modify any of these memory files without approval from the user.

## Tier 1 (short-term) Memory

The following memory files contain core (always loaded) context:

- @memory/build_and_run.md
- @memory/glossary.md
- @memory/gotchas.md
- @memory/rust_core_backend_boundary.md
- @memory/sase.md

## Tier 2 (long-term) Memory

The below files contain detailed reference material. When working in their domain, you MUST use your `/sase_memory_read`
skill to review their contents. Do not read canonical memory files directly.

**`memory/cli_rules.md`**  
Read anytime new CLI subcommands or options are added.

**`memory/generated_skills.md`**  
Skill file generation pipeline, CLI/skill contract synchronization, commit skills per runtime.

**`memory/tui_perf.md`**  
Read before changing anything that affects TUI performance or responsiveness (navigation, refresh, rendering, startup).
