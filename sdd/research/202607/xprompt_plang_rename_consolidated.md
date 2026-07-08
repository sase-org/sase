# XPrompt to Plang Rename Research

Date: 2026-07-08

## Recommendation

Do **not** rename `sase xprompt` to `sase plang`.

Ignoring implementation cost, `plang` is still a weaker name. It is attractive as a short way to say "prompt
language", and SASE's xprompt system really has become language-like. But the name being evaluated is not just the
name of an abstract language. It must also name the concrete things users create, list, save, expand, catalog, and put
in config. `xprompt` is imperfect, mainly because the `x` is opaque, but it works better as the artifact noun and as
the command/config namespace.

The better convention is:

- Keep `xprompt` for reusable prompt assets and the existing `sase xprompt` command namespace.
- Keep `prompt` for submitted prompt text and prompt history.
- Keep `workflow` for YAML execution graphs, `directive` for `%...` launch/runtime syntax, and `skill` for generated
  runtime-facing slash commands.
- If SASE needs a broader language-level term, introduce **SASE Prompt Language** as the umbrella term for the whole
  prompt-composition grammar.

## Verification Notes

I read both prior research-agent transcripts and the two reports they created:

- `sdd/research/202607/xprompt_plang_rename_research.md`
- `sdd/research/202607/xprompt_to_plang_rename_analysis.md`

Both agents answered the request and reached the same recommendation: do not rename `xprompt` to `plang`. The strongest
finding in the first report was the taxonomy argument: `plang` overstates the feature and blurs the distinction among
prompts, xprompts, workflows, directives, and skills. The strongest finding in the second report was the count-noun and
`sase prompt` collision argument: the term must name individual reusable artifacts, not only a language.

I resolved two conflicts while consolidating:

- The exact repo footprint counts differed by search scope. A fresh broad scan in this checkout found hundreds of files
  and many thousands of `xprompt` matches, so the stable conclusion is only that `xprompt` is a core public domain term.
  The count is not used as an implementation-cost objection.
- `xprompt` is not perfectly unique externally, but its collisions are weaker. `plang` has direct collisions in the LLM
  prompt/programming-language space, which is much more damaging for naming quality.

## What `xprompt` Names Today

SASE currently defines xprompts as reusable prompt templates with optional typed inputs and Jinja support. They can be
referenced inline with `#name`, can define local helper xprompts under `xprompts:`, and can participate in multi-agent
fan-out when their body contains top-level `---` separators. Standalone YAML workflows use `#!name`.

The term already spans several user-facing surfaces:

- CLI: `sase xprompt expand`, `explain`, `list`, `graph`, and `catalog`.
- Config and frontmatter: `xprompts:`, `xprompt_aliases:`, file-local helpers, workflow-local helpers, and prompt
  frontmatter.
- File and discovery conventions: `xprompts/`, `.xprompts/`, built-in package xprompts, project-local xprompts, and
  plugin xprompt entry points.
- Editor support: `sase lsp` starts the xprompt language server, with `SASE_XPROMPT_LSP_CMD` as the override.
- Agent skills: generated skills are sourced from xprompt definitions under `src/sase/xprompts/skills/`.
- UI and docs: ACE completion/browser surfaces, Admin Center references, catalog output, artifacts, and docs all use
  xprompt as a product term.

This matters because the term is not merely an internal module name. It names a concept users manipulate directly.

## The Best Case For `plang`

The rename has a real motivation:

- SASE's xprompt surface has become a small DSL: `#name` and `#!name` references, typed inputs, Jinja rendering,
  directives, command substitution, aliases, recursive expansion, multi-agent fan-out, YAML workflows, and an LSP.
- SASE docs and blog posts already use "prompt language" informally, so `plang` would formalize a mental model that
  exists.
- The `x` in `xprompt` is not documented. Users may wonder whether it means extended, executable, expansion, cross, or
  simply "ex prompt".
- `plang` is shorter and pronounceable.

This is enough to justify naming the broader grammar. It is not enough to justify replacing the artifact noun.

## Problems With `plang`

### 1. It Fails As A Count Noun

The most important practical test is whether the term works for one reusable prompt artifact.

`xprompt` passes:

- "write an xprompt"
- "three xprompts"
- "this xprompt's inputs"
- `xprompts:`

`plang` does not:

- "write a plang"
- "three plangs"
- "this plang's inputs"
- `plangs:`

A language is a system noun, not a natural instance noun. But SASE users mostly create and manage instances: prompt
templates, reusable snippets, workflow entries, catalog items, and saved prompt assets. Renaming the artifact noun to a
language noun would make the common case awkward.

### 2. It Collides With `prompt`, Which Is Already A First-Class SASE Concept

SASE already has a separate `sase prompt` command group for prompt history: list, show, search, run, edit, select,
delete, prune, save, and export. The docs also use `prompt` for the submitted instruction text, prompt history shards,
the ACE prompt bar, `prompt_part` workflow steps, and `PromptDirectives`.

The current pair is clear:

- `sase prompt`: raw submitted prompts and prompt history.
- `sase xprompt`: reusable prompt assets, expansion, catalog, and workflow-related prompt composition.

