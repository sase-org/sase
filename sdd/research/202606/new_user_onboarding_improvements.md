# New-User Onboarding Improvements (Pre-Blog-Launch)

- **Date:** 2026-06-09
- **Author context:** Research for Bryan, ahead of a public blog post about SASE.
- **Goal:** Recommend a *few* high-priority improvements that make SASE easier to **install, understand, and
  use** for brand-new users who arrive cold from a blog post.
- **Status:** Research / recommendations. No code changed.
- **Method:** Three parallel audits — (1) synthesis of prior onboarding research in this directory, (2) a fresh
  brand-new-user *install + first-run* walkthrough of the current `master`, (3) a docs *digestibility* audit —
  cross-checked against the live code so findings reflect the repo **today**, not when older research was written.

---

## TL;DR — the three that matter most

A stranger who reads the blog post and decides to try SASE hits friction in this exact order: **install →
understand → first agent run.** All three are currently rough, and the fixes are cheap relative to their impact.

1. **Fix the README install funnel.** SASE is now published on PyPI (`sase==0.1.3`, MIT, prebuilt Rust-core
   wheels), but the README still routes *everyone* through the contributor path (`uv venv` → `just install`),
   which needs `just`, a checkout, and the full `[dev]` toolchain. New users should see `uv tool install sase`
   first. **Highest impact, lowest effort.**
2. **Publish the 15-minute quickstart.** A genuinely good, jargon-gentle, end-to-end tutorial already exists at
   `docs/blog/posts/hello-sase-your-first-15-minutes.md` — but it is `draft: true` and excluded from the nav,
   README, and `index.md`. The single best onboarding asset is currently invisible. Un-draft it, add a
   **"Getting Started"** nav section, and link it from the README and the launch essay.
3. **Document the agent-CLI prerequisite.** SASE *orchestrates* Claude Code / Codex / Gemini / Qwen / OpenCode —
   it is not itself an LLM. Nothing in the README, `index.md`, or `init.md` tells a new user they must install
   **and authenticate** at least one provider CLI before `sase run` will work. This is the most common silent
   first-run failure and it is entirely undocumented at the onboarding layer.

Everything else (jargon load, README density, ACE empty-state, a comparison page, the missing `LICENSE` file) is
real and worth doing, but these three are the ones that decide whether a curious reader gets to a first success or
bounces.

---

## What's already good or recently fixed (don't re-litigate)

Several blockers flagged in earlier research (`sase_install_use_understand_readiness_consolidated.md`,
`sase_doctor_command_consolidated.md`) have since been resolved. Current `master` already has:

- ✅ **`sase` on PyPI at `0.1.3`** with MIT license, real description, and Homepage/Repository URLs in
  `pyproject.toml`. The old "stale `0.1.0`" problem is gone. Prebuilt `sase_core_rs` wheels mean `pip`/`uv tool`
  installs pull the Rust core automatically (Linux x86_64/aarch64, macOS universal2, Windows x86_64, CPython
  3.12+) — the Rust dependency is *frictionless on the install path*, just not surfaced in the README.
- ✅ **`sase doctor`** exists (`parser_doctor.py`) — the read-only diagnostic aggregator that prior research
  specced. It's even referenced in the README's command list. This is a strength to *lean on*, not rebuild.
- ✅ **`sase version`** exists (`parser_version.py`) — the missing top-level version surface is done.
- ✅ **README value proposition is strong.** The one-liner and "Why sase" section land the pitch within the first
  screen. The problem is everything *after* that, not the pitch itself.
- ✅ **`docs/index.md`** has a genuinely good plain-language hook: *"A single coding-agent run can produce a patch.
  Real projects also need a place to store intent, pass work between agents, order dependencies, track review
  state, retry failed runs…"* — keep this; build the on-ramp around it.

The implication: the remaining work is **packaging the on-ramp**, not building new machinery. The good first-run
tools (`sase doctor`, `sase core health`, the quickstart tutorial, the architecture doc) mostly already exist —
they're just hidden, mis-ordered, or pointed at the wrong audience.

---

## The new-user journey, and where it breaks

