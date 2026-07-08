# Renaming `xprompt` → `plang`: A Critique

**Date:** 2026-07-08
**Author:** Research agent (for Bryan Bugyi)
**Question:** Should the SASE concept currently called **`xprompt`** be renamed to **`plang`** (presumably "prompt language")?
**TL;DR recommendation:** **No — do not rename to `plang`.** Keep `xprompt`. If the real motivation is that the `x` prefix is opaque, fix that with documentation (or a light backronym), not a rename. See [Recommendation](#recommendation).

> Note: The user stipulated that *implementation cost is not a factor*. This analysis therefore ignores migration effort and judges the two names purely on naming quality, conceptual clarity, and long-term ergonomics.

---

## 1. What `xprompt` actually is

From the module docstring (`src/sase/xprompt/__init__.py`):

> "XPrompt system for typed prompt templates with argument validation... a replacement for the legacy snippet system, adding: Markdown files with YAML front matter... type validation... backward compatibility with existing `#name(args)` syntax... YAML workflow support for multi-step agent workflows."

From `docs/xprompt.md`:

> "XPrompts are reusable prompt templates with optional typed inputs and Jinja2 support. They let you define a prompt fragment once and reference it by name anywhere a prompt is composed... Inline prompt fragments use `#name`; standalone workflows use `#!name`."

So an xprompt is simultaneously:

1. **An artifact** — a single named, reusable, typed prompt template (`.md`) or workflow (`.yml`). Users write *many* of them.
2. **A system/mechanism** — expansion, directives, Jinja2, aliases, recursive resolution, an LSP, and a CLI.

It has genuinely matured into a small **DSL**: `#name(args)` references, `%directive` tags, typed/validated inputs, Jinja2, command substitution, aliases, recursive expansion, and multi-step YAML workflows. There is even a dedicated **language server** (`sase lsp`, env var `SASE_XPROMPT_LSP_CMD`). This maturity is the strongest point *in favor* of a "prompt language" framing — and, as noted in §4, the project **already informally calls it exactly that** ("The Prompt Language") in its own blog and docs. But as shown below, that framing does not survive the countervailing problems.

**On the `x`:** nothing in the codebase documents what `x` stands for (no "extended/executable/extensible" expansion anywhere). It is a bare disambiguating prefix. Note the CamelCase house form is always written **`XPrompt`** (capital P) — i.e. "X-Prompt", *not* an initialism for a word. So there is no hidden meaning being lost by a rename, but also nothing to "fix" by expanding it.

**Three directories carry the name**, all implicated by a rename: `src/sase/xprompt/` (the Python module), `src/sase/xprompts/` (the bundled/built-in library + `skills/`), and repo-root `xprompts/` (this project's own local templates).

### Scale of the term (context, not a cost argument)

- **836** files and **~10,513** raw occurrences of `xprompt` (case-insensitive) across code, tests, and docs.
- **0** current occurrences of `plang` — so there is no *internal* naming conflict.
- The term is embedded in many **user-facing surfaces** (these are what a rename would actually change the *meaning* of, cost aside):
  - CLI command: `sase xprompt {expand,explain,list,graph,catalog}` (`src/sase/main/parser_xprompt.py`, `docs/xprompt.md`).
  - Config keys: `xprompts:`, `xprompt_aliases:` (`src/sase/default_config.yml:412,415`).
  - User-created directories: `xprompts/`; config permission scopes `xprompts-dir`, `xprompts-schema`.
  - The **xprompt language server** / LSP (`sase lsp`, `SASE_XPROMPT_LSP_CMD`).
  - Dozens of TUI/API tokens: `xprompt_browser`, `xprompt_completion`, `xprompt_assist`, `xprompts_enabled`, `xprompt_catalog`, etc.
  - Docs: dedicated `docs/xprompt.md`, plus references throughout `architecture.md`, `llms.md`, `editor.md`, `cli.md`.

---

## 2. Naming-quality scorecard

| Criterion | `xprompt` | `plang` | Winner |
|---|---|---|---|
| Signals "prompt-related" at a glance | Yes — literally contains "prompt" | Weak — must first learn that `p` = prompt | **xprompt** |
| Works as a **count noun** (an X, three Xs, this X's args) | Yes — natural | **No** — a "language" has no instances | **xprompt** |
| Distinct from the existing `prompt` concept | Yes — `x` prefix differentiates | Blurs into it ("prompt language") | **xprompt** |
| Composes with `language server` / LSP | "xprompt LSP" — clean | "prompt-language language server" — tautology | **xprompt** |
| Externally distinctive / searchable / ownable | Yes — no known collisions | **No** — collides with existing products | **xprompt** |
| Fits SASE coinage culture (`ace`, `axe`, `bead`, `gp`, `hood`) | Yes — invented, unique | Weaker — generic compression | **xprompt** |
| Matches `#name`-in-a-prompt trigger mental model | Yes — "prompt" in name | Abstracted away | **xprompt** |
| Descriptive of the *matured DSL* | Weak (opaque `x`) | **Strong** ("language") | **plang** |
| Brevity | 7 chars | 5 chars | **plang** (minor) |

The only two boxes `plang` wins are cosmetic (brevity) or a framing upgrade (DSL honesty) — and the framing upgrade can be captured in prose without a rename. Every criterion `plang` loses is a substantive correctness/usability problem. Details follow.

---

## 3. The case *against* `plang` (the substantive problems)

### 3.1 The count-noun failure (most damaging)

The term must name **individual instances**, not just the system. The config key is literally a dictionary of many:

```yaml
xprompts:            # a collection of many named templates
  bd/land_epic: ...
  c: ...
```

- `xprompt` reads correctly as a count noun: *"write an xprompt," "three xprompts," "this xprompt's inputs."*
- `plang` / "prompt **language**" is a **mass/system noun**. *"Write a plang"? "Three plangs"? A `plangs:` config key?* A language does not have countable instances. Renaming forces the plural `plangs:` to mean "many languages," which is semantically nonsensical for what is really "many templates."

This alone is close to disqualifying: the concept's most common usage is referring to a single artifact, and `plang` is grammatically ill-suited to that.

### 3.2 Collision with the first-class `prompt` concept — including a whole CLI namespace

`prompt` is already a heavily used, *distinct* concept in the codebase — not a synonym for xprompt:

- **`sase prompt` is its own top-level command group** for prompt *history* — list/show/search/run/edit/select/delete/prune/save/export (`docs/prompt.md`). Its intro: *"The `sase prompt` command group is the first-class way to inspect, search, reuse, curate, and clean up that history."* It sits directly beside `sase xprompt`. Tellingly, `sase prompt save` already "Save[s] a prompt as a reusable **xprompt** markdown file" — so `prompt` and `xprompt` appear on the *same* doc table row, cleanly distinguished today.
- The actual text a user types (the "prompt bar", `prompt_panel`/`prompt_input_bar` widgets — ~46 files).
- `prompt_part` workflow steps.
- `PromptDirectives` / `%name` prompt directives (`src/sase/xprompt/directives.py`).

`plang` = *prompt-language* **re-injects "prompt" as its root** and blurs a distinction that is currently crisp. Concretely, a `sase plang` command would sit next to `sase prompt` — two near-synonymous, near-homophonous top-level commands (*"was it `sase prompt` or `sase plang`?"*). The current pairing `sase prompt` (history) vs `sase xprompt` (templates) is far more distinguishable because the `x` prefix visually and aurally separates them. The `x` marks xprompt as **kin to, but distinct from,** a raw prompt — exactly the relationship that holds. `plang` throws that away.

### 3.3 The "language server" tautology

There is already an **xprompt language server** (`docs/editor.md`: "`sase lsp` starts the SASE xprompt language server"; env var `SASE_XPROMPT_LSP_CMD`). Renaming yields:

> **plang language server** = "prompt-**language** language server"

That is a tautology. You would either live with the awkwardness or rename/decouple the LSP and lose the naming link. "xprompt language server" has no such problem.

### 3.4 External brand collision — `plang` is already taken in *this exact domain*

This is the decisive external strike. "Plang" is **already an established name for prompt/LLM tooling**, so adopting it makes SASE's feature non-distinctive, un-Googleable, and confusable with real products:

- **Plang** — "Efficient prompt engineering language for blending natural language and control flow in large language models," a published DSL (Expert Systems with Applications / ScienceDirect, 2025). This is *precisely* a "prompt language" for LLM/multi-agent workflows — i.e., a near-namesake of what SASE would be claiming.
- **Plang** (plang.is) — a natural-language programming language for building AI/agents.

Good naming for a distinctive feature should be **ownable and searchable in its domain**. `xprompt` scores perfectly here (zero external collisions, and — as an invented, highly greppable token — trivially searchable). `plang` fails on both counts and actively invites confusion with a competing prompt-DSL.

### 3.5 It reads like a general-purpose programming language, not templates

"Plang" strongly connotes *"programming language"* (cf. real projects named Plang). That over-promises: xprompts are reusable **prompt templates + light workflows**, not a general PL. The current name keeps expectations calibrated ("prompt-ish thing"), while `plang` sets up a mismatch with what users actually get.

### 3.6 Off-brand for SASE's coinage style

SASE favors short, *distinctive, invented* handles: `ace`, `axe`, `bead`, `gp`, `hood`, `chop`, `lumberjack`. These are memorable precisely because they're not generic. `xprompt` fits that culture (unique, greppable, coined). `plang` is a generic compression that also happens to be externally claimed — the opposite of the house style.

---

## 4. The case *for* `plang` (steel-man)

To be fair, the motivations behind the idea are real:

1. **The name "prompt language" is already in use — informally.** This is the strongest point for the rename. The project's own blog and docs already call the xprompt surface *"The Prompt Language"* (`docs/blog/posts/prompt-widget-and-nvim.md`: heading "The Prompt Language"; "the prompt language is the contract"; `docs/blog/posts/why-coding-agents-need-orchestration.md`: "SASE exposes an XPrompt language server"). So `plang` would merely *formalize a mental model that already exists* — there's genuine internal precedent for the framing.
2. **The `x` is undocumented / opaque.** Nothing states what `x` means; new users may not know how to read or pronounce it ("ex-prompt"?). A legitimate wart.
3. **The system really is a language now.** Jinja2 + directives + typed inputs + workflows + an LSP make "prompt language" an *honest* description of the mechanism's power. "Template" undersells it.
4. **Snappier.** `plang` is shorter and has a certain ring.
5. **Precedent for renaming exists.** The project already renamed `snippet` → `xprompt` (and migrated `gai` → `sase`), so a rename is culturally possible.

However, note the irony in (1): the informal phrase *"the prompt language"* reads fine **as prose describing xprompt's nature**, precisely because it isn't competing as a proper noun with the busy `prompt` namespace. Promoting it to the *formal name of the artifact* is a different move — that's exactly what triggers the §3.2 CLI/namespace collision. And motivations (2)–(3) are addressable *without* a rename (document the `x`; keep describing the DSL nature in prose). (4)–(5) don't outweigh the §3 problems — especially the count-noun failure and the external collision.

---

## 5. If a rename were truly desired anyway

Should Bryan still want to rename (e.g., to retire the opaque `x`), `plang` is a poor target for the reasons above. Better targets would **preserve count-noun-ability and prompt-kinship** and avoid the external collision — for example a concrete artifact noun rather than "language" (things you can say "write a ___" / "three ___s" about). But note that *any* rename of a term this deeply woven into user-facing config, directories, CLI, and LSP imposes a real **relearning cost on users and their existing dotfiles/repos** — which is a UX cost even though implementation cost is off the table. The bar for a rename should be "the new name is clearly better on the merits," and no candidate examined clears it decisively over the incumbent.

---

## 6. Recommendation

**Do not rename `xprompt` to `plang`.**

Reasoning in one paragraph: `xprompt` is not a perfect name (the `x` is opaque), but it satisfies four hard constraints that `plang` violates: (a) it works as a **count noun** for the individual template artifacts that dominate real usage — `plangs:` is nonsensical; (b) it is **differentiated from yet kin to** the first-class `prompt` concept — including the sibling `sase prompt` command group — whereas `sase plang` next to `sase prompt` is a near-homophone collision; (c) it avoids the **"language server" tautology**; and (d) it is **externally unclaimed and greppable**, whereas `plang` is already an established name for a competing LLM prompt DSL, killing distinctiveness and searchability. `plang`'s only genuine advantages — brevity, DSL-honest framing, and matching the informal "the prompt language" phrasing — are cosmetic or achievable through documentation.

**Instead, address the underlying itch cheaply:**

1. **Document the `x` as an intentional namespace marker.** State plainly in `docs/xprompt.md` and the glossary that `xprompt` = "X-Prompt": a prompt-*derived* artifact, prefixed to distinguish it from a raw `prompt`. (Don't over-backronym — the house style already writes `XPrompt`, so lean into "X-Prompt as a namespace," not a forced word expansion.) This removes the opacity complaint at near-zero risk.
2. **Keep the "prompt language" framing in prose, not in the name.** The blog already does this well ("The Prompt Language"). Describe xprompts as "SASE's small prompt-templating language" wherever the power matters — you keep the DSL-honest framing without sacrificing the count noun, without the `sase prompt` collision, and without the external `plang` clash.
3. **Only revisit a rename** if a candidate emerges that beats `xprompt` on the §2 scorecard *without* reintroducing the count-noun / `prompt`-collision / external-collision problems. `plang` is not that candidate.

---

## Appendix: Evidence index

- Definition & docstring: `src/sase/xprompt/__init__.py`; `docs/xprompt.md` (intro, TOC); glossary; `README.md`.
- CLI surface: `src/sase/main/parser_xprompt.py`; `src/sase/main/entry.py`; `src/sase/main/xprompt_handler.py`; `docs/xprompt.md` (subcommands).
- Config keys: `src/sase/default_config.yml:412` (`xprompt_aliases`), `:415` (`xprompts`), `:61` (`auto_xprompt_menu`); schema `src/sase/config/sase.schema.json`.
- Three implicated directories: `src/sase/xprompt/`, `src/sase/xprompts/`, repo-root `xprompts/`.
- LSP / "language server": `docs/editor.md`; `docs/cli.md`; env var `SASE_XPROMPT_LSP_CMD`; `src/sase/integrations/xprompt_lsp.py`.
- `prompt` as a distinct concept: the `sase prompt` history command group (`docs/prompt.md`); `prompt_part`; `prompt_panel`/`prompt_input_bar`; `PromptDirectives` (`src/sase/xprompt/directives.py`).
- "Prompt language" already used informally: `docs/blog/posts/prompt-widget-and-nvim.md` ("The Prompt Language"); `docs/blog/posts/why-coding-agents-need-orchestration.md` ("XPrompt language server"); `docs/editor.md:44`.
- Legacy rename precedent (`snippet` → `xprompt`; `gai` → `sase`): module docstring; `git log`.
- SASE coinage culture: `ace`, `axe`, `bead`, `gp`, `hood`, `chop`, `lumberjack` (glossary, `docs/axe.md`).
- External `plang` collisions (naming/searchability):
  - "Plang: Efficient prompt engineering language for blending natural language and control flow in large language models," ScienceDirect — https://www.sciencedirect.com/science/article/pii/S0957417425037339
  - Plang, natural-language programming language — https://plang.is (per web results)
