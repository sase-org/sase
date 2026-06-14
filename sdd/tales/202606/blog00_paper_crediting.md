---
create_time: 2026-06-14 15:27:11
status: done
prompt: sdd/prompts/202606/blog00_paper_crediting.md
---
# Plan: Strengthen the SASE-paper crediting in blog post `[00]`

## Context

I reviewed the rewritten launch post `docs/blog/posts/why-coding-agents-need-orchestration.md` (titled
`[00] The Missing Operating Layer for Coding Agents`) against the original 30-point requirements list. The post is in
very good shape. I verified the objective claims and they hold up:

- **XPrompt directives** — all 12 listed (`%model/%m`, `%name/%n`, `%wait/%w`, `%time/%t`, `%hide/%h`, `%approve/%a`,
  `%plan/%p`, `%epic`, `%edit/%e`, `%repeat/%r`, `%group/%g`, `%alt/%(`) match `src/sase/xprompt/_directive_types.py` +
  `_directive_alt.py` and `docs/xprompt.md`. None missing, none mislabeled.
- **AXE chop names** — `sase_fix_just`, `sase_pylimit_split`, the five `*_refresh_docs` chops, `gh_actions_fix`,
  `memory_episodes`, `tg_inbound`/`tg_outbound` all match `~/.config/sase/sase_athena.yml`.
- **`worker_models` example** — valid; `llm_provider.provider` is a real field (`docs/configuration.md`,
  `src/sase/doctor/checks_providers.py`).
- **External links** — Anthropic article confirms the **June 15, 2026** `claude -p` credit change; PDL arxiv
  `2410.19135` is correct; Codex app docs URLs load; `gastownhall/beads` is the canonical Beads repo (`steveyegge/beads`
  redirects to it), so that link is fine.

**The one clear, objective gap:** the post under-credits the SASE paper, which works against the user's explicit
requirement to "make it clear _how_ sase has taken inspiration." The paper (`arxiv 2509.06216`, "Agentic Software
Engineering: Foundational Pillars and a Research Roadmap") **coins the exact term "Structured Agentic Software
Engineering (SASE)" as its vision** — i.e. the project's name and acronym come straight from that paper — and it
**defines two environments**: `ACE = "Agent Command Environment"` (where humans orchestrate and mentor agent teams) and
`AEE = "Agent Execution Environment"` (where agents do the work and call humans for ambiguity).

The current post presents "Structured Agentic Software Engineering" as if SASE invented the expansion (intro line ~29
and the papers section ~552-556), and describes the ACE/AEE mapping vaguely ("Its ACE/AEE vocabulary directly shaped
SASE's naming: ACE is the human command environment, and AXE is SASE's practical execution/supervision daemon") without
the precise paper definitions that make the lineage concrete and verifiable.

## Goal

Make the SASE-paper inspiration explicit and accurate, satisfying the "make it clear _how_" requirement, without
bloating the post or touching anything already correct.

## Changes (single file: `docs/blog/posts/why-coding-agents-need-orchestration.md`)

1. **"The Papers Behind The Name" section** — rewrite the SASE-paper paragraph to state plainly that:
   - The paper _coins_ the "**Structured Agentic Software Engineering (SASE)**" vision — the project takes its name and
     framing directly from it.
   - The paper splits work into **SE for Humans** and **SE for Agents** and proposes two environments: **ACE — "Agent
     Command Environment"** (humans orchestrate/mentor agent teams) and **AEE — "Agent Execution Environment"** (agents
     execute, invoking humans on ambiguity).
   - Map them onto SASE concretely: SASE's **ACE** cockpit echoes the paper's Agent Command Environment, and SASE's
     **AXE** background daemon echoes the paper's Agent Execution Environment. Keep the existing acronym note that
     SASE's ACE is the "Agentic ChangeSpec Explorer" so readers aren't confused by the dual meaning.

2. **Intro nod (light touch, ~line 29)** — adjust the sentence "SASE calls that layer **Structured Agentic Software
   Engineering**" so it reads as borrowing the term from the research rather than coining it (e.g. note the name comes
   from the SASE paper, with the detail deferred to the papers section). Keep this minimal — one clause, no new
   paragraph.

## Out of scope (verified correct or purely cosmetic — leaving alone to avoid churn)

- Directive table, chop list, `worker_models` example, install commands, all external links, the Anthropic date, the
  Gastown/Beads comparison, diagram/screenshot briefs — all verified accurate; no changes.
- "Friction note" styling — already satisfies the "distinct syntax and/or icon" requirement via the described blockquote
  convention; not adding an emoji (subjective, not objective).

## Validation

- `just install` then `just check` (repo rule for file changes).
- `just docs-check` (strict MkDocs build) to confirm no broken links/frontmatter.
- Re-read the edited section to confirm the paper's `ACE`/`AEE` definitions are quoted accurately and the SASE acronym
  dual-meaning stays clear.

## Risk

Low. Single-file, additive-clarification edit to prose only; no code, config, or link targets change.
