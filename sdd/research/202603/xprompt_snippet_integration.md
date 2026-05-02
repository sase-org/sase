# XPrompt-Snippet Integration Research

## Problem Statement

Snippets and xprompts are two separate expansion systems with overlapping purpose but different triggers:

- **Snippets**: Defined in `ace.snippets` config, expanded inline in the editor via `Tab` key. Simple
  `trigger -> template` mappings with `$0`/`$1`/`$2` tabstop markers.
- **XPrompts**: Defined as `.md` files (xprompt parts) or `.yml` files (workflows), expanded at prompt submission time
  via `#name` syntax. Support typed inputs, Jinja2 templates, namespacing, and recursive expansion.

The goal is to make xprompts that can be expanded (specifically xprompt parts — simple text templates) also expandable
inline in the editor like snippets are, so that typing `foo<Tab>` could expand an xprompt part named `foo`.

### Why Not Workflows?

YAML workflows cannot be meaningfully expanded inline because they have multi-step execution pipelines (bash, python,
agent steps), conditional logic, loops, and pre/post steps. They require the workflow executor runtime. Only xprompts
that satisfy `is_simple_xprompt()` (single `prompt_part` step, no pre/post steps) are candidates for inline expansion.

## Current System Comparison

| Aspect             | Snippets                        | XPrompt Parts                                                          |
| ------------------ | ------------------------------- | ---------------------------------------------------------------------- |
| **Storage**        | `ace.snippets` in sase.yml      | `.md` files in `xprompts/` dirs, sase.yml `xprompts:` section, plugins |
| **Trigger**        | `word<Tab>` in editor           | `#name` at submission                                                  |
| **Arguments**      | None (pure templates)           | Typed `InputArg` list with validation                                  |
| **Placeholders**   | `$0`, `$1`, `$2` (tabstops)     | `{{ var }}` (Jinja2), `{1}` (legacy)                                   |
| **Cursor control** | Yes (tabstop cycling)           | No (not editor-aware)                                                  |
| **Recursion**      | No                              | Yes (xprompts can reference other xprompts)                            |
| **Indentation**    | Auto-indents continuation lines | N/A                                                                    |
| **Namespace**      | Flat                            | Hierarchical (`project/name`)                                          |

### Key Tension: Arguments vs Tabstops

The fundamental difference is that xprompt parts have **named, typed arguments** (`{{ file_path }}`) while snippets have
**anonymous tabstops** (`$1`, `$2`). An xprompt like:

```markdown
---
name: split
input: { file_path: path, max_lines: { type: int, default: 500 } }
---

Split `{{ file_path }}` into files of at most {{ max_lines }} lines.
```

...needs `file_path` and `max_lines` to produce useful output. Snippets have no mechanism for named arguments — they
just place the cursor at numbered positions.

## Approaches

### Approach A: Auto-Register XPrompt Parts as Snippets

Convert xprompt parts into snippet entries automatically at load time. Each xprompt input becomes a numbered tabstop.

**Mechanism:**

1. At app startup (when `AceApp._snippets` is populated), also load all xprompts via `get_all_xprompts()`.
2. For each xprompt with no inputs or only inputs with defaults, generate a snippet template:
   - No inputs: register content as-is, appending `$0` at the end.
   - With inputs: replace `{{ arg_name }}` with `$N` tabstops (ordered by input position). Default values become tabstop
     defaults (`${N:default_value}`).
3. Merge into `_snippets` dict (user-defined snippets take precedence on collision).

**Example conversion:**

```markdown
---
name: review
input: { file_path: path }
---

Review {{ file_path }} for correctness and style.
```

Becomes snippet: `Review $1 for correctness and style.$0`

And for an xprompt with a default:

```markdown
---
name: split
input: { file_path: path, max_lines: { type: int, default: 500 } }
---

Split `{{ file_path }}` into files of at most {{ max_lines }} lines.
```

Becomes snippet: `Split \`$1\` into files of at most ${2:500} lines.$0`

**Pros:**

