---
create_time: 2026-07-07
updated_time: 2026-07-07
status: research
---

# Progressive Disclosure of xprompt Skill Descriptions

## Question

Every xprompt skill's description is injected into the context window of every agent, for every run. Can we support
"skill description progressive disclosure" — i.e. keep a tight, roughly constant bound on the per-agent context cost of
the skill catalog — so that the number of xprompt skills can grow without bound? If so, what solution shapes exist, and
which should we pursue?

**Short answer: yes, this is possible, there is strong prior art (Claude Code's own MCP ToolSearch deferral, plus a
2025–2026 research literature on skill retrieval at scale), and the recommended shape is a two-tier catalog: a small
"core" set of always-installed skills plus one generated `sase_skill_find` meta-skill that searches the rest of the
catalog on demand.** Details and alternatives below.

## 1. Where the cost comes from today (sase side)

Verified against the current tree (2026-07-07):

- Skill sources are ordinary xprompts with a `skill:` frontmatter key (`src/sase/xprompt/models.py:168-170`, schema
  `src/sase/config/sase.schema.json:1020-1036`). There are **14** today, all under `src/sase/xprompts/skills/`.
- The relationship is **1:1 opt-in**: each `skill: true` xprompt becomes exactly one generated `SKILL.md` per target
  provider (`src/sase/main/init_skills_handler.py` — `_load_skill_xprompts` line 184, `_render_skill_targets` line 343,
  `_build_output` line 237). All five registered providers (`agy`, `claude`, `codex`, `opencode`, `qwen`;
  `pyproject.toml:117-122`) receive the **same SKILL.md markdown/YAML format**, differing only in Jinja context
  (`llm_skill_template_context`) and deploy subpath (`llm_skill_deploy_subpath`).
- Deployment is **global and init-time only**: `sase skill init` writes to per-user dotfile dirs
  (`~/.claude/skills/<name>/SKILL.md`, `~/.codex/skills/...`, `~/.gemini/antigravity-cli/skills/...`, etc.). Nothing
  writes or filters skill files at launch time, and there is no per-agent allowlist, per-run subset, or lazy-loading
  mechanism anywhere in the code. Progressive disclosure is greenfield.
- Current descriptions run ~60–260 chars each. With harness framing, today's 14 skills cost each agent very roughly
  1–2k tokens per session — real but modest. The problem is **prospective**: the goal of "potentially infinite xprompt
  skills" makes linear growth in always-loaded descriptions the binding constraint.

Incidental finding while researching: `src/sase/xprompts/skills/sase_hg_commit.md` declares `skill: [gemini]`, but
"gemini" is no longer a registered provider entry point (the slot was inherited by `agy`, see
`src/sase/llm_provider/agy.py:322`), so that skill currently deploys **nowhere**. Worth a follow-up fix regardless of
this research.

## 2. What the runtimes already do (and where it stops helping)

