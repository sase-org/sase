---
create_time: 2026-06-21 10:22:06
status: done
prompt: sdd/prompts/202606/snippet_reference_syntax.md
---
# Plan: `#[<snippet>]` snippet-reuse syntax

## Summary

Add a new `#[<snippet>]` reference syntax that snippet authors can embed inside a snippet definition to splice in
**another existing snippet**, optionally passing xprompt-style arguments to fill the referenced snippet's tabstop
placeholders (`$1`, `$2`, …). The reference is resolved while the snippet catalog is built, so every snippet consumer
(ACE TUI prompt input, the Python editor helper bridge, and the Rust LSP) sees fully-composed templates.

The feature is implemented in **both Python (`src/sase`) and the Rust core (`sase-core`)** so the LSP and the TUI stay
in parity, per the Rust-core backend boundary rule.

### Decisions already made (from clarifying Q&A)

- **Arg syntax (Q1):** args live _inside_ the brackets — `#[name(a, b)]` / `#[name:a]`. The bracket body (`name` + args)
  is parsed with the **existing** xprompt argument parser, verbatim.
- **Scope (Q2):** full parity — Python _and_ Rust now, with mirrored tests.
- **Missing / cyclic ref (Q3):** leave the `#[ref]` text **literal** (mirrors the existing behavior for unknown nested
  `#name` references; non-destructive and visible).

---

## Motivation / product context

Snippets are currently authored as xprompts with a `snippet:` field (or as raw `ace.snippets` config entries). A snippet
body can already pull in another xprompt's **content** with the bare `#name` syntax, but that composition flattens
everything into final text _before_ tabstops are computed — it cannot reuse another snippet's **tabstop structure**, and
it cannot pass arguments to pre-fill some of those tabstops while leaving the rest interactive.

Authors want to build snippets out of smaller reusable snippets. Example:

```
# snippet "greet":   Hello {{ name }}!          -> template:  Hello $1!$0
# snippet "welcome": #[greet] Welcome to {{ place }}.   (input: place)
```

`#[greet]` should expand to greet's _template_ (`Hello $1!`) embedded inside welcome's template, with tabstops
renumbered so the user can tab through both fields:

```
welcome -> Hello $1! Welcome to $2.$0
```

And with an argument, `#[greet(World)]` pre-fills greet's `$1`:

```
welcome -> Hello World! Welcome to $1.$0
```

This is distinct from the existing `#name`: `#name` composes xprompt **content** (pre-tabstop), while the new `#[name]`
composes another snippet's **template** (post-tabstop, with argument pre-fill).

---

## Current architecture (what exists today)

### Python — `src/sase/xprompt/snippet_bridge.py`

- `get_xprompt_snippet_entries(project)` — for each xprompt with `snippet` set: resolve the trigger, compose nested
  **`#name`** references in the content via `process_xprompt_references_with_catalog(xp.content, xprompts)`, then
  convert to a tabstop template via `_xprompt_to_snippet_template(...)`.
- `_xprompt_to_snippet_template(xp)` — converts `{{ input }}` / legacy `{N}` / `{N:default}` to `$1`, `$2`, … tabstops
  (required inputs in definition order; defaulted inputs pre-filled), appends `$0`, bails (returns `None`) on complex
  Jinja2.
- `get_xprompt_snippets(project)` → `{trigger: template}`.

### Python — argument parsing — `src/sase/xprompt/_parsing_args.py`

- `parse_workflow_reference(ref)` → `(name, positional_args, named_args)` for a reference body _without_ the leading
  `#`, handling `name(a, b)`, `name:a`, `name+`, plain `name`.
- `parse_args(...)`, `find_matching_paren_for_args(...)`, `find_matching_brace_for_args(...)`, and the shared
  `_find_matching_delimiter_for_args(...)` (already skips `"…"`, `'…'`, and `[[…]]` text blocks).

### Python — snippet catalog assembly points (all three merge xprompt + user-config snippets)

1. **ACE TUI:** `src/sase/ace/tui/actions/startup.py::get_snippets` → `get_xprompt_snippets()` then
   `.update(self._user_snippets)`, cached. Consumed by the prompt text-area widget
   (`src/sase/ace/tui/widgets/_snippets.py`).
