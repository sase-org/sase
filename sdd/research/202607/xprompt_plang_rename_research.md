# Research: Should SASE Rename XPrompt to Plang?

Date: 2026-07-08

## Recommendation

Do **not** move forward with renaming `xprompt` to `plang`.

The rename would make SASE's terminology less precise, not more precise. `xprompt` is an imperfect but defensible name
for reusable prompt fragments and inline-capable prompt/workflow references. `plang` implies a whole prompt/programming
language, has awkward noun behavior, and now has direct external collisions in the LLM prompt-language space. If SASE
needs a language-level brand, introduce **SASE Prompt Language** as an umbrella term for the syntax and semantics while
keeping `xprompt` as the asset/command noun.

Implementation cost is intentionally excluded from this recommendation. The repository footprint below is used only as
evidence that `xprompt` is a core domain term, not as a migration-cost argument.

## Method

I reviewed:

- Local SASE docs and code for current `xprompt` semantics, command surfaces, config keys, artifacts, LSP naming, and
  workflow relationships.
- In-repo term footprint with `rg`.
- External naming guidance for developer-facing terminology.
- Adjacent LLM prompt-language projects and public usage of `Plang`/`XPrompt`.

## Current SASE Meaning

SASE currently defines xprompts as reusable prompt templates with optional typed inputs and Jinja2 support. They are
referenced by `#name`, can compose prompt fragments, can declare local helper xprompts, and can fan out into multi-agent
prompts when the body contains top-level `---` separators. Standalone workflows use `#!name`.

The term is already a product-level concept, not just a code label:

- `sase xprompt` exposes `expand`, `explain`, `list`, `graph`, and `catalog`.
- `xprompts:` appears in config, frontmatter, workflow-local helper definitions, and prompt frontmatter.
- `xprompt_aliases` names the pre-expansion alias layer.
- The editor server is branded as the xprompt LSP (`sase-xprompt-lsp`).
- Agent artifacts and UI surfaces expose xprompt metadata.
- Generated skills are sourced from xprompt definitions.
- Docs explicitly distinguish xprompt parts, xprompt workflows, standalone workflows, directives, and multi-agent
  prompts.

Local scan results:

- `xprompt`/`XPrompt` appears in about 697 files.
- The term appears about 6,807 times.
- `plang` has no current in-repo usage.

Again, this does not count against a rename by cost. It shows that the chosen name must carry a broad conceptual load:
template asset, inline reference grammar, workflow adapter, catalog object, UI category, LSP domain, and generated skill
source.

## Naming Criteria

The strongest external naming guidance points in the same direction:

- Microsoft framework naming guidance says names should make immediate sense to developers and convey function.
- Microsoft's general naming guidance favors readability over brevity and discourages nonstandard acronyms unless they
  are widely accepted.
- Google's developer style guidance prioritizes clear, concise language, discourages jargon, and emphasizes user
  understanding.

For this decision, the relevant criteria are:

- **Semantic fit:** Does the term name the thing users manipulate?
- **Scope control:** Does it avoid implying a broader concept than the feature actually owns?
- **Taxonomy fit:** Does it preserve useful distinctions among prompts, xprompts, workflows, directives, and skills?
- **Searchability:** Does it avoid direct collisions in the same problem space?
- **Pronunciation and grammar:** Can users say it naturally in singular, plural, adjective, and command forms?
- **Future extensibility:** Does it leave room for a language-level term if SASE later formalizes the complete prompt
  syntax?

## Case For Plang

There is a plausible case for `plang`:

- It is pronounceable.
- It is shorter than `xprompt`.
- It can be read as "prompt language", which matches the direction SASE has taken: typed inputs, Jinja, recursive
  expansion, directives, workflow-local helpers, command substitution, multi-agent fan-out, and editor language-server
  behavior.
- It may feel more ambitious and less template-specific than `xprompt`.

That argument is strongest if the thing being named is the entire grammar of SASE prompt composition.

## Critique Of Plang

### 1. `plang` Overstates The Concept

Most user operations are not "writing a language"; they are defining or invoking reusable prompt assets. A user saves a
prompt fragment, lists available prompt templates, expands `#name`, or opens a catalog. In those situations, `xprompt`
or "prompt template" maps more directly to the object being manipulated.

`plang` sounds like a language runtime or DSL. That would be a reasonable umbrella for the whole syntax:

- `#name` and `#!name` references
- `%name`, `%wait`, `%model`, and other directives
- xprompt frontmatter
- `xprompts:` local helpers
- workflow YAML
- Jinja and command substitution
- multi-agent segment rules

But using `plang` as the replacement for the asset noun collapses the language and the library item into one word.
`sase plang list` would probably mean "list prompt-language programs", but the command actually lists a mixed catalog
of xprompts and workflows.

### 2. It Weakens The Existing Taxonomy

SASE already has a useful taxonomy:

- **Prompt:** the submitted instruction text.
- **XPrompt:** a reusable, named prompt fragment or inline-capable prompt asset.
- **Workflow:** a YAML multi-step execution graph.
- **Directive:** launch/runtime control syntax.
- **Skill:** generated runtime-facing slash command derived from xprompt metadata.