All of our runtimes follow the [Agent Skills](https://agentskills.io) open standard, which bakes in progressive
disclosure **of skill bodies**:

- **Level 1 (always in context):** every skill's name + description.
- **Level 2 (on activation):** the full SKILL.md body.
- **Level 3 (on demand):** supporting files referenced from the body.

So bodies are already free until used. The residual, unavoidable-by-default cost is **Level 1 itself**, which grows
linearly with skill count. Per-runtime specifics:

### Claude Code

- All skill names are always listed; descriptions share a character budget defaulting to **1% of the model's context
  window** (~8,000 chars / ~2,000 tokens on a 200k model). On overflow, descriptions for the least-invoked skills are
  dropped first; each entry's `description` + `when_to_use` is independently capped at 1,536 chars. `/doctor` reports
  shortened/dropped skills.
- Knobs: `skillListingBudgetFraction` setting, `SLASH_COMMAND_TOOL_CHAR_BUDGET` env var (fixed char count),
  `skillListingMaxDescChars`, and per-skill `skillOverrides` in settings with four states — `"on"`, `"name-only"`,
  `"user-invocable-only"` (hidden from the model, still in the `/` menu), `"off"`. Frontmatter offers
  `disable-model-invocation: true` (user-invoked only) and `user-invocable: false`.
- Precedent that description-level deferral works: Claude Code defers **MCP tool definitions** behind a `ToolSearch`
  tool (on by default, `ENABLE_TOOL_SEARCH`); Anthropic reports ~85% token-overhead reduction from search-on-demand
  instead of upfront listing. Skills, however, have **no equivalent deferral today** — only the budget/truncation
  behavior above.

### Codex

- Initial skills list capped at **2% of the context window, or 8,000 chars** when unknown. Over budget it first
  shortens descriptions, then **omits skills entirely with a warning**. Full SKILL.md still loads on activation.
  Per-skill disable via `[[skills.config]]` in `~/.codex/config.toml`. Discovery from `.agents/skills` (repo),
  `$HOME/.agents/skills` (user), `/etc/codex/skills` (admin), plus built-ins.

### Gemini CLI (the `agy` lineage)

- Injects the name + description of **all enabled skills** into the system prompt at session start, with **no
  documented budget or truncation at all**. Skills activate via an `activate_skill` tool; `/skills enable|disable`
  manage a per-user/workspace enable list.

### The punchline

The runtimes bound the cost, but by **silently degrading trigger quality**: Claude truncates/drops descriptions, Codex
truncates/omits, Gemini just grows. Since implicit invocation depends entirely on description matching, "infinite
skills + runtime defaults" means skills silently stop firing — the worst failure mode, because nothing tells the agent
(or us) what it never saw. This matches the research literature: SkillRouter (arXiv 2504.06188 line of work) finds that
name+description-only selection is already inaccurate at scale and moves to retriever + reranker over **full skill
content**; GOSKILLS (arXiv 2605.06978) retrieves grouped skill contexts rather than flat lists. Retrieval-on-demand is
the emerging standard answer.

## 3. Solution options

### Option A — Lean on runtime-native knobs (status-quo hardening)

Tune `skillListingBudgetFraction` / `SLASH_COMMAND_TOOL_CHAR_BUDGET`, mark low-priority skills `"name-only"` via
`skillOverrides`, keep descriptions terse, watch `/doctor`.

- **Pros:** zero sase code; immediate.
- **Cons:** three different mechanisms on three runtimes (against the spirit of the uniform-runtimes rule); Gemini/agy
  has no budget mechanism; degradation is silent; does not scale to "infinite" — it just moves the cliff.

### Option B — Two-tier catalog + a single `sase_skill_find` meta-skill (ToolSearch pattern at the skill layer)

Split skills into a small **core tier** (always deployed as today) and an unbounded **catalog tier** (never deployed to
runtime skill dirs). Deploy exactly one additional generated skill, `sase_skill_find`, whose description says roughly
"Search sase's extended skill catalog whenever no listed skill covers the task; returns matching skills and how to use
them." The agent runs a CLI search — e.g. `sase skill search "<query>"` — which returns matching names, descriptions,
and rendered SKILL.md paths/content; the agent then reads the body and follows it (functionally identical to Level 2
activation, since our skill bodies are plain procedural markdown).

- Context cost becomes **O(core + 1)** regardless of catalog size — true progressive disclosure of descriptions.
- **Runtime-uniform by construction:** one CLI command + markdown files, identical for all five providers. No
  runtime-specific branches.
- Fits existing machinery: catalog membership is a frontmatter extension (e.g. `skill: catalog` alongside
  `true`/`false`/provider-list, or a separate `skill_tier:` key, schema at `sase.schema.json:982-1048`); search indexes
  the same xprompt loader output (`src/sase/xprompt/loader.py`); rendering reuses `_render_skill` /
  `_render_skill_targets`; the existing `sase skill use` audit log (prepended to bodies via `_build_output`,
  `init_skills_handler.py:226-259`) keeps working for catalog skills and doubles as usage telemetry for tiering
  decisions.
- **Cons / risks:**
  - *Discoverability inversion:* the model must think to search. The finder's description carries all the trigger
    weight, and recall for never-listed skills depends on the agent's diligence. Mitigations: a strong finder
    description; a one-line nudge in tier-1 memory (CLAUDE.md equivalents); keep anything referenced by hooks or
    lifecycle machinery (commit, plan, questions, memory_read) permanently core.
  - *One extra round trip* (search → read) before acting.
  - *Native frontmatter features are lost* for catalog skills — `allowed-tools`, `context: fork`, argument hints,
    runtime keybinding/autocomplete (`/name` won't complete for catalog skills). Today's xprompt skills use none of
    these, so this is acceptable now but is the main long-term trade-off to monitor.
  - Search quality: start with keyword/BM25 over name + description + body; the SkillRouter finding suggests indexing
    bodies, not just descriptions. Embeddings can be added later if keyword search misses.

### Option C — Per-run skill subset selection at launch time (sase-side routing)

sase controls every launch, so it can predict which skills a run needs (xprompt `#name` trigger matches, keyword or
embedding similarity against the prompt, or a cheap LLM classification) and materialize only that subset for the run.
The injection surfaces mostly already exist:

- **Codex:** already launches with a disposable shadow `CODEX_HOME` (`src/sase/llm_provider/codex.py:159-199`) that
  symlinks `~/.codex` wholesale; replacing the `skills/` symlink with a generated, filtered per-run directory is the
  natural hook.
- **agy:** home is redirectable via `SASE_AGY_HOME`/`ANTIGRAVITY_HOME`/`AGY_HOME`
  (`src/sase/llm_provider/_subprocess_agy.py:27-31`).
- **Claude:** launched today against the real home with no `--settings` or config-dir override
  (`src/sase/llm_provider/claude.py:223-234`). Options: `CLAUDE_CONFIG_DIR`, a `--settings` file, or writing a
  per-workspace `.claude/settings.local.json` containing a generated `skillOverrides` map (`"off"`/`"name-only"` for
  everything outside the predicted subset) into the ephemeral workspace clone.

- **Pros:** zero added agent effort; native invocation and all frontmatter features preserved; invisible to the model.
- **Cons:** launch-time prediction is strictly weaker than agent-driven retrieval at the moment of need — a
  misprediction leaves the agent without the skill *and without any way to discover it exists* (unless Option B's
  finder also ships, at which point B is doing the heavy lifting); tasks drift mid-run; per-provider plumbing diverges
  (three different injection mechanisms to build and maintain).

### Option D — Per-prompt hook injection (automatic retrieval)

Use the prompt-submit hook (all runtimes support hooks uniformly) to run catalog retrieval against each user prompt and
inject the top-k matching skill descriptions as context.

- **Pros:** adapts per prompt rather than per run; no agent effort.
- **Cons:** recurring token cost on every prompt; the injected text is not a native skill listing (the model still ends
  up reading SKILL.md files, i.e. this converges to Option B with automatic instead of agent-driven search, but paying
  retrieval cost even when unneeded); hook-event parity across all five providers needs verification for this specific
  event. Better as a later augmentation of B than a foundation.

### Option E — Hierarchical grouping (fewer, fatter skills)

Collapse related skills into per-domain umbrella skills (e.g. one VCS skill) whose bodies index sub-procedures in
sibling files — pushing the long tail from Level 1 into Level 3, GOSKILLS-style.

- **Pros:** works today with zero new machinery; native invocation preserved.
- **Cons:** sub-linear, not constant — doesn't reach "infinite"; umbrella descriptions blur the precise trigger
  phrases that make implicit invocation work; ongoing curation burden deciding what groups with what.

## 4. Recommended approach

**Adopt Option B as the backbone — a two-tier catalog with a single generated `sase_skill_find` meta-skill — and treat
A/C as cheap complements rather than alternatives.** It is the only option whose context cost is constant in catalog
size, it degrades loudly (a failed search returns "no match", vs. runtimes silently truncating descriptions), it
retrieves at the moment of need with the full task in view (strictly better information than launch-time routing), and
it is implementable as one CLI + markdown mechanism identical across all five providers — no runtime special cases.

Suggested phasing:

1. **Phase 1 — tiering + search + finder skill.**
   - Extend the xprompt `skill` frontmatter value space (or add `skill_tier:`) to distinguish `core` from `catalog`;
     update the schema and `_get_target_providers`/`_load_skill_xprompts` so `sase skill init` deploys only core-tier
     skills plus the new finder.
   - Add `sase skill search <query>` doing keyword/BM25 retrieval over name + description + **body** of catalog
     xprompts (rendered per the invoking provider), returning matches with descriptions and a way to fetch the full
     rendered body (path or `sase skill show <name>`).
   - Author `src/sase/xprompts/skills/sase_skill_find.md` through the normal generation pipeline. Keep
     hook/lifecycle-referenced skills (`sase_git_commit`, `sase_plan`, `sase_questions`, `sase_memory_read`, `sase_run`)
     permanently core.
   - *Rust core boundary:* catalog search/tiering is domain behavior any frontend (TUI, web, editor) would need to
     match, so plan the seam toward `sase-core` (`sase_core_rs`) even if the first keyword implementation lands in the
     Python CLI handler.
2. **Phase 2 — measurement + retrieval quality.** Use the existing `sase skill use` audit log to track which catalog
   skills get found/used and which searches return nothing; promote hot catalog skills to core (or auto-tier by usage);
   upgrade to embedding retrieval only if keyword search demonstrably misses.
3. **Phase 3 (optional) — per-run seeding.** Layer Option C on top for high-confidence cases (e.g. explicit `#name`
   references in the launch prompt → natively install those skills for the run), using the Codex shadow-home hook, agy
   home redirect, and a Claude `skillOverrides`/config-dir mechanism. The finder remains the safety net for everything
   unpredicted.

Independent of phases, apply the free Option A hygiene now: keep core-tier descriptions terse and front-loaded (Claude
caps each at 1,536 chars and Codex shortens first), and check Claude's `/doctor` skill diagnostics when the core set
grows.

## 5. Sources

Runtime documentation:

- [Claude Code — Extend Claude with skills](https://code.claude.com/docs/en/skills) (listing budget, `skillOverrides`,
  `skillListingBudgetFraction`, `SLASH_COMMAND_TOOL_CHAR_BUDGET`, `/doctor`)
- [Claude Platform — Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Anthropic Engineering — Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Claude Code — Scale to many tools with tool search](https://code.claude.com/docs/en/agent-sdk/tool-search) and
  [Claude Platform — Tool search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Codex — Agent Skills](https://developers.openai.com/codex/skills) (2%/8,000-char budget, shorten-then-omit,
  per-skill disable)
- [Gemini CLI — Agent Skills](https://geminicli.com/docs/cli/skills/) (all enabled descriptions injected, no budget)
- [Agent Skills open standard](https://agentskills.io)

Research literature on skill retrieval at scale:

- [SkillFlow: Scalable and Efficient Agent Skill Retrieval](https://arxiv.org/pdf/2504.06188) (BM25 + dense retrieval +
  rerank; description-only selection inaccurate at scale)
- [Group of Skills: Group-Structured Skill Retrieval for Agent Skill Libraries](https://arxiv.org/pdf/2605.06978)
- [SkillRAE: Agent Skill-Based Context Compilation for Retrieval-Augmented Execution](https://arxiv.org/abs/2605.10114)

Repo anchors (verified 2026-07-07; line numbers will drift): `src/sase/main/init_skills_handler.py`,
`src/sase/xprompt/models.py:151-170`, `src/sase/xprompt/loader_sources.py:160`,
`src/sase/llm_provider/{claude.py,codex.py,agy.py}`, `src/sase/config/sase.schema.json:982-1048`.