### Stage 1 — Install (the README sends users down the contributor path)

The README "Quick start" (`README.md:56-70`) reads:

```bash
# Requirements: Python 3.12+, uv, just
uv venv .venv
source .venv/bin/activate
just install
sase core health
sase ace
```

Problems, verified against current `master`:

- **No mention of `uv tool install sase` or `pip install sase`** anywhere in the README, even though both work
  today. The one-step install is documented only in deep reference pages (`docs/rust_backend.md`,
  `docs/plugins.md`). A reader following the README is steered into the **contributor** flow.
- `just install` runs `uv pip install ... -e ".[dev]"` (`Justfile:83`) — it pulls ruff, mypy, pytest, tox,
  twine, etc. A normal user does not need any of this.
- The quickstart requires **two extra prerequisites** (`just`, `uv`) that a `uv tool install sase` user doesn't,
  and **never shows `git clone`** — yet `just install` only works inside a checkout. A copy-paste user has no repo.

**Net:** ~6 manual steps + 2 extra tools + a heavy dev install, versus the unadvertised **1-step**
`uv tool install sase`.

### Stage 2 — Understand (jargon dumped before any payoff)

- **`docs/index.md`** dumps ~12 undefined custom terms as links before defining any — ACE, AXE, ChangeSpecs,
  Beads, XPrompts, SDD, ProjectSpecs, mentors, episodes, agent families — and gives **no install step and no first
  command**. It routes ("pick the surface that matches your work") rather than teaches.
- **No "Getting Started" / "Quickstart" / "Installation" / "Tutorial" section exists in the nav** (`mkdocs.yml`).
  The first beginner-facing section is literally "The Basics," whose first page is `init.md` — opening with
  `sase init -c` flag tables, not install steps.
- **No user-facing glossary.** The only glossary (`memory/short/glossary.md`) is an internal agent-memory file,
  outside `docs/`, covering 9 terms, written *for agents operating the TUI*. Newcomers never see it.
- **The unifying mental-model doc (`docs/architecture.md`) is filed under "Beyond the Basics"** — i.e. *after* the
  reader was supposed to learn the parts — and is written ownership/boundary-first (Rust vs Python), not as a
  beginner narrative.
- **Whimsical vocabulary raises the cost:** tales / epics / legends / myths (SDD tiers), Orchestrator /
  Lumberjacks / chops (AXE). These need role-translation on first appearance.
- Four reference docs are 1,200–1,900 lines (`ace.md` 1,900; `configuration.md` 1,760; `xprompt.md` 1,563;
  `llms.md` 1,228), and three of them sit under "The Basics" with no lightweight intro counterpart.

### Stage 3 — First run (silent failures, no guidance)

- **The agent-CLI prerequisite is undocumented.** SASE orchestrates Claude Code / Gemini / Codex / Qwen /
  OpenCode, but no onboarding surface tells the user to install or authenticate one (no `claude login` /
  `ANTHROPIC_API_KEY` guidance). `sase run "<prompt>"` will fail with no upfront warning.
- **The README "Useful first commands" block lists ~35 commands** (`README.md:72-108`) — `doctor`, `amd`,
  `memory episodes`, `skills`, `plugin`, `project`, `bead`, `workspace`, … — with no signal which 2-3 a newcomer
  actually needs. The real quickstart drowns under reference material and a ~50-line "Operational model" section.
- **Bare `sase` (no args) errors out** (subparsers are `required=True`) instead of offering a hint. `sase --help`
  dumps **40 subcommands alphabetically** with no "start here" grouping; ~36 are advanced/automation-internal
  (`var`, `questions`, `plan`, `artifact`, `revive-log`, `lsp`, `axe`, `telemetry`…) yet sit at the same level as
  `ace` and `run`.
- **`sase ace` has no first-run guidance and no empty-state coaching.** A new user with zero projects is dropped
  into 3 empty tabs (ChangeSpecs / Agents / Axe) with no welcome, no "No ChangeSpecs yet — try `sase run …`," and
  no on-screen hint that `?` opens help. The `HelpModal` exists but is a dense keymap cheat-sheet you must already
  know to open.

---