`sase plang` would sit next to `sase prompt` while deriving from "prompt language". That makes the distinction less
visible and less teachable. The current `x` prefix is opaque, but it does useful work: it marks the concept as related
to a prompt while still separate from a raw prompt.

### 3. It Blurs The Existing Taxonomy

SASE's current taxonomy is useful:

- **Prompt**: submitted instruction text and prompt history.
- **XPrompt**: reusable named prompt asset or inline-capable prompt/workflow reference.
- **Workflow**: YAML multi-step execution graph.
- **Directive**: launch/runtime control syntax such as `%name` and `%wait`.
- **Skill**: generated runtime-facing slash command derived from xprompt metadata.

`plang` collapses the language layer and artifact layer. "Plang workflow", "local plang", "plang aliases", and
"plang catalog" are all plausible but imprecise. It becomes less clear whether the word means a language, a program,
a template, a workflow file, or a catalog entry.

### 4. It Creates A Language-Server Tautology

SASE already has an xprompt language server. Renaming the noun to `plang` makes that concept read as "prompt-language
language server" or "plang language server". That is not fatal, but it is a small sign that the name is being applied at
the wrong layer. `xprompt language server` cleanly means "a language server for xprompt files and references."

### 5. It Has Direct External Collisions

`plang` is already used in nearby spaces:

- A ScienceDirect / Expert Systems with Applications paper titled "Plang: Efficient prompt engineering language for
  blending natural language and control flow in large language models" defines PromptLanguage (Plang) for LLM prompt
  engineering.
- `plang.is` and `github.com/plangHQ` describe PLang as a natural-language programming language with LLM-assisted
  compilation/execution.

These are not random name collisions. They are prompt/programming-language collisions in the same broad market. That
makes `plang` less searchable and less ownable than `xprompt`.

### 6. It Saves Too Little

`plang` saves two characters over `xprompt`, but introduces ambiguity:

- Does `p` mean prompt or programming?
- Is it pronounced "pee-lang" or one syllable?
- Is a `plang` the language, a file, a template, or a workflow?

Microsoft's naming guidance favors readability over brevity and discourages nonstandard abbreviations unless they are
widely accepted. Google developer-doc guidance similarly prioritizes clarity and consistency for developer audiences.
On that standard, `plang` does not earn the abbreviation.

## Adjacent Naming Landscape

Other prompt-language projects tend to separate the language/formalism from the concrete file or asset:

- IBM's Prompt Declaration Language (PDL) uses a full descriptive language name for a YAML-based prompt formalism.
- Microsoft's Prompty uses a concrete `.prompty` file/format noun for Markdown plus YAML frontmatter and Jinja prompt
  templates.

That pattern supports a two-layer SASE convention: use **SASE Prompt Language** when discussing the whole grammar, and
use `xprompt` for the concrete reusable asset.

## Decision Matrix

| Criterion | `xprompt` | `plang` |
| --- | --- | --- |
| Names an individual reusable prompt asset | Good enough | Weak |
| Names the whole prompt-composition language | Weak | Better |
| Distinguishes from raw `prompt` / `sase prompt` | Strong | Weak |
| Fits existing taxonomy | Strong | Weak |
| Works in plural/config/UI forms | Acceptable | Awkward |
| Avoids external collisions | Better | Worse |
| Improves readability over brevity | Mixed | Weak |
| Leaves room for an umbrella language name | Strong | Weak |

## Final Answer

Do not move forward with `xprompt` to `plang`.

The best version of the idea is not a rename. It is to acknowledge that SASE has a prompt language and name that layer
explicitly. Keep `xprompt` as the concrete reusable prompt asset and command namespace. Add **SASE Prompt Language** as
the umbrella term if the product needs a formal name for the full grammar.

I would also document the `x` directly: `xprompt` is an "X-Prompt", an intentionally namespaced prompt-derived artifact
that is related to, but distinct from, a raw `prompt`. That fixes the real weakness in the current name without taking
on `plang`'s count-noun, taxonomy, prompt-namespace, language-server, and external-collision problems.

## Sources

Local sources:

- `src/sase/xprompt/__init__.py`
- `docs/xprompt.md`
- `docs/prompt.md`
- `docs/cli.md`
- `docs/editor.md`
- `docs/blog/posts/prompt-widget-and-nvim.md`
- `docs/blog/posts/why-coding-agents-need-orchestration.md`
- `src/sase/default_config.yml`
- `src/sase/config/sase.schema.json`
- `AGENTS.md`
- `memory/generated_skills.md`, read via `sase memory read generated_skills.md`

External sources:

- Microsoft Framework Design Guidelines, General Naming Conventions:
  <https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/general-naming-conventions>
- Google developer documentation style guide:
  <https://developers.google.com/style>
- IBM Prompt Declaration Language:
  <https://ibm.github.io/prompt-declaration-language/>
- Microsoft Promptflow Prompty:
  <https://microsoft.github.io/promptflow/how-to-guides/develop-a-prompty/index.html>
- Plang paper:
  <https://www.sciencedirect.com/science/article/pii/S0957417425037339>
- PLang site:
  <https://plang.is/>
- PLang GitHub organization:
  <https://github.com/plangHQ>