2. **Editor helper bridge:** `src/sase/integrations/_editor_helper_snippets.py::snippet_catalog_response` →
   `get_xprompt_snippet_entries(...)` + `ace.snippets` user config.

### Rust — `sase-core` crate `sase_core`, `src/xprompt_catalog.rs`

- `load_editor_snippet_catalog(...)` — builds `entries_by_trigger` from `snippet_entry_from_xprompt(...)` for every
  xprompt, then merges `load_user_snippets()` (the `ace.snippets` config). **This is the third assembly point.**
- `snippet_entry_from_xprompt(...)` → `xprompt_to_snippet_template(content, inputs)` — the mirror of the Python
  conversion. Consumed by the LSP server (`crates/sase_xprompt_lsp/src/server.rs`) for editor snippet completions.

### Cross-language parity mechanism

Behavior that must match across Python and Rust is pinned by **parallel literal golden-vector tables** that are required
to agree byte-for-byte — e.g. the VCS-project-completion `_GOLDEN_VECTORS` table in
`tests/test_xprompt_vcs_project_completion.py` and the matching `vcs_project_golden_vectors()` test in `sase-core`
`editor/completion.rs`. We follow this same pattern for snippet references.

---

## Why this resolves cleanly at the template level

`#[name]` is **not** matched by the existing `#name` xprompt pattern: after `#` comes `[`, which is not a valid
name-start character, so the existing `#name` composition pass and `_xprompt_to_snippet_template` both leave `#[…]`
tokens untouched. That lets us add a **new, separate resolution pass that runs after the tabstop template already
exists** — operating on `$N` template strings, exactly the level the author is thinking in ("if the snippet has
placeholders like `$1`").

Operating on template strings is also uniform across both snippet sources (xprompt-derived and `ace.snippets`
user-config), since both end up as `$N` template strings, and it is straightforward to mirror in Rust (whose snippet
path already produces template strings).

---

## Design: `#[<snippet>]` semantics

### Token recognition

- A reference is `#[` … `]`, recognized only where the `#` is preceded by start-of-string, whitespace, or an opening `(`
  `[` `{` `"` `'` — mirroring the existing xprompt reference leading-context guard (so `foo#[bar]` inside a word is
  _not_ a reference).
- The matching `]` is located by a new `find_matching_bracket_for_args(text, start)` helper that reuses the existing
  delimiter-matcher machinery so it skips quoted strings and `[[…]]` text blocks. Note the `[[`-vs-`[` subtlety: `[[…]]`
  text blocks inside the body must be consumed atomically and must not be mistaken for the closing `]`.
- The bracket **body** (everything between `[` and `]`) is parsed with the existing `parse_workflow_reference(body)` →
  `(name, positional_args, named_args)`.

### Argument → tabstop mapping

- **Positional args (primary, fully specified):** the _i_-th positional arg (1-based) replaces every occurrence of `$i`
  in the referenced snippet's template with the literal arg text. Tabstops with no corresponding arg are **kept** (and
  renumbered — see below). This is the must-have behavior and the one the user's `$1` framing describes; both
  `#[name(a, b)]` and `#[name:a]` produce positional args.
- **Named args (secondary / can be deferred):** only meaningful for xprompt-derived targets, where the ordered
  required-input names that became `$1, $2, …` are known. Carry that small `input_names` list alongside each
  xprompt-derived template so a named arg `k=v` maps to the `$N` of input `k`. For user-config targets (no input names)
  named args are ignored. Recommend shipping positional first; named support is a clean, bounded follow-on (or same-PR
  stretch) and should be called out explicitly so the reviewer knows it is intentional.
- Literal-substitution note: an arg value containing a `$` should be inserted so it is **not** re-read as a tabstop
  (escape or otherwise neutralize `$` in substituted arg text).

### Embedding & tabstop renumbering (the crux)

When `#[name(args)]` is replaced by the referenced template fragment:

