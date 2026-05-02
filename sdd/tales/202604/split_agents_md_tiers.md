---
create_time: 2026-04-12 18:37:16
status: done
prompt: sdd/prompts/202604/split_agents_md_tiers.md
---

# Split AGENTS.md into Always-Loaded and On-Demand Tiers

STATUS: proposed

## Context

Research in `sdd/research/202604/short_term_vs_long_term_memory.md` recommends Approach A (Annotated Index) for splitting memory
files into always-loaded vs on-demand tiers. Since that research was written, commit 4b607fe2 already deleted
`memory/e2e_testing.md` and trimmed several files. The current AGENTS.md has 6 `@`-imported files — all always-loaded.

The goal is to move task-specific reference files out of always-loaded context while keeping them discoverable via
descriptions in AGENTS.md. This saves ~60 lines of token budget on sessions that don't need cross-repo or skill
generation context.

## Current State

All 6 files are `@`-imported (always loaded):

| File                  | Lines | Always needed?                              |
| --------------------- | ----- | ------------------------------------------- |
| `glossary.md`         | 14    | Yes — terms referenced constantly           |
| `build_and_run.md`    | 11    | Yes — `just check` constraint is universal  |
| `code_conventions.md` | 9     | Yes — applies to all code changes           |
| `workspaces.md`       | 10    | Yes — workspace isolation is critical       |
| `external_repos.md`   | 25    | No — only for cross-repo work               |
| `generated_skills.md` | 35    | No — only for skill/commit workflow changes |

## Plan

### Phase 1: Restructure AGENTS.md

Edit AGENTS.md to split into two sections:

1. **Core Context** — `@`-prefixed, always loaded: glossary.md, build_and_run.md, code_conventions.md, workspaces.md
2. **On-Demand Reference** — listed without `@`, with one-line descriptions telling agents when to read them:
   external_repos.md, generated_skills.md

The on-demand entries use markdown link syntax (`[memory/file.md](memory/file.md)`) for clickability, followed by a dash
and a description of when the agent should read the file.

### Phase 2: Verify

Run `just check` to confirm no lint/test regressions from the AGENTS.md edit.

## Token Savings

- Removed from always-loaded: external_repos.md (25 lines) + generated_skills.md (35 lines) = ~60 lines
- Added to AGENTS.md: ~6 lines (section headers + 2 description lines)
- Net savings: ~54 lines per session that doesn't need these files
