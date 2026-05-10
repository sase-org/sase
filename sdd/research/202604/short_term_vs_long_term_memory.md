# Short-Term vs Long-Term Agent Memory: Research & Recommendation

## Problem Statement

All 7 memory files in `memory/` are `@`-imported from AGENTS.md, meaning they load into context at session start
regardless of task relevance. This is ~175 lines of instructions consumed on every message. Some files (e.g.,
`e2e_testing.md` at 56 lines) are only relevant for specific tasks but pay their token cost universally.

The question: how should we split memory into "always loaded" (short-term) vs "loaded on demand" (long-term)?

## Current State

```
CLAUDE.md → @AGENTS.md → @memory/architecture.md      (26 lines)
                        → @memory/build_and_run.md     (11 lines)
                        → @memory/code_conventions.md  (12 lines)
                        → @memory/e2e_testing.md       (56 lines)
                        → @memory/external_repos.md    (25 lines)
                        → @memory/generated_skills.md  (35 lines)
                        → @memory/workspaces.md        (10 lines)
                                                  TOTAL: 175 lines
```

Everything loads at session start. No conditional mechanism exists today.

## Prior Art

### Industry Patterns for Tiered Context

Every major AI coding tool has converged on a three-tier model:

| Tier         | What                                             | When                         | Tool examples                                                       |
| ------------ | ------------------------------------------------ | ---------------------------- | ------------------------------------------------------------------- |
| Always       | Project identity, critical rules, build commands | Session start                | CLAUDE.md, `.cursor/rules` with `alwaysApply: true`                 |
| Conditional  | Domain-specific guides, testing patterns         | On file access or invocation | `.claude/rules/*.md` with `paths:`, Cursor globs, Copilot `applyTo` |
| Never loaded | Full API specs, architecture docs                | Agent reads if needed        | Files the agent can grep/read                                       |

### ETH Zurich Study (Gloaguen et al., Feb 2026)

Tested 138 real-world tasks. Key findings relevant to this decision:

- Human-curated AGENTS.md files improve performance ~4% on average
- Architecture overviews can be removed without impact -- the agent infers these from code
- Information the agent can discover by reading the codebase adds overhead without improving performance
- LLM-generated context files _decrease_ performance by ~3%

### Claude Code's Built-in Mechanisms

1. **`@path` imports in CLAUDE.md/AGENTS.md** -- always loaded at session start
2. **`.claude/rules/*.md` with `paths:` frontmatter** -- loaded only when the agent reads a file matching the glob
3. **Skills (`.claude/skills/*/SKILL.md`)** -- description always in context (~250 chars), full content loaded only on
   invocation
4. **Auto-memory (`~/.claude/projects/*/memory/`)** -- MEMORY.md index (first 200 lines) always loaded, topic files read
   on demand

### Quantitative Context

| Metric                                                 | Source             |
| ------------------------------------------------------ | ------------------ |
| 50-82% token savings from moving procedures to skills  | Multiple sources   |
| 62% token reduction from tiered restructuring          | Medium (jpranav97) |
| 90% cache discount on repeated context reads           | Anthropic          |
| 100-150 instruction practical limit before degradation | Jaroslawicz et al. |
| Under 200 lines recommended for CLAUDE.md              | Anthropic          |

### What Survives Compaction

This is critical for choosing a mechanism. After `/compact` or auto-compaction:

- **Project-root CLAUDE.md**: Re-read from disk. Survives.
- **`@`-imported files**: Survive (loaded as part of CLAUDE.md chain).
- **`.claude/rules/*.md`**: Re-attached based on recently accessed files.
- **Skills**: Re-attached within 25K token budget, prioritized by most recently invoked.
- **Conversation-only instructions**: Lost.

Any long-term memory mechanism must survive compaction to be reliable.

## Candidate Approaches

### Approach A: Annotated Index in AGENTS.md (User's Proposal)

Split AGENTS.md into two sections -- `@`-prefixed short-term files that always load, and non-`@` long-term files listed
with descriptions that tell the agent when to read them.

```markdown
# SASE Agent Instructions

## Core (always loaded)

- @memory/build_and_run.md
- @memory/code_conventions.md
- @memory/workspaces.md

## Reference (read when relevant)

- memory/architecture.md — Project layout, glossary of ChangeSpec/xprompt terms. Read when working with unfamiliar sase
  concepts.
- memory/e2e_testing.md — AcePage testing DSL. Read when writing or modifying TUI tests.
- memory/external_repos.md — Chezmoi and plugin repo locations. Read when cross-repo work is needed.
- memory/generated_skills.md — Skill file generation, CLI/skill contract sync. Read when modifying skills or commit
  workflow.
```

**Strengths:**

- Simple. No new files, directories, or mechanisms required.
- Self-documenting. The descriptions double as a table of contents.
- Cross-runtime compatible. Works for Claude, Gemini, Codex -- any runtime that reads AGENTS.md.
- Survives compaction (the index is part of the always-loaded AGENTS.md chain).

**Weaknesses:**