1. Recursively resolve `name`'s template first (so any `#[…]` inside it is already handled), with cycle protection
   (below).
2. Strip the fragment's trailing `$0` (only the outermost snippet keeps a final `$0`).
3. Apply argument substitution to the fragment's tabstops.
4. Splice the fragment in place of the `#[…]` token, **renumbering tabstops** so the fully composed template uses one
   contiguous, collision-free `$1, $2, …` sequence in left-to-right document order, with a single trailing `$0`.

Renumbering requirements:

- **Mirror tabstops are preserved within a source.** A snippet that repeats `$1` (e.g. `$1 says hi, $1`) keeps both
  occurrences linked after renumbering.
- **Tabstops from different sources never collide.** The outer template's own `$1` and an embedded fragment's `$1` must
  become distinct fields. (Implementation: accumulate a running max-tabstop offset and shift each spliced fragment's
  numbers by it, or equivalently assign new numbers per source during a single left-to-right walk.)
- Worked example: outer `#[greet] Welcome to $1.$0` with greet = `Hello $1!$0` → `Hello $1! Welcome to $2.$0` (no arg)
  or `Hello World! Welcome to $1.$0` (`#[greet(World)]`).

### Missing references and cycles (Q3 → leave literal)

- If `name` is not a known snippet **trigger** in the merged catalog → leave the `#[…]` token literal.
- If resolving `name` re-enters a trigger already on the current resolution stack (direct self-reference `#[foo]` inside
  `foo`, or a mutual `#[a]`↔`#[b]` cycle) → leave the offending `#[…]` token literal and continue. Implement with a
  `visiting` set + memoization of fully-resolved templates.

---

## Where the resolution runs

The resolver must see the **fully merged** catalog (xprompt-derived **and** `ace.snippets` user-config) so a reference
can target any snippet and so user-config snippets can both use and be targeted by `#[…]`. Therefore resolution is
applied once, after the merge, at each of the three assembly points.

Factor a single recursive resolver per language and call it at each site:

### Python

- New helper(s) in `snippet_bridge.py` (e.g. `resolve_snippet_references(catalog: Mapping[str, str]) -> dict[str, str]`,
  plus the per-reference recursion with `visiting`/memo). Add `find_matching_bracket_for_args` to `_parsing_args.py`.
  Reuse `parse_workflow_reference` for the body.
- Call it at:
  - `startup.py::get_snippets` — resolve the merged dict before caching.
  - `_editor_helper_snippets.py::snippet_catalog_response` — after merging user snippets, resolve the
    `trigger → template` map and write resolved templates back into the wire entries.
- Audit any other callers of `get_xprompt_snippets` / `get_xprompt_snippet_entries` to ensure none consume unresolved
  templates without going through a merge+resolve step.

### Rust (`sase-core`)

- Mirror the resolver in `xprompt_catalog.rs` (or a small new `snippet_refs` module), reusing the argument parsing in
  `editor/xprompt_args.rs`.
- Call it in `load_editor_snippet_catalog(...)` after `entries_by_trigger` is fully populated (xprompt + user snippets),
  rewriting each entry's `template`.

### TUI / LSP consumers

No changes needed in the TUI snippet-expansion widget or the LSP completion provider — they already consume final `$N`
template strings; they simply receive resolved ones.

---

## Implementation plan

1. **Python core resolver** — bracket scanner (`find_matching_bracket_for_args`), `#[…]` recognition with the
   leading-context guard, body parsing via `parse_workflow_reference`, positional arg→`$N` substitution, `$0` stripping,
   tabstop renumbering, and recursive resolution with cycle/missing → literal handling. Pure functions, no I/O.
2. **Python wiring** — call the resolver at `startup.get_snippets` and
   `_editor_helper_snippets.snippet_catalog_response`; audit other consumers.
3. **Python named-arg support (optional / clearly-scoped)** — thread `input_names` for xprompt-derived entries and map
   named args to tabstops; ignore for user-config targets.