- Zero new infrastructure — reuses the existing snippet expansion pipeline entirely.
- User gets familiar Tab-based expansion with tabstop cycling for free.
- Clean separation: xprompts remain the source of truth, snippets are a derived view.
- Xprompts without inputs "just work" as simple text expansions.

**Cons:**

- **Loses type validation.** Snippet tabstops don't enforce `path`, `int`, `bool` types. The user can type anything into
  a `$1` position. (Mitigated: validation still happens if the same xprompt is used as `#name(...)` at submission.)
- **Loses named arguments.** The user sees `$1`, `$2` — not `file_path`, `max_lines`. Context is lost.
- **Namespace collision.** XPrompt names like `sase/docs` contain `/` which isn't a valid snippet trigger word
  character. Would need to flatten namespaced names (e.g., `sase_docs`) or only register non-namespaced xprompts.
- **Jinja2 complexity.** XPrompts with conditionals (`{% if %}`) or complex Jinja2 beyond simple `{{ var }}`
  substitution can't be meaningfully converted to snippets.
- **Recursive xprompts.** An xprompt that references `#other_xprompt` inside its content can't be fully expanded at
  snippet registration time because that requires the full processor pipeline.

### Approach B: Expand XPrompts Inline via the Tab Key (Fallback After Snippet Lookup)

Add xprompt resolution as a fallback in `_try_expand_snippet()`. When Tab is pressed and no snippet matches, check if
the trigger word matches an xprompt name and expand it inline.

**Mechanism:**

1. In `_try_expand_snippet()`, after the snippet lookup fails, call `get_all_xprompts()` and check if the trigger word
   matches an xprompt name.
2. If the xprompt has **no required inputs** (all have defaults or no inputs at all), expand it inline using
   `process_xprompt_references()` to get the fully resolved text (handling recursion, Jinja2, defaults).
3. If the xprompt has **required inputs**, insert the `#name()` reference with cursor positioned inside the parens
   (prompting the user to fill in args), or open a small input modal.
4. Replace the trigger word with the expanded content.

**Example flow (no required inputs):**

```
User types: review<Tab>
→ No snippet "review" found
→ XPrompt "review" found, no required inputs
→ Expand via process_xprompt_references("#review")
→ Insert: "Review the code for correctness and style."
```

**Example flow (required inputs):**

```
User types: split<Tab>
→ No snippet "split" found
→ XPrompt "split" found, has required input file_path
→ Insert: "#split()" with cursor between parens
   OR open a small input modal asking for file_path
```

**Pros:**

- **Full xprompt semantics preserved.** Recursion, Jinja2, type validation all work because expansion goes through the
  real processor.
- **Handles nested references.** An xprompt that references `#other` inside it will be fully expanded.
- **Graceful degradation.** XPrompts with required args get inserted as `#name()` references that will be expanded at
  submission time — nothing is lost.
- **No conversion layer.** No need to translate between Jinja2 and tabstop syntaxes.

**Cons:**

- **No tabstop cycling.** Unlike snippets, the expanded text has no `$1`/`$2` markers. The user can't Tab through
  argument positions. For xprompts with defaults that got auto-filled, the user would need to manually edit if they want
  different values.