Renaming `xprompt` to `plang` blurs this. A "plang workflow" is linguistically plausible but unclear: is it a workflow
written in the language, an executable program, or one catalog entry? A "local plang" or "`plangs:` frontmatter key" is
less natural than "local xprompt" / "`xprompts:`".

### 3. External Collisions Are Worse Than XPrompt

`xprompt` is not collision-free. Search results include SASE, an XPrompt multi-LLM app, HCL's historical `xprompt`
file, and academic XPROMPT papers.

`plang` has a more serious collision problem because the collisions are directly in the same category:

- A public `PLang` project describes itself as an LLM-assisted programming language and uses commands like
  `plang build` and `plang run`.
- A 2025 open-access paper is explicitly titled "Plang: Efficient prompt engineering language for blending natural
  language and control flow in large language models" and defines PromptLanguage (Plang) for LLM prompt engineering.
- There is also an older "Plang" logic programming language.

That means SASE adopting `plang` would not simply be competing with a generic name. It would be competing with existing
names for prompt/programming languages.

### 4. It Is An Abbreviation Without Strong Payoff

`plang` compresses "prompt language" or "programming language", but neither expansion is obvious without explanation.
It also invites multiple pronunciations and interpretations:

- "pee-lang"
- "plang" as one syllable
- "prompt language"
- "programming language"

The acronym-like compression saves two characters compared with `xprompt` while losing the literal word `prompt`.

### 5. It Creates Awkward User-Facing Grammar

The current term is clunky but usable:

- an xprompt
- xprompts
- xprompt expansion
- xprompt catalog
- xprompt LSP
- xprompt aliases

`plang` is harder to use naturally:

- a plang?
- plangs?
- plang expansion?
- plang catalog?
- plang aliases?
- plang LSP?

That awkwardness matters because SASE exposes the term in CLI help, docs, UI labels, config keys, artifacts, and blog
posts.

## Adjacent Naming Landscape

The surrounding ecosystem suggests that prompt-language projects either use a descriptive full name or a file-format
brand:

- IBM's Prompt Declaration Language (PDL) names the language explicitly and describes a YAML-based declarative approach
  for prompt structure, validation, model composition, and rule-based systems.
- Microsoft Promptflow's Prompty uses a format noun: `.prompty` is a markdown file with YAML frontmatter and Jinja
  prompt template content.
- SASE's own README says xprompt workflows were influenced by PDL, which strengthens the case for an umbrella term like
  "SASE Prompt Language" if SASE wants to name the full language layer.

The pattern is: use a language name for the whole formalism, and use a concrete format/asset name for reusable files.
`plang` tries to be both.

## Decision Matrix

| Criterion | `xprompt` | `plang` |
| --- | --- | --- |
| Names the reusable prompt asset | Good enough: includes `prompt`; "x" is ambiguous | Weak: sounds like a whole language |
| Names the full prompt syntax | Weak: too asset-specific | Better, but too broad for the asset noun |
| Fits current SASE taxonomy | Strong: already separates prompt, xprompt, workflow, directive, skill | Weak: blurs asset vs language vs workflow |
| Search collision risk | Moderate | High, with direct prompt-language collisions |
| Natural grammar | Acceptable | Awkward in plural/adjective/UI forms |
| Developer clarity | Mixed but learnable | Requires explanation; abbreviation is not self-evident |
| Future extensibility | Good if paired with "SASE Prompt Language" as umbrella | Poor if it consumes the language-level name for one asset |

## Recommended Naming Convention

Keep:

- `xprompt` for reusable prompt assets and the existing catalog/CLI domain.
- `workflow` for YAML multi-step execution graphs.
- `directive` for `%...` launch/runtime controls.
- `skill` for generated runtime-facing slash commands.

Add, if useful:

- **SASE Prompt Language** as the umbrella term for the complete prompt-composition grammar.

That gives SASE a clean two-layer naming model:

- **Language layer:** SASE Prompt Language.
- **Asset layer:** xprompt, workflow, directive, skill.

This preserves the existing domain boundaries while giving the broader syntax a more explicit name.

## Final Answer

I would not rename `sase xprompt` to `sase plang`.

The best version of the idea is not "rename xprompt to plang"; it is "recognize that SASE has a prompt language, and
name that language explicitly." Use **SASE Prompt Language** for the whole grammar if you want that framing, but keep
`xprompt` as the concrete reusable prompt asset and command namespace.

## Sources

- Local: `docs/xprompt.md`
- Local: `docs/workflow_spec.md`
- Local: `src/sase/main/parser_xprompt.py`
- Local: `src/sase/xprompt/models.py`
- Local: `AGENTS.md`
- Microsoft Framework Design Guidelines: <https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/naming-guidelines>
- Microsoft General Naming Conventions: <https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/general-naming-conventions>
- Google Developer Documentation Style Guide word list: <https://developers.google.com/style/word-list>
- IBM Prompt Declaration Language docs: <https://ibm.github.io/prompt-declaration-language/>
- Microsoft Promptflow Prompty docs: <https://microsoft.github.io/promptflow/how-to-guides/develop-a-prompty/index.html>
- PLang project site: <https://plang.is/>
- ScienceDirect Plang paper: <https://www.sciencedirect.com/science/article/pii/S0957417425037339>
- SASE public XPrompt docs: <https://sase.sh/xprompt/>