## Prioritized recommendations

Scored by **impact** (does it change whether a new user succeeds?) and **effort**. Lead with P0; they are the
launch blockers.

### P0 — Launch blockers (do before the post goes live)

**P0-1. Make `uv tool install sase` the headline install; split user vs contributor paths.**
Rewrite the README "Quick start" so the *first* thing a reader sees is the one-step install:

```bash
uv tool install sase      # or: pipx install sase
sase doctor               # verify install, config, and provider readiness
sase run "explain what this repo does, don't change anything"   # first agent run
sase ace                  # open the control surface to see the result
```

Move the `uv venv` / `just install` block into a clearly-labeled **"Install from source (contributors)"**
subsection. *Impact: high. Effort: low (README edit).* This is the single highest-leverage change.

**P0-2. Publish the 15-minute quickstart and add a "Getting Started" nav section.**
`docs/blog/posts/hello-sase-your-first-15-minutes.md` is already written, gentle, and end-to-end (install →
`sase run` → find the ChangeSpec in ACE → reuse as XPrompt → plan with beads, with "what you just did" recaps and
a closing vocabulary section). Remove `draft: true`, add it to `mkdocs.yml` nav under a new top **"Getting
Started"** section (above "The Basics"), and link it from the README and the launch essay. Verify it end-to-end
from a clean machine first, recording the real install time and any failure modes. *Impact: high. Effort: low —
the asset exists.*

**P0-3. Document the agent-CLI prerequisite up front.**
Add a short **"Prerequisites: bring your own coding agent"** note to the README quickstart and `index.md`: SASE
drives an existing agent CLI, so install and authenticate at least one (e.g. `claude` / `gemini` / `codex`) before
`sase run`. Have `sase doctor` detect provider-CLI presence/auth and print an explicit next step when none is
found (it already reports provider state — make the *absence* a clear, actionable WARN). *Impact: high. Effort:
low-medium.*

### P1 — Digestibility (help them "get it" and not drown)

**P1-1. Trim the README to a real on-ramp.**
Target shape: value prop (keep) → prerequisites → 1-step install → **one** first command → 3-5 curated "next
steps" → "Keep reading" links. Move the ~35-command dump and the ~50-line "Operational model" reference prose into
docs (`cli.md`, `architecture.md`). A newcomer should never see 35 commands on the landing README. *Impact:
high. Effort: low-medium.*

**P1-2. Add a user-facing glossary + a "translate the names" table.**
Create `docs/glossary.md` (in the nav) defining the core dozen terms in one line each, with role-translations for
the whimsical names: **ACE** = the TUI control surface, **AXE** = the background automation daemon,
**ChangeSpec** = a durable, PR-like record of one change, **Beads** = dependency-aware work items, **XPrompt** =
reusable prompt/workflow spec, **SDD tiers** (tales/epics/legends) = sized units of planned work. Add a compact
"three concepts to start" box (workspace target → agent run → ChangeSpec) near the top of `index.md` and reduce
the up-front jargon-link dump there. *Impact: high. Effort: low-medium.*

**P1-3. Surface the mental model earlier.**
Either move `docs/architecture.md` (or a lighter "How SASE fits together" narrative cut from it) up next to the
quickstart, or fold a one-screen "how the pieces connect" diagram into `index.md` / the Getting Started page. The
beginner narrative shouldn't live only in the (currently hidden) blog series. *Impact: medium. Effort: low-medium.*

**P1-4. Give `sase ace` a first-run / empty-state.**
When there are no projects/ChangeSpecs/agents, render coaching instead of blank tabs — e.g. "No ChangeSpecs yet —
run `sase run \"…\"` or `sase git init <name>` to get started," plus a persistent footer/hint that `?` opens help.
Reuse the existing `HelpModal`; just make it discoverable. *Impact: medium. Effort: medium (TUI work).*

### P2 — Credibility & quick wins (worth doing around launch)

- **P2-1. Add a `LICENSE` file.** `pyproject.toml` declares MIT but there is **no `LICENSE` file**, so GitHub shows
  `license: null`. Trivial, and it removes a credibility ding for OSS-savvy readers. *Effort: trivial.*
