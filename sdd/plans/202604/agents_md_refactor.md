---
create_time: 2026-04-12 15:28:42
status: done
prompt: sdd/prompts/202604/agents_md_refactor.md
---

# Plan: Extract AGENTS.md Sections into memory/ Directory

## Goal

Replace each `##` section in AGENTS.md with an `@`-prefixed file reference pointing to a new markdown file in a
`memory/` directory. This follows the same pattern that CLAUDE.md already uses to reference AGENTS.md (`@AGENTS.md`).

## Section-to-File Mapping

The title and intro paragraph (lines 1-3) stay in AGENTS.md. Each `##` section (with its `###` children) becomes one
file:

| Section                                                                                          | File                         |
| ------------------------------------------------------------------------------------------------ | ---------------------------- |
| Build & Run Commands                                                                             | `memory/build_and_run.md`    |
| Ephemeral `sase_<N>` Workspace Directories                                                       | `memory/workspaces.md`       |
| Architecture (+ Glossary)                                                                        | `memory/architecture.md`     |
| Generated Skill Files (+ CLI/Skill Contract, Commit Skills per Runtime, Plan Mode and Questions) | `memory/generated_skills.md` |
| Code Conventions and Gotchas                                                                     | `memory/code_conventions.md` |
| End-to-End Testing w/ `sase ace --agent`                                                         | `memory/e2e_testing.md`      |
| External Repos (+ Chezmoi Repo, Plugin Repos)                                                    | `memory/external_repos.md`   |

## Steps

1. Create the `memory/` directory.
2. Create the 7 markdown files, each containing the exact content of its section (preserving the `##` header as the
   top-level heading in each file).
3. Rewrite AGENTS.md to keep the title/intro and replace each section body with an `@memory/<file>.md` reference.