- Relies on the agent _choosing_ to read the file. There's no enforcement -- the agent could ignore the description and
  skip a relevant file, or read all of them anyway (defeating the purpose).
- The index lines themselves consume tokens every session (~4-8 lines of descriptions).
- No automatic triggering based on file access patterns. The agent must self-select.

### Approach B: Path-Scoped `.claude/rules/*.md`

Move conditional content to `.claude/rules/` files with `paths:` frontmatter, leveraging Claude Code's built-in
conditional loading.

```yaml
# .claude/rules/testing.md
---
paths: ["tests/**/*.py", "src/sase/ace/testing/**"]
---
## TUI Testing with AcePage
[contents of current e2e_testing.md]
```

```yaml
# .claude/rules/skills.md
---
paths: ["src/sase/xprompts/skills/**", ".claude/skills/**"]
---
## Generated Skill Files
[contents of current generated_skills.md]
```

**Strengths:**

- Automatic triggering. Claude Code loads the rule when the agent touches a matching file -- no reliance on agent
  judgment.
- Built-in mechanism. No custom conventions to maintain.
- Survives compaction (re-attached based on recently accessed files).

**Weaknesses:**

- Claude Code-specific. Gemini and Codex don't support `.claude/rules/` with path scoping. Breaks the cross-runtime
  AGENTS.md contract.
- Some content doesn't map cleanly to file paths. `external_repos.md` is relevant based on _task intent_, not which
  files are being edited.
- Splits memory across two locations (`memory/` and `.claude/rules/`), complicating maintenance.
- Duplicates the pattern that `.claude/rules/` was designed for (project rules), repurposing it for reference docs.

### Approach C: Skills for On-Demand Content

Convert long-term memory files into skills that load only when explicitly invoked.

```
.claude/skills/e2e_testing/SKILL.md    — "TUI testing reference using AcePage DSL"
.claude/skills/external_repos/SKILL.md — "Cross-repo work with chezmoi and plugins"
.claude/skills/skill_generation/SKILL.md — "Skill file generation and CLI contract sync"
```

**Strengths:**

- Designed for this exact use case. Skills exist specifically to move on-demand content out of always-loaded context.
- Largest token savings. Only ~250 chars of description loaded per skill; full content loads on invocation.
- Survives compaction (re-attached within 25K budget).
- Skills can include dynamic content via `` !`command` `` syntax.

**Weaknesses:**

- Semantic mismatch. Skills represent _actions_ ("do X"), not _reference material_ ("here's context about X"). Using
  skills as a knowledge base feels like a misuse of the mechanism.
- Requires explicit invocation. The agent must decide to invoke `/e2e_testing` before writing tests. If it doesn't, the
  context is missing entirely -- worse than always loading it.
- Claude Code-specific. Skills don't exist in Gemini or Codex runtimes (though sase has its own skill mechanism).
- More files and directories to maintain.

### Approach D: Hybrid -- Annotated Index + Path-Scoped Rules

Combine Approach A (annotated index in AGENTS.md for cross-runtime compatibility) with Approach B (path-scoped rules for
Claude Code) where file-path triggering makes sense.

```markdown
# AGENTS.md

## Core (always loaded)

- @memory/build_and_run.md
- @memory/code_conventions.md
- @memory/workspaces.md

## Reference (read when relevant)

- memory/architecture.md — Project layout and glossary. Read when working with unfamiliar sase concepts.
- memory/e2e_testing.md — AcePage testing DSL. Read when writing or modifying TUI tests.
- memory/external_repos.md — Chezmoi and plugin repo locations. Read when cross-repo work is needed.
- memory/generated_skills.md — Skill file generation and CLI/skill sync. Read when modifying skills or commit workflow.
```

Plus, for Claude Code specifically:

```yaml
# .claude/rules/testing.md
---
paths: ["tests/**/*.py"]
---
@../../memory/e2e_testing.md
```

```yaml
# .claude/rules/skills.md
---
paths: ["src/sase/xprompts/skills/**"]
---
@../../memory/generated_skills.md
```

**Strengths:**

- Best of both worlds. Cross-runtime agents get the annotated index; Claude Code gets automatic path-based triggering.
- Content stays in one place (`memory/`). Rules files just `@`-import them.
- Redundant loading paths increase reliability -- if the agent doesn't self-select, the path rule catches it.

**Weaknesses:**

- Most complex to maintain. Two loading mechanisms for the same content.
- Risk of confusion about which mechanism is "primary."
- The `.claude/rules/` files are thin wrappers that exist only for triggering -- arguably over-engineered for the
  current memory file count.

## Analysis: Which Files Should Be Always-Loaded vs On-Demand?

Applying the ETH Zurich heuristic ("Would the agent get this wrong without the instruction?") and frequency analysis:

