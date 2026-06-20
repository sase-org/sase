---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Research: Should `%` Directives Be Merged Into `#` XPrompts?

## Question

SASE has two in-prompt extension mechanisms:

- **Directives** (`%model`, `%wait`, `%name`, …) — closed-vocabulary control tokens.
- **XPrompts** (`#foo`, `#gh:sase`, `/sase_plan`, `.yml` workflows) — open-vocabulary content/automation tokens.

Should directives be migrated into the xprompt system so the two become one feature? This document assesses the idea
**purely on architectural merit, as if building from scratch** — migration cost is explicitly excluded from the
trade-off analysis (per request). It ends with a recommended solution.

> **TL;DR.** "Merge" conflates three separable questions. Merging the *substrate* (lexer, reference model, completion,
> LSP) is correct and ~70% already done. Merging the *orchestration band* (the `%wait`/`%repeat`/`%alt` directives with
> `.yml` workflows) onto one IR is correct and already underway in the Rust core. Merging the *semantic category* —
> making a directive "just an xprompt" — is **not** correct: directives and content-xprompts sit on opposite sides of a
> control-plane / data-plane boundary, with closed-vs-open vocabularies and different output types. **Recommendation:
> share the plumbing, keep the meaning distinct.**

---

## 1. What each system actually is

### Directives — the control plane

A directive is a `%`-prefixed token that is **extracted and stripped from the prompt before the LLM ever sees it**. It
configures *how the agent runs* — it is never content.

- **Closed vocabulary, defined in code.** `_KNOWN_DIRECTIVES` is a 10-element `frozenset`
  (`src/sase/xprompt/_directive_types.py:20`): `approve, edit, epic, hide, model, name, group, repeat, time, wait`,
  plus single-letter aliases (`%m`, `%w`, `%n`, …).
- **Output is a struct, not text.** Parsing yields a `PromptDirectives` dataclass
  (`_directive_types.py:52`) consumed by the runner/orchestrator (`extract_prompt_directives()` in
  `src/sase/xprompt/directives.py`). Consumers include `agent/names/_resume.py`, `history/prompt_metadata.py`,
  `llm_provider/preprocessing.py`, and the agent-launch path.
- **Each directive carries bespoke imperative logic.** `%time` parses `5m`/`1h30m`/`yymmdd/HHMM`
  (`_directive_time.py`); bare `%wait` resolves to the most-recent agent; `%name:foo-@` allocates an indexed suffix;
  `%model(a,b)` rewrites to `%alt(%model:a,%model:b)` and fans out (`_directive_alt.py`). None of this is expressible as
  data — it is engine behavior.
- **Declarative & composable.** Multiple directives on one prompt all apply; there is no control flow.

### XPrompts — the data / content plane

An xprompt is a `#`-prefixed token that is **expanded inline into the prompt text the LLM (or a workflow executor)
consumes**.

- **Open vocabulary, defined in data.** Authored as `.md`/`.yml` files discovered across a 9-level priority chain (CWD
  → home → project → config → plugins → built-ins), or in `sase.yml`. Users and plugins add new ones with **no engine
  changes** (`src/sase/xprompt/loader.py`, `loader_sources.py`).
- **Output is text or workflow steps.** A `.md` xprompt expands to a `prompt_part`; a `.yml` xprompt is a multi-step
  `Workflow` (`agent`/`bash`/`python`/`prompt_part` steps, `for`/`while`/`repeat` loops, `if:` conditions, `parallel`,
  `finally`) executed by `workflow_executor.py`.
- **Uniform, typed argument model.** `InputArg`/`InputType` (`word|line|text|path|int|bool|float`) with defaults and
  Jinja2 substitution — one grammar for all xprompts (`src/sase/xprompt/models.py`).
- **Skills and VCS tags are xprompt sub-roles.** `skill: true` exposes an xprompt under `/name`; `tags: [vcs]` makes
  `#gh:sase` switch workspaces.

### The clean contrast

| Dimension | Directive (`%`) | XPrompt (`#` / `/`) |
|---|---|---|
| Reaches the LLM? | **No** — stripped out | **Yes** — expanded in |
| Vocabulary | Closed, code-defined (10) | Open, data-defined (∞) |
| Extensible by users/plugins | No (needs engine code) | Yes (drop a file) |
| Output | `PromptDirectives` struct | Prompt text / workflow steps |
| Consumer | Orchestrator / runner | LLM / workflow executor |
| Argument model | Bespoke per directive | Uniform typed `InputArg` |
| Failure mode | Engine can't honor unknown `%x` | Unknown `#x` is just inert/diagnostic |

