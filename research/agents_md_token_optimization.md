# Reducing Token Usage in AGENTS.md / CLAUDE.md Files

Research on best practices for keeping agent instruction files lean and effective.

## 1. What Makes Instructions Effective vs. Wasteful

### Effective

- **Non-obvious information the agent can't infer from code.** Toolchain specifics (e.g., "run `just check` before
  terminating"), workflow expectations, non-standard constraints. Litmus test: "Would the agent get this wrong without
  the instruction?" If not, delete it.
- **Dense, directive language.** Replace "It is highly recommended that you use..." with "Use X." As instruction count
  rises, compliance degrades uniformly -- every word competes for attention.
- **Patterns, not procedures.** Encode conventions, constraints, rules. Multi-step procedures belong in skills that load
  on demand.
- **Concrete examples over abstract rules.** A single canonical example communicates more than paragraphs of
  description.

### Wasteful

- **Code style guidelines.** If ruff/ESLint/prettier handles it, don't duplicate in instructions.
- **Self-evident information.** Telling the model how to write Python, use git, or follow REST conventions.
- **Stale instructions.** Outdated references to completed migrations or deprecated features are "actively harmful, not
  neutral" -- they can cause the agent to follow obsolete procedures.
- **Inline code snippets.** They become outdated quickly. Use `file:line` references instead, or let the agent read the
  actual code.

## 2. Common Anti-Patterns

**a. The "employee handbook" approach.** Treating CLAUDE.md as comprehensive documentation rather than concise
instructions. Target under 200 lines (Anthropic official recommendation) or under 300 lines (HumanLayer).

**b. Architectural overviews without actionable specifics.** Multiple sources report that removing an "Architecture"
section while keeping only commands, constraints, and non-standard patterns produces the same agent behavior at lower
token cost. The agent can read your code to understand architecture; what it can't infer are your workflow expectations.

**c. Task-specific hotfixes appended over time.** Instructions for edge cases that apply to one specific task get
ignored when working on unrelated tasks, but they still consume tokens every session.

**d. Instruction overload.** Research from Jaroslawicz et al. (2025) tested instruction-following from 10 to 500
instructions:

- Claude Sonnet shows **linear decay** -- steady, predictable performance decline as instructions increase
- Most models hit a practical limit around **100-150 instructions** where accuracy remains reasonable
- Claude Code's system prompt already contains ~50 instructions, leaving a budget of roughly 50-100 more before
  significant degradation
- Models exhibit a **primacy effect** -- instructions at the beginning get more attention than those in the middle
- Beyond ~250 instructions, models "abandon rather than approximate" -- they drop instructions entirely

**e. Redundant instructions across files.** One study found 178 different lines between a project's CLAUDE.md and
AGENTS.md, creating inconsistencies. If you maintain multiple files, keep them synchronized or centralize.

**f. Always-on context for sometimes-needed content.** Database schema instructions when working on the frontend.
Deployment procedures when writing unit tests. Every token loaded at session start is paid on every subsequent message.

## 3. Optimization Strategies

### a. Tiered context architecture

The most consistently recommended approach:

| Tier               | Content                                                        | Loading               |
| ------------------ | -------------------------------------------------------------- | --------------------- |
| Tier 1 (Always)    | Project identity, critical rules, build/test commands          | Session start         |
| Tier 2 (On-demand) | Component guides, API refs, testing patterns, deployment steps | Skills when invoked   |
| Tier 3 (Never)     | Full API specs, changelogs, generated docs                     | Agent reads if needed |

### b. Move procedures to skills

Anthropic's official docs: "If [CLAUDE.md] contains detailed instructions for specific workflows (like PR reviews or
database migrations), those tokens are present even when you're doing unrelated work. Skills load on-demand only when
invoked." Reported savings: 50-82% token reduction.

### c. Prompt caching optimization

Place static, unchanging content at the top of your instructions. Cache read tokens cost 0.1x the base input price (90%
discount). Content that changes often should go at the end. Structure instructions so the cache prefix is maximized.

### d. Conditional/scoped loading

Cursor supports glob-based rule scoping (rules activate only for matching file patterns). Claude Code skills support a
`paths` frontmatter field for the same purpose. Only load Python conventions when editing `.py` files.

### e. Compress language

Replace explanatory prose with terse directives. "It is highly recommended that you always use absolute imports rather
than relative imports because..." becomes "Use absolute imports: `from sase.foo import bar`".