| File                  | Lines | Always needed? | Rationale                                                                                                                                                                |
| --------------------- | ----- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `build_and_run.md`    | 11    | **Yes**        | `just check` before terminating is a universal constraint. Every session.                                                                                                |
| `code_conventions.md` | 12    | **Yes**        | Absolute imports, Python 3.12+, CLI short options -- applies to all code changes.                                                                                        |
| `workspaces.md`       | 10    | **Yes**        | Ephemeral workspace context is critical to avoid running commands in wrong dir.                                                                                          |
| `architecture.md`     | 26    | **Borderline** | Glossary terms (ChangeSpec, xprompt) are referenced frequently. But the ETH study says architecture overviews can be dropped. The glossary section is the valuable part. |
| `e2e_testing.md`      | 56    | **No**         | Only relevant when writing TUI tests. 56 lines is the largest file.                                                                                                      |
| `external_repos.md`   | 25    | **No**         | Only relevant for cross-repo work (chezmoi, plugins).                                                                                                                    |
| `generated_skills.md` | 35    | **No**         | Only relevant when modifying skill files or commit workflow.                                                                                                             |

Potential savings: moving e2e_testing, external_repos, and generated_skills to on-demand saves ~116 lines (66% of
current total). Architecture is debatable -- the glossary is ~16 lines and frequently useful; the overview is ~10 lines
and arguably inferable.

## Recommendation: Approach A (Annotated Index)

**Use the annotated index approach in AGENTS.md.** It's the right choice for where this project is today, for these
reasons:

**1. Simplicity wins at this scale.** At 175 total lines across 7 files, we're already within Anthropic's recommended
200-line budget for CLAUDE.md. The optimization is worth doing, but doesn't justify building infrastructure. The
annotated index adds ~4-6 lines of descriptions while removing ~116 lines of always-loaded content -- a net savings of
~110 lines.

**2. Cross-runtime compatibility matters.** This project runs agents on Claude, Gemini, and Codex. Path-scoped rules and
skills are Claude Code-specific. The annotated index works everywhere because every runtime reads AGENTS.md and can
follow "read this file when X" instructions.

**3. Agent self-selection is reliable enough.** Modern models are good at following "read X when doing Y" instructions,
especially when the descriptions are specific. The risk of the agent skipping a relevant file is low, and the cost of
occasionally loading an irrelevant file is also low (these are 25-56 line files, not 500-line documents).

**4. Path-scoped rules can be added later.** If we find that agents consistently fail to self-select the right files, we
can layer on Approach D (the hybrid) without changing the AGENTS.md structure. Approach A is forward-compatible with
Approach B/D.

**5. Architecture.md deserves special treatment.** Split it: extract the glossary into a small `memory/glossary.md` that
stays `@`-imported (terms like ChangeSpec and xprompt come up constantly), and let the project overview section become
part of the long-term reference list. Alternatively, keep the whole file as always-loaded since it's only 26 lines --
the glossary alone justifies the cost.

### Proposed AGENTS.md Structure

```markdown
# Structured Agentic Software Engineering (SASE) - Agent Instructions

## Core Context

- @memory/architecture.md
- @memory/build_and_run.md
- @memory/code_conventions.md
- @memory/workspaces.md

## On-Demand Reference

The following files contain detailed reference material. Read them when working in their domain.

- [memory/e2e_testing.md](memory/e2e_testing.md) — AcePage testing DSL and patterns. Read when writing or modifying
  end-to-end TUI tests.
- [memory/external_repos.md](memory/external_repos.md) — Chezmoi repo and plugin repo (sase-github, retired Mercurial plugin,
  sase-telegram, sase-nvim) locations and workflows. Read when cross-repo work is needed.
- [memory/generated_skills.md](memory/generated_skills.md) — Skill file generation pipeline, CLI/skill contract
  synchronization, commit skills per runtime. Read when modifying skill source files or the commit workflow.
```

### Why Not the Other Approaches

- **Approach B (path-scoped rules):** Good mechanism, but Claude Code-specific. Not worth the cross-runtime
  incompatibility for 3 files.
- **Approach C (skills):** Semantic mismatch. These are reference docs, not workflows. Skills should do things, not
  passively provide context.
- **Approach D (hybrid):** Over-engineered for the current scale. Revisit if the memory directory grows to 15+ files or
  if we observe agents consistently failing to self-select.

## Sources

- [ETH Zurich: Evaluating AGENTS.md](https://arxiv.org/html/2602.11988v1) -- 138-task study on instruction file
  effectiveness
- [Anthropic: Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  -- "smallest set of high-signal tokens"
- [Anthropic: Extend Claude with Skills](https://code.claude.com/docs/en/skills) -- on-demand loading mechanism
- [Anthropic: How Claude Remembers Your Project](https://code.claude.com/docs/en/memory) -- memory architecture
- [Jaroslawicz et al.: Instruction Following Limits](https://arxiv.org/html/2507.11538v1) -- 100-150 instruction ceiling
- [Augment Code: How to Build AGENTS.md](https://www.augmentcode.com/guides/how-to-build-agents-md) -- tiered
  architecture guide
- [SmartScope: Token Optimization Guide 2026](https://smartscope.blog/en/generative-ai/claude/agents-md-token-optimization-guide-2026/)
  -- quantitative savings data
- Existing project research: `sdd/research/202604/agents_md_token_optimization.md`