This table is the core of the analysis: **directives and content-xprompts are not two flavors of one thing — they are
opposite sides of a configure-the-run vs. produce-the-content boundary.**

---

## 2. The dichotomy is fuzzy in the middle (the honest counter-argument)

The clean split above holds at the *extremes*. It blurs in an **orchestration band** where both systems already overlap,
and this is what makes the merge question reasonable rather than naive:

- **XPrompts already have side effects.** `#gh:sase` switches workspaces; `.yml` workflows run `bash`/`python`. So
  "xprompts are pure content" is not strictly true — they span content → automation → side-effects.
- **Directives already do orchestration.** `%wait` is a dependency edge, `%repeat:3` is a loop, `%alt(...)` is a
  fan-out, `%model(a,b)` is parallel dispatch. These are exactly the primitives `.yml` workflows express as
  `repeat:`/`for:`/`parallel:`/step-ordering.
- **They already cross-reference.** `#fork:<name>` implies `%wait:<name>` (commit `e64a9ebf1`) — an xprompt injecting a
  directive.

So there are really **two overlaps, not one**, and they point in different directions:

1. **Directive ↔ Workflow** (orchestration band) — *genuine, deep overlap.* Both describe agent graphs.
2. **Directive ↔ content-XPrompt** (the literal "merge directives into xprompts" proposal) — *shallow overlap.* One
   configures the run and is stripped; the other is text for the model.

The merge proposal as literally stated targets overlap #2 (the shallow one). The real architectural pressure is overlap
#1 (the deep one). Conflating these is the central trap.

---

## 3. Why a literal semantic merge is the wrong cut

Making a directive "just a kind of xprompt" fails on four independent grounds:

1. **Closed vs. open is load-bearing, not incidental.** A directive *works only because the engine has code to honor
   it* — to parse a duration, resolve a bare wait, allocate an indexed name, fan out models. An xprompt's entire value
   proposition is the opposite: it is inert data requiring no engine code. Pour directives into the xprompt data model
   and you must either (a) discard their bespoke logic, or (b) bolt an imperative/plugin escape hatch onto xprompts —
   at which point you have merely relocated the closed set into the xprompt namespace and bought ambiguity, not
   simplicity. "User-defined directives" remains illusory either way: the scheduler still cannot honor a `%foo` it has
   no code for.

2. **Strip-vs-expand cannot be unified at the value level.** The defining act of a directive is *removal* from the text;
   the defining act of an xprompt is *insertion* into it. A merged token type would need a per-instance flag for "am I
   text or am I config?" — which is just the `%`/`#` distinction wearing a disguise.

3. **The sigil encodes the type — that is a feature.** `%` = configures the run, invisible to the model. `#` = becomes
   content the model reads. `/` = invokes a skill. A reader (and the LSP) can tell *at a glance* whether a token mutates
   their prompt text or their run configuration. Collapsing to one sigil destroys a real, daily-used signal and forces
   disambiguation by lookup.