4. **Rust core resolver** — mirror of step 1 in `sase_core`, reusing `editor/xprompt_args.rs` parsing.
5. **Rust wiring** — call the resolver in `load_editor_snippet_catalog` after the merge.
6. **Shared golden vectors + tests** (see below).
7. **Docs** — update the glossary entry for snippets/xprompt-reference syntax to document `#[snippet]`; update any
   user-facing snippet documentation and the ACE help surface if it lists snippet syntax. Update `cli_rules.md` only if
   any CLI surface changes (not expected).

---

## Testing strategy

- **Cross-language golden-vector table** (the parity contract): a literal table of cases
  `(catalog of trigger→raw-template, input trigger) -> expected resolved template`, duplicated in a Python test and a
  matching Rust test, required to agree byte-for-byte. Mirror the existing `_GOLDEN_VECTORS` /
  `vcs_project_golden_vectors()` pattern.
- Cases to cover in the table:
  - Reference with no args; reference filling all tabstops; reference filling some tabstops (remaining kept +
    renumbered).
  - Collision case proving renumbering (outer `$1` + embedded `$1` → distinct fields).
  - Mirror-tabstop preservation across renumbering.
  - Multiple `#[…]` in one template.
  - Nested `#[a]`→`#[b]`→ leaf.
  - Missing trigger → literal; self-cycle → literal; mutual cycle → literal.
  - `#[name:a]` colon form; `#[name(a, [[multi, line]])]` text-block arg (verifies the bracket scanner skips `[[…]]`).
  - `#[…]` referencing a user-config (`ace.snippets`) snippet and vice versa.
  - Interaction with the existing `#name` content composition (both present in one body).
- **Python unit tests** in `tests/test_xprompt_snippet_bridge.py` (extend; keep the existing `#name`-composition and
  unknown-literal tests passing) plus parser tests for `find_matching_bracket_for_args`.
- **Rust unit tests** in `xprompt_catalog.rs` mirroring the conversion/resolution cases.
- **Helper-bridge / LSP** integration coverage that the catalog responses now contain resolved templates.
- Run `just check` (after `just install`) in the `sase` repo; run the `sase-core` crate tests for the Rust side.

---

## Edge cases & rules

- `#[…]` survives the existing `#name` pass and `_xprompt_to_snippet_template` untouched; the new pass is strictly
  additive.
- Only one final `$0` in the composed template; embedded fragments' `$0` are stripped.
- Arg text containing `$` must not be reinterpreted as a tabstop.
- Resolution targets snippets by **trigger** (the same key the catalog is keyed on), not by xprompt name.
- Trigger-collision precedence in the catalog is unchanged; resolution runs against the post-merge map.

---

## Pre-existing divergence discovered (flag for a decision — not silently bundled)

Python's `get_xprompt_snippet_entries` composes nested **`#name`** references in a snippet body (via
`process_xprompt_references_with_catalog`) before tabstop conversion; the Rust `snippet_entry_from_xprompt` does **not**
— it calls `xprompt_to_snippet_template` on raw content. So Python and Rust snippet templates already diverge today
whenever a snippet body contains a bare `#name`.

This is **independent** of the new `#[name]` feature (the new resolver reaches full Python/Rust parity on its own, since
it runs over the template catalog). Recommend an explicit decision:

- **(A)** Also port the `#name` content-composition step to the Rust snippet path now, so all snippet behavior is in
  parity in one coherent change (aligns with the Q2 "full parity" intent); or
- **(B)** Track it as a separate follow-up bead.

---

## Out of scope / possible follow-ups

- Changing how the existing bare `#name` composition works.
- New editor **autocompletion** for `#[…]` (offering snippet triggers after `#[`); this plan covers _resolution_ only.
  Completion UX can be a follow-up.
- Recursion/iteration limits beyond cycle detection (the recursion is bounded by the visiting set).
- Named-arg support may be deferred per the scoping note above.

## Risks

- Tabstop renumbering is the subtle part (mirror preservation + cross-source uniqueness); the golden vectors are the
  guard.
- Three assembly points must all apply resolution or the surfaces drift; the audit step and the helper-bridge/LSP
  integration tests guard against that.
- The bracket scanner must handle `[[…]]` text blocks correctly to avoid truncating args at the wrong `]`.