### f. Offload preprocessing to hooks

Instead of Claude reading a 10,000-line log to find errors, a hook can grep for `ERROR` and return only matching lines.

### g. Dynamic context injection in skills

The `` !`command` `` syntax in skill files runs shell commands before sending content to Claude, so current data (git
status, branch name) is injected at invocation time rather than maintained as stale static text.

### h. Sub-agent delegation

Delegate verbose operations (test runs, log analysis) to sub-agents that return condensed summaries rather than keeping
full output in the main context.

## 4. What Belongs Where

### Keep in AGENTS.md / CLAUDE.md (static, always-on)

- Project identity (1-2 sentences)
- Build/run/test commands (the "quick start")
- Critical universal constraints (e.g., "ALWAYS run `just check` before terminating")
- Non-obvious conventions the agent would get wrong without guidance
- Pointers to docs the agent can read on demand

### Move to skills (on-demand)

- Multi-step workflows (commit procedures, deployment steps, PR review checklists)
- Domain-specific reference material (API conventions, database schema)
- Testing patterns and templates

### Let the agent discover dynamically

- Architecture (it can read code and directory structure)
- Code style details (it can read existing code and match patterns; linters enforce)
- Git history and current branch state (`git log`, `git status`)
- Dependency versions (`pyproject.toml`, `package.json`)
- File contents and function signatures

### Move to hooks (preprocessing)

- Filtering large outputs before Claude sees them
- Injecting current environment state at session start
- Enforcing rules deterministically (post-commit checks, formatting)

**Guiding principle from Anthropic:** "Context is a finite resource -- find the smallest set of high-signal tokens that
maximize the likelihood of the desired outcome."

## 5. Measurement and Iteration

- **The "Reset Test."** Temporarily remove your instruction files. If agent performance is unchanged, you have
  instruction overload.
- **Weekly audits.** Delete rules the agent follows without explicit guidance. Add rules only when you notice the same
  mistake repeated 3+ times.
- **Cost tracking via `/cost`.** Compare per-session token consumption before/after restructuring.
- **Proxy-based observation.** Insert a logging proxy between Claude Code and the API using `ANTHROPIC_BASE_URL` to see
  exactly what context Claude receives.
- **Automated drift detection.** Tools like Packmind's `context-evaluator` compare documentation coverage against actual
  codebase patterns.

## Quantitative Findings

| Metric                                                 | Source             |
| ------------------------------------------------------ | ------------------ |
| 50-82% token savings from moving procedures to skills  | Multiple sources   |
| 62% token reduction from tiered restructuring          | Medium (jpranav97) |
| 90% cache discount on repeated context                 | Anthropic          |
| 100-150 instruction practical limit before degradation | Jaroslawicz et al. |
| Under 200 lines recommended for CLAUDE.md              | Anthropic          |

## Sources

- [HumanLayer: Writing a Good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Anthropic: Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Manage Costs Effectively (Claude Code docs)](https://code.claude.com/docs/en/costs)
- [Anthropic: Extend Claude with Skills (Claude Code docs)](https://code.claude.com/docs/en/skills)
- [Anthropic: Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Jaroslawicz et al.: How Many Instructions Can LLMs Follow at Once?](https://arxiv.org/html/2507.11538v1)
- [Arize AI: Optimizing Coding Agent Rules](https://arize.com/blog/optimizing-coding-agent-rules-claude-md-agents-md-clinerules-cursor-rules-for-improved-accuracy/)
- [Medium (jpranav97): Stop Wasting Tokens: Optimize Claude Code Context by 60%](https://medium.com/@jpranav97/stop-wasting-tokens-how-to-optimize-claude-code-context-by-60-bfad6fd477e5)
- [Medium (Peakvance): Guide to Cursor Rules -- The Token Tax](https://medium.com/@peakvance/guide-to-cursor-rules-engineering-context-speed-and-the-token-tax-16c0560a686a)
- [Packmind: Writing AI Coding Agent Context Files](https://packmind.com/evaluate-context-ai-coding-agent/)
- [CodeWithSeb: Claude Code Skills -- Token Savings Architecture](https://www.codewithseb.com/blog/claude-code-skills-reusable-ai-workflows-guide)
- [Builder.io: Improve Your AI Code Output with AGENTS.md](https://www.builder.io/blog/agents-md)