4. **Different output types want different validation/diagnostics.** Directive errors are run-configuration errors
   ("unclosed `%alt`", "duration mixed with absolute time"); xprompt errors are template/IO errors ("unknown
   reference", "missing required input"). A merged type muddies both.

The marginal upside of a literal merge — "one mental model, one parser" — is largely **already achievable without
merging the semantics** (next section).

---

## 4. The substrate is *already* the right shape — and already mostly shared

The most important finding: from-scratch, the ideal architecture is **one shared parsing/completion/editor substrate
with discriminated token kinds**, and the Rust core has already converged on exactly that.

`crates/sase_core/src/editor/` is a single framework over *all* prompt tokens:

- `token.rs` — one lexer: `extract_token_at_position`, `is_xprompt_like_token`, `is_slash_skill_like_token`,
  `is_vcs_project_trigger_token`, plus directive recognition.
- `completion.rs` — one completion engine whose `CompletionContextKind` enumerates **`Xprompt`, `SlashSkill`,
  `VcsProject`, `DirectiveName`, `DirectiveArgument`, `XpromptArgumentName/Path/Value`** as *kinds within one model*.
- `directive.rs` — the directive vocabulary as a `const DIRECTIVES: &[DirectiveMetadata]` (13 entries: `model, name,
  wait, time, approve, edit, plan, epic, hide, group, repeat, alt, xprompts_enabled`).
- `diagnostics.rs`, `hover.rs`, `definition.rs`, `frontmatter.rs` — shared across both token families.

The TUI mirrors this: commit `27258f105` generalized the menu opener to
`_try_auto_prompt_reference_completion()` (`src/sase/ace/tui/widgets/_file_completion_open.py`), dispatching `%`/`#`/`/`
through one path while keeping a branch (and an independent setting) per kind. **This generalized the *presentation*,
not the *semantics*** — which is precisely why the menu unification can create the *impression* that the features are
collapsing into one when architecturally they are not.

And the orchestration band is converging too: `crates/sase_core/src/agent_launch/mod.rs` already parses
`%model` fan-out, `%alt` splitting, and `%wait`-for-previous at launch time (`directive_occurrences`,
`alt_directive_starts`, `has_wait_directive`). Orchestration-relevant directive parsing is **already migrating into the
core's agent-launch IR**, next to where workflows are planned.

**Conclusion from the codebase itself:** the substrate-merge answer (shared plumbing, distinct kinds) is not
hypothetical — it is the de facto direction. The literal semantic-merge answer is contradicted by the very modules that
would have to implement it.

### The one real smell: a duplicated closed grammar

The directive vocabulary is implemented **twice**: Python (`_KNOWN_DIRECTIVES` = 10 entries, plus the runtime
extractor/validators in `directives.py`/`_directive_time.py`/`_directive_alt.py`) **and** Rust (`editor/directive.rs`
`DIRECTIVES` = 13 entries, plus `agent_launch` parsing). The lists have already drifted — Rust still lists `plan`,
`alt`, and `xprompts_enabled`; Python's runtime set does not (legacy `%plan` was removed in `58b44e2d8`). This is the
same parity hazard the glossary flags for `vcs_project_completion` (kept in sync by golden vectors).

This smell argues for consolidation — but toward **"one directive parser in Rust core, bound from Python"**
(per `memory/rust_core_backend_boundary.md`: directive parsing is cross-frontend backend logic). It does **not** argue
for "directives become xprompts."

---

## 5. Options & trade-offs

### Option A — Full semantic merge (directive ≡ a kind of xprompt)
- **Pros:** single sigil/mental model; single catalog; nominal "custom directives."
- **Cons:** breaks control/data-plane separation (§3.1–3.2); needs an imperative escape hatch in the xprompt data model
  to host bespoke logic; "user-extensible directives" stays illusory (orchestrator still needs code per directive);
  loses sigil-as-type signal; muddies validation. **Net: more complexity, weaker guarantees, marginal real gain.**

### Option B — Status quo: two fully independent stacks
- **Pros:** clean separation; each optimized for its job.
- **Cons:** ignores the genuinely shared substrate; perpetuates the duplicated directive grammar (Python + Rust) and
  duplicated completion logic; handles the directive↔workflow overlap by ad-hoc special cases (`#fork`⇒`%wait`).

### Option C — Shared substrate, distinct semantics  ✅ recommended
- One reference/lexer/completion/LSP/diagnostics framework with a discriminated `kind` (directive | xprompt | skill |
  vcs-project) — i.e., finish what `editor/` started; one canonical directive grammar+vocabulary owned by Rust core,
  with Python binding it and **deleting its duplicate**; keep `%`/`#`/`/` as distinct, meaningful sigils.
- **Pros:** removes the real duplication; keeps the meaningful type distinction; matches the de facto direction and the
  Rust-core boundary rule; lets each surface keep optimal ergonomics.
- **Cons:** requires disciplined layering (substrate vs. semantics) so the shared plumbing does not leak kind-specific
  assumptions.

### Option D — Unified orchestration IR with two surface syntaxes  ✅ recommended (forward-looking, complements C)
- Treat **inline directives and `.yml` workflows as two front-ends lowering to one orchestration / agent-spec IR** in
  the core. `%repeat:3` ≅ workflow `repeat:`; `%alt(...)`/`%model(a,b)` ≅ fan-out; `%wait` ≅ dependency edge;
  `%model`/`%name`/`%approve`/`%group` ≅ per-agent step attributes. This dissolves the *deep* overlap (#1) cleanly while
  leaving the *shallow* overlap (#2) untouched.
- **Pros:** one place to reason about agent graphs; `#fork`⇒`%wait` stops being a special case and becomes IR
  composition; inline syntax stays terse, file syntax stays expressive. `agent_launch/mod.rs` is already a beachhead.
- **Cons:** the IR must be designed to express both terse-inline and rich-file cases without lowest-common-denominator
  loss.

---

## 6. Recommendation

**Do not migrate directives into the xprompt vocabulary (reject Option A).** A directive and a content-xprompt are not
the same kind of object: one is stripped run-configuration drawn from a closed, engine-honored set; the other is
open, data-defined content the model consumes. The sigil that distinguishes them is carrying real information.

Instead, pursue **Option C now and Option D as the north star** — *merge the plumbing and the orchestration model, keep
the semantic category distinct*:

1. **Unify the substrate (C).** Make `editor/` in `sase-core` the single source of truth for tokenization, reference
   parsing, completion, hover, diagnostics, and definition across `%`/`#`/`/`/`#gh:`. Treat directive / xprompt / skill
   / vcs-project as *kinds* in one model — which is already the shape of `CompletionContextKind`.

2. **De-duplicate the directive grammar.** Promote the canonical directive vocabulary + parser into Rust core and bind
   it from Python, deleting `_KNOWN_DIRECTIVES` / the hand-rolled Python extractor as the *authority* (keep a thin
   adapter). This kills the live Python↔Rust drift (`plan`/`alt`/`xprompts_enabled`).

3. **Converge the orchestration band onto one IR (D).** Continue what `agent_launch/mod.rs` began: lower both inline
   orchestration directives and `.yml` workflow constructs into a shared agent-spec/orchestration IR, so loops,
   fan-out, dependencies, and per-agent attributes have exactly one semantics regardless of surface syntax.

4. **Keep the three sigils as a typed surface.** `%` configures the run (stripped), `#` inserts content (expanded), `/`
   invokes a skill. Preserve this as a deliberate, user-facing type signal.

### Decision rule for "where does a new capability go?"
- Honored by the **orchestrator**, closed/engine-known meaning, never shown to the model → **directive**.
- **Content or reusable template** the model (or a workflow executor) consumes, user/plugin authorable as data →
  **xprompt** (`skill:` if `/`-invokable, `tags:[vcs]` if a workspace tag).
- A **multi-step pipeline** with control flow / non-prompt steps → **workflow** (`.yml` xprompt), lowering to the same
  orchestration IR an inline directive would.

This delivers the genuine wins behind the merge instinct — one parser, one completion model, one orchestration
semantics, no duplicated grammar — without paying the cost of collapsing a meaningful control/data distinction into a
single ambiguous token type.

---

## Appendix — Key source references

**Directives (Python runtime):**
`src/sase/xprompt/_directive_types.py` (`_DIRECTIVE_PATTERN`, `_KNOWN_DIRECTIVES`, `PromptDirectives`),
`src/sase/xprompt/directives.py` (`extract_prompt_directives`), `_directive_time.py`, `_directive_alt.py`,
`src/sase/ace/tui/widgets/directive_completion.py`.

**XPrompts (Python):**
`src/sase/xprompt/models.py` (`XPrompt`, `InputArg`, `InputType`), `processor.py` (expansion),
`loader.py`/`loader_sources.py` (9-level discovery), `workflow_executor*.py`, `multi_agent_xprompt.py`, `tags.py`.

**Shared substrate (Rust core):**
`crates/sase_core/src/editor/mod.rs`, `token.rs`, `completion.rs` (`CompletionContextKind`: `Xprompt`, `SlashSkill`,
`VcsProject`, `DirectiveName`, `DirectiveArgument`, `XpromptArgument*`), `directive.rs` (`DIRECTIVES` const, 13),
`diagnostics.rs`/`hover.rs`/`definition.rs`/`frontmatter.rs`; `crates/sase_core/src/agent_launch/mod.rs`
(runtime `%model`/`%alt`/`%wait` parsing). Rust xprompt LSP: `crates/sase_xprompt_lsp/`.

**Cross-feature & UI convergence:**
TUI dispatcher `src/sase/ace/tui/widgets/_file_completion_open.py` (`_try_auto_prompt_reference_completion`);
commit `27258f105` (menu generalization); commit `e64a9ebf1` (`#fork`⇒`%wait`); commit `58b44e2d8` (removed `%plan`).

**Governing memory:** `memory/rust_core_backend_boundary.md` (cross-frontend parsing belongs in `sase-core`);
`memory/glossary.md` (xprompt / directive definitions; `vcs_project_completion` parity precedent).