- **Performance.** `get_all_xprompts()` loads from filesystem on every call. Would need caching to avoid lag on Tab
  press. (The loader already has some caching but it's worth confirming.)
- **Ambiguity for xprompts with args.** The fallback of inserting `#name()` is useful but creates a different UX from
  snippet expansion — the user expects text, but gets a reference they need to fill in.
- **Namespace handling.** Same issue as Approach A — namespaced names can't be typed as trigger words.

### Approach C: Hybrid — Convert Inputs to Tabstops, Expand via Processor

Combine Approach A's tabstop UX with Approach B's full processor semantics. Generate snippet-like templates from
xprompts but use the xprompt processor for the base expansion, then overlay tabstop markers.

**Mechanism:**

1. When Tab triggers on an xprompt name, first run `process_xprompt_references()` to expand nested `#refs` and resolve
   defaults.
2. For any remaining `{{ input_name }}` placeholders (required inputs that have no values), replace them with `$N`
   tabstop markers ordered by the xprompt's input list.
3. Insert the resulting text using the snippet expansion machinery (tabstop tracking, cursor positioning).

**Example:**

XPrompt `split` has inputs `file_path` (required) and `max_lines` (default: 500). After processor expansion with
defaults applied:

```
Split `{{ file_path }}` into files of at most 500 lines.
```

The `{{ file_path }}` placeholder remains because it's required. Replace with tabstop:

```
Split `$1` into files of at most 500 lines.$0
```

Insert via snippet machinery. User tabs to `$1`, types the path, tabs to `$0` (end).

**Pros:**

- **Best of both worlds.** Recursive expansion and Jinja2 handled by the processor; cursor UX handled by snippet
  tabstops.
- **Named → positional is transparent.** The input ordering in the xprompt definition determines tabstop order, which is
  intuitive.
- **Defaults are pre-filled.** Only truly required inputs become tabstops.
- **Type validation possible.** Could validate tabstop values on `Tab` advance using the xprompt's `InputArg` type info
  (future enhancement).

**Cons:**

- **New code path.** Requires a new "partial expansion" mode in the processor, or a post-processor that identifies
  unfilled placeholders. The current processor either fully expands or errors — it doesn't leave `{{ var }}`
  placeholders in output.
- **Jinja2 ambiguity.** Not all `{{ ... }}` are simple variable references — some are Jinja2 expressions
  (`{{ count + 1 }}`). Distinguishing expandable input placeholders from computed expressions is non-trivial.
- **Tabstop default syntax.** Would need to support `${N:default}` syntax in the snippet engine (currently only `$N` is
  supported — `${N:default}` was deferred to Phase 2 in the snippet implementation).

### Approach D: Unified Trigger Namespace with Explicit Opt-In

Rather than automatically making all xprompts expandable as snippets, let xprompt authors opt in to snippet expansion
with a `snippet` (or `trigger`) field in the frontmatter.

**Mechanism:**

Add an optional `snippet: true` (or `snippet: <trigger_word>`) field to xprompt `.md` frontmatter:

```markdown
---
name: review
snippet: true
input: { file_path: path }
---

Review {{ file_path }} for correctness and style.
```

Or with a custom trigger word:

```markdown
---
name: sase/review_code
snippet: rv
---

Review the code for correctness and style.
```

At load time, xprompts with `snippet: true` or `snippet: <word>` are registered into the snippet system using Approach
A's conversion logic (inputs → tabstops). The trigger word defaults to the xprompt name (sans namespace) or the explicit
value.

**Pros:**

- **Explicit control.** Not every xprompt makes sense as a snippet (e.g., xprompts with complex Jinja2, or ones meant to
  be composed via `#name` only). Opt-in avoids polluting the snippet namespace.
- **Custom triggers.** Allows short trigger words (`rv` instead of `review_code`) which is important for editor
  ergonomics.
- **Clear expectations.** If an xprompt author marks it as `snippet: true`, they're signaling that it works well as an
  inline expansion.
- **No ambiguity.** The `snippet` field clarifies that this xprompt is designed for both `#name` expansion and `Tab`
  expansion.

**Cons:**

- **Requires author action.** Existing xprompts don't benefit until someone adds the `snippet` field. Discovery is not
  automatic.
- **Schema change.** New frontmatter field needs to be parsed, validated, and documented.
- **Still has the conversion limitations** from Approach A (loses type validation, Jinja2 complexity limits).

## Analysis

### Feasibility Matrix

| Approach                           | Complexity | UX Quality         | Xprompt Coverage               | Risk   |
| ---------------------------------- | ---------- | ------------------ | ------------------------------ | ------ |
| **A: Auto-register as snippets**   | Low        | Good (tabstops)    | Partial (simple xprompts only) | Low    |
| **B: Inline via processor**        | Medium     | Fair (no tabstops) | Full (all expandable xprompts) | Medium |
| **C: Hybrid processor + tabstops** | High       | Excellent          | Full                           | High   |
| **D: Opt-in with snippet field**   | Low-Medium | Good (tabstops)    | Author-controlled              | Low    |

### Key Observations

1. **Most xprompt parts are simple.** Looking at the codebase, many xprompt parts have zero or one input. The complex
   Jinja2 / multi-input cases are the minority. A solution that handles the simple majority is high-value even if it
   doesn't cover every edge case.

2. **`#name` expansion still works.** Even if an xprompt is also available as a snippet, users can still use
   `#name(...)` syntax in the prompt for the full processor expansion with argument validation. Snippet expansion is an
   ergonomic shortcut, not a replacement.

3. **Snippet tabstops already support `$1`-`$N`.** The Phase 1 snippet implementation already supports multi-field
   tabstops with Tab cycling. The `${N:default}` syntax (Approach C's requirement) is not yet implemented but is a
   natural Phase 2 addition.

4. **Namespace flattening is solvable.** For snippet triggers, namespaced xprompts (`sase/docs`) can be registered with
   the flat name (`docs`) if there's no collision, or with underscore flattening (`sase_docs`). The `snippet: <word>`
   override in Approach D elegantly sidesteps this entirely.

5. **The xprompt select modal (`#@`) already bridges the gap.** Users can type `#@` to open a fuzzy-search modal that
   lists all xprompts and inserts the selected `#name` reference. Snippet expansion would be a faster path for
   frequently-used xprompts — complementary, not competing.

## Recommendation: Approach D (Opt-In) with Approach A Mechanics

**Start with Approach D** as the primary solution, using Approach A's conversion mechanics under the hood.

### Why This Combination

- **Low risk, low complexity.** The snippet expansion pipeline already exists and handles tabstops. Adding
  xprompt-derived entries to the snippet registry is straightforward.
- **Explicit > implicit.** Automatically registering all xprompts as snippets would pollute the Tab-expansion namespace
  with entries that weren't designed for inline use (e.g., xprompts that are only meaningful as embedded `#name`
  references in larger prompts). Opt-in via `snippet: true` gives authors control.
- **Custom triggers are important.** XPrompt names are often verbose (`sase/review_code_for_style`). Snippet triggers
  need to be short (`rv`). The `snippet: <word>` syntax supports this naturally.
- **Preserves both expansion paths.** An xprompt with `snippet: true` is expandable via both `word<Tab>` (inline,
  simplified) and `#name(args)` (at submission, full semantics). No functionality is lost.
- **Natural upgrade path.** If we later want automatic registration (Approach A) or hybrid processor expansion (Approach
  C), the `snippet` field provides the metadata to know which xprompts should participate.

### Sketch of Implementation

1. **Parse `snippet` field in frontmatter** (`loader_parsing.py`). Add optional `snippet: bool | str` to `XPrompt`
   model.
2. **At TUI startup, generate snippet entries from xprompts.** In the same place `AceApp._snippets` is populated from
   config, also load xprompts with `snippet` field and convert their content to snippet templates (inputs → tabstops).
3. **Handle namespace and collisions.** User-defined snippets in `ace.snippets` always win. Xprompt-derived snippets use
   the custom trigger word if specified, else the xprompt name (sans namespace prefix).
4. **Conversion rules:**
   - Inputs with `default=UNSET` (required) → `$N` tabstop
   - Inputs with a default value → `${N:default_value}` (requires `${N:default}` tabstop support, or pre-fill the
     default and skip the tabstop)
   - `{{ var }}` Jinja2 references for inputs → replaced with tabstop markers
   - `{{ expr }}` non-input Jinja2 → left as literal text (or warn/skip this xprompt)
   - Append `$0` at end if not otherwise placed
5. **For xprompts with only non-input Jinja2 or no inputs**, expand content fully and register as a plain snippet (no
   tabstops needed beyond `$0`).