- **P2-2. Write a comparison / FAQ page.** Answer the predictable high-intent objection: "Why not just use Claude
  Code / tmux + git worktrees / a dashboard?" plus "What does SASE sandbox?" (agents run with full local FS
  access — workspace clones are *concurrency* isolation, not a security boundary; say so plainly). This question
  *will* come up in blog comments. *Effort: medium.*
- **P2-3. Group `sase --help` and make bare `sase` helpful.** Offer a "start here" grouping (ace, run, doctor,
  init) ahead of the 40-command alphabetical wall, and have bare `sase` print a friendly hint instead of an
  argparse error. *Effort: low-medium.*
- **P2-4. Lean on `sase doctor` as the documented first troubleshooting step** everywhere a new user might get
  stuck (README, quickstart, agent-launch error paths). It already exists — make it the reflexive answer to
  "it's not working." *Effort: trivial (docs).*

---

## Scope guard — what *not* to do for the launch

- Don't try to ship the larger feature ideas from older comparison research (MCP control plane, container/remote
  workspace backends, inline diff review in ACE, FTS5 chat search, living-plan checkpoints). They're real
  roadmap items but **none of them is what blocks a new user from a first success**, and pursuing them now trades
  cheap onboarding wins for expensive feature work.
- Don't keep the 10-post numbered blog serial as the launch shape — prior research (`sase_blog_series_structure_consolidated.md`)
  already argues for a smaller promoted set. Onboarding-wise, the only post that *must* be live is the
  quickstart (P0-2).
- Don't expose optional personal integrations (chezmoi, Telegram/mobile, Bob-vault, nvim) on the first path —
  they make SASE read like one person's private system. Label them clearly as optional.

---

## Appendix — relationship to prior research

This consolidates and *updates* (does not duplicate) earlier work in `sdd/research/`:

- `202606/sase_install_use_understand_readiness_consolidated.md` — primary source for the install/release funnel
  and concept-compression analysis. **Update:** its core blockers (stale PyPI `0.1.0`, missing `sase --version`)
  are now resolved; the install-funnel *framing* (user vs contributor path) and the draft-quickstart blocker still
  stand and are carried forward here as P0-1/P0-2.
- `202606/sase_doctor_command_consolidated.md` — **Update:** `sase doctor` is now implemented; this doc
  re-purposes it (P0-3, P2-4) rather than asking to build it.
- `202606/sase_blog_launch_strategy_consolidated.md`, `202606/sase_blog_series_structure_consolidated.md`,
  `202606/sase_hacker_news_popularity_strategy_consolidated.md` — launch sequencing and the missing-comparison-page
  finding (carried forward as P2-2).
- `202606/open_source_sase_competitors_consolidated.md` — name-translation and sandbox-credibility findings
  (P1-2, P2-2).
- `202604/sase_vs_codex_comparison.md`, `202604/sase_vs_hermes_agent.md` — setup-complexity disadvantage and
  larger feature gaps (noted in the scope guard as explicitly out of launch scope).

### Key evidence (current `master`, verified 2026-06-09)

| Finding | Location |
| --- | --- |
| README quickstart routes to `just install`, no `uv tool install sase` | `README.md:56-70` |
| ~35-command "Useful first commands" dump | `README.md:72-108` |
| Quickstart tutorial is `draft: true`, not in nav/README/index | `docs/blog/posts/hello-sase-your-first-15-minutes.md:3` |
| No "Getting Started"/Install nav section | `mkdocs.yml` nav |
| `index.md` dumps ~12 undefined terms, no first command | `docs/index.md` |
| No user-facing glossary (only internal agent file) | `memory/short/glossary.md` |
| Mental-model doc filed under "Beyond the Basics" | `docs/architecture.md` |
| 40 flat top-level subcommands; bare `sase` errors | `src/sase/main/parser.py:122,128-168` |
| `sase ace` has no empty-state / first-run guidance | `src/sase/ace/tui/` |
| No `LICENSE` file despite MIT in pyproject | repo root |
| `sase doctor` / `sase version` already implemented | `parser_doctor.py`, `parser_version.py` |
