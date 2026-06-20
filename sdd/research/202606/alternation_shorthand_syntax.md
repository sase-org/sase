# Alternation Shorthand Syntax Research

Date: 2026-06-20

## Research Question

SASE currently supports prompt alternation fan-out through:

```text
%alt(A, B, ...)
%(A, B, ...)
```

The long form is clear, but the shorthand `%(...)` is visually weak. It looks like an accidental punctuation sequence,
is hard to search for, and does not carry the "set of alternatives" idea as well as it could. The goal is a better
short-hand syntax that remains compact while preserving current `%alt` behavior.

## Current SASE Constraints

The current behavior to preserve:

- `%alt(...)` and `%(...)` are launch fan-out syntax, not ordinary directive extraction fields.
- Arguments can be arbitrary prompt text, xprompt references, prompt directives, or `[[text blocks]]`.
- Named arguments use `id=value`; the value is inserted into the child prompt, while `id` becomes fan-out metadata and
  can become the child-name suffix.
- A single argument means "with and without this text".
- Multiple alternation points produce a Cartesian product.
- `%model(...)` and repeated scalar `%model` directives are normalized into the same fan-out machinery, so any new
  syntax must compose with model fan-out.

Relevant local implementation points:

- `docs/xprompt.md` documents `%alt`, `%(...)`, named alternatives, single-argument with/without splits, and Cartesian
  products.
- `src/sase/xprompt/_directive_alt.py` is the Python public API, but it delegates actual fan-out planning to
  `sase.core.agent_launch_facade.plan_agent_launch_fanout(...)`.
- `../sase-core/crates/sase_core/src/agent_launch/mod.rs` owns the canonical Rust parser for `%alt`, `%(...)`,
  `alt_id`, model fan-out, and Cartesian product expansion.
- `src/sase/core/agent_launch_wire.py` mirrors the `LaunchFanoutSlotWire.alt_id` field on the Python side.
- Editor support is split: Rust editor metadata treats `%(` as an alias for `%alt`, while the Python ACE directive
  completion code lists canonical directives and needs separate updates for punctuation shorthands.

The most important parser invariant is that live prompt directives are recognized only in directive-like contexts: start
of prompt, after whitespace, or after selected opening punctuation, while fenced code blocks and disabled xprompt regions
are protected. A replacement shorthand should keep that invariant.

## Evaluation Criteria

Good shorthand should be:

1. Readable in normal prompts without requiring the user to remember a private glyph trick.
2. Short enough to be worth using instead of `%alt(...)`.
3. Hard to trigger accidentally in prose, Markdown, JSON, shell snippets, or code fences.
4. Able to preserve the current argument grammar, especially `id=value` and `[[text blocks]]`.
5. Compatible with Cartesian products and model fan-out.
6. Straightforward to implement in both Rust core and Python/editor adapters.
7. Friendly to CLI examples when prompts are quoted, without making unquoted CLI usage catastrophically surprising.

## Prior Art

### Brace Expansion

GNU Bash brace expansion uses comma-separated strings inside braces, preserves left-to-right order, supports nesting,
and is explicitly textual rather than semantically interpreted. That maps closely to SASE's alternation fan-out:
"generate these prompt variants from this text" rather than "parse a runtime expression." See the Bash manual's
brace-expansion section: <https://www.gnu.org/software/bash/manual/html_node/Brace-Expansion.html>.

The downside is also from Bash: unquoted `{a,b}` expands in the shell before SASE sees it. SASE CLI docs already use
single quotes for prompts with shell-active characters, and `%{...}` would need that same guidance.

### Regex and Grammar Alternation

Regular expressions and grammar notations commonly use `|` for alternatives. Python documents `A|B` as matching either
branch, and W3C XML's grammar notation uses `A | B` for alternatives:

- <https://docs.python.org/3/library/re.html>
- <https://www.w3.org/TR/xml/#sec-notation>

This is familiar, but it brings regex-like precedence expectations. It is also a poor fit for SASE prompt text because
`|` is common in Markdown tables, shell pipelines, and prose examples. If `|` became the primary separator, text branches
containing tables or command pipelines would need escaping or text blocks more often.

### Snippet Choice Placeholders

VS Code snippets support choice placeholders such as `${1|one,two,three|}`. That shows another established "choice
list" visual vocabulary: values are comma-separated and enclosed in choice delimiters. See the VS Code snippet docs:
<https://code.visualstudio.com/docs/editing/userdefinedsnippets#_choice>.

That syntax is too heavy for SASE prompt entry, and the numbered placeholder is not useful here. The useful idea is not
the exact spelling, but the fact that comma-separated choices inside an unmistakable delimiter are familiar to editor
users.

## Candidate Syntaxes

### Option A: `%{A, B, ...}`

Examples:

```text
%{#review,#test}
%{sec=#review,perf=#test}
%{[[Focus on correctness]],[[Focus on performance]]}
%{Also check security}
%{Focus on security, Focus on perf} %m(opus, sonnet)
```

Meaning:

- `%{a,b}` is exactly `%alt(a,b)`.
- `%{id=value,...}` is exactly `%alt(id=value,...)`.
- `%{one arg}` keeps the existing with/without split.
- Multiple `%{...}` occurrences participate in the same Cartesian product as `%alt(...)`, `%(...)`, and `%model(...)`.

Pros:

- Best conceptual match to textual fan-out because brace expansion already means "generate variants from a set".
- More readable than `%(...)` while still shorter than `%alt(...)`.
- Keeps `%` as the SASE directive sentinel, avoiding dangerous bare `{...}` detection.
- Keeps comma-separated arguments, so existing named-argument and text-block grammar mostly transfers.
- Visually distinct from normal `%name(...)` directive calls, which helps communicate that this is a fan-out set rather
  than a regular directive argument list.
- Easy to document as "brace alternation" or "brace shorthand".

Cons:

- In unquoted shell CLI usage, `%{a,b}` can be brace-expanded before SASE receives it. The mitigation is to keep showing
  shell examples as `sase run '%{a,b} ...'`, which is already the safer pattern for prompts containing spaces, `#`, `!`,
  parentheses, or `%`.
- Requires a balanced-brace matcher in Rust core rather than reusing the current matching-paren helper unchanged.
- Braces appear in JSON, CSS, Jinja, and code examples, so the parser must keep the same directive-context and
  fenced-block protection rules. The leading `%` sentinel makes accidental matches much less likely than bare braces.

Implementation impact:

- Add `%{` to the Rust core alternation detector in `agent_launch/mod.rs`.
- Add a generic balanced-delimiter helper or extend `find_matching_paren` into `find_matching_delimiter`.
- Reuse `parse_directive_args_with_names(inner)` so `id=value`, comma splitting, text blocks, and numeric ID allocation
  do not fork.
- Update Python `has_alt_directive()` detection and any Python-side quick checks.
- Update Rust editor directive metadata and completion handling so `%{` is recognized as an alternation shorthand.
- Update Python ACE directive completion or tokenization if punctuation shorthand should surface in the TUI completion
  path.
- Add tests in both repos for `%{a,b}`, `%{id=a,b}`, nested with `%m(...)`, fenced/disabled ignored regions, and
  unclosed brace errors.

### Option B: `%[A | B | ...]`

Examples:

```text
%[#review | #test]
%[sec=#review | perf=#test]
%[[[Focus on correctness]] | [[Focus on performance]]]
```

Pros:

- `|` is highly recognizable as "or".
- Square brackets can read as a choice list.
- Avoids Bash brace expansion.

Cons:

- `|` is common in Markdown tables and shell pipelines, so arbitrary branch text would need escaping more often.
- SASE already uses comma-separated argument lists everywhere else; introducing pipe-separated alternation creates a
  second mini-language.
- `[[text blocks]]` inside `%[...]` looks noisy and is easy to miscount visually.
- Named alternatives are less natural with `|` because `id=value | id=value` resembles shell or grammar syntax rather
  than SASE's normal argument syntax.

Implementation impact is larger than Option A if `|` becomes a true separator, because it needs a new splitter rather
than the existing comma-argument parser.

### Option C: `%alt[A, B, ...]`

Examples:

```text
%alt[#review,#test]
%alt[sec=#review,perf=#test]
```

Pros:

- Very clear.
- Avoids overloading function-call parentheses.
- Keeps comma arguments and named IDs.
- Less shell-risky than braces.

Cons:

- Not much shorter than `%alt(...)`.
- Adds another delimiter form for one directive without solving the "I want a shorthand" problem.
- Looks like a directive-specific special case rather than a general shorthand.

This is a reasonable explicit form but a weak shorthand.

### Option D: `%|A|B|...|`

Examples:

```text
%|#review|#test|
%|Focus on security|Focus on perf|
```

Pros:

- Very short for simple alternatives.
- Avoids commas in the common case.

Cons:

- Hard to parse robustly for arbitrary prompt text.
- Branch text containing shell pipelines, Markdown tables, or grammar examples needs escaping.
- Named branch IDs do not have an obvious shape.
- The closing delimiter is visually weak in long prompt lines.
- Editor completion and diagnostics would need a bespoke parser.

This optimizes for character count at the expense of predictability.

### Option E: Bare `{A, B, ...}`

Examples:

```text
{#review,#test}
{sec=#review,perf=#test}
```

Pros:

- Shortest and closest to Bash brace expansion.
- Easy to read for users who know shell expansion.

Cons:

- Too easy to trigger in JSON, CSS, Jinja, Markdown, and ordinary prose.
- Shells will pre-expand unquoted usage.
- No SASE-specific sentinel means the parser would need broad text scanning and many more false-positive guards.
- Existing xprompt/Jinja templates commonly use braces for other purposes.

This should be rejected.

### Option F: Keep `%(...)` As The Only Shorthand

Pros:

- No implementation work.
- Fully backward compatible.
- Keeps using the existing directive argument parser.

Cons:

- The original problem remains: `%(...)` is opaque, hard to search for, and does not visually suggest alternatives.
- Punctuation-only aliases are weaker for docs, completion, and error messages.
- It reads like a malformed `%name(...)` directive rather than a deliberate fan-out set.

This is acceptable as a compatibility alias, but not as the preferred user-facing shorthand.

## Comparison

| Option | Readability | Brevity | Parser fit | Accidental-trigger risk | Main concern |
| --- | --- | --- | --- | --- | --- |
| `%{A,B}` | High | High | High | Medium-low with `%` boundary | Shell brace expansion if unquoted |
| `%[A | B]` | Medium | Medium | Medium-low | Medium | Pipe conflicts and new separator rules |
| `%alt[A,B]` | High | Low | High | Low | Not really shorthand |
| `%|A|B|` | Low-medium | High | Low | Medium | Escaping and diagnostics |
| `{A,B}` | High | Highest | Low | High | No SASE sentinel; shell/code conflicts |
| `%(A,B)` | Low | High | Existing | Low | Opaque |

## Migration Shape

The migration should be additive:

1. Add `%{...}` as the preferred shorthand.
2. Keep `%alt(...)` as the canonical explicit form.
3. Keep `%(...)` indefinitely for backward compatibility with prompt history, docs, user snippets, and existing xprompt
   content.
4. Update docs to show `%{...}` first in shorthand examples and describe `%(...)` as an older alias.
5. Update completion/diagnostics so `%{` is recognized as an alternation opener, but keep `%alt` as the named completion
   candidate.
6. Add CLI docs examples using single quotes around `%{...}` prompts.

There is no need to warn on `%(...)` immediately. It is harmless once supported, and warnings in prompt launch syntax can
be more annoying than helpful. Prefer documentation pressure first.

## Sources

- GNU Bash brace expansion: <https://www.gnu.org/software/bash/manual/html_node/Brace-Expansion.html>
- Python regular expression alternation: <https://docs.python.org/3/library/re.html>
- W3C XML grammar notation: <https://www.w3.org/TR/xml/#sec-notation>
- VS Code snippet choice placeholders: <https://code.visualstudio.com/docs/editing/userdefinedsnippets#_choice>

## Recommended Approach

Implement `%{A, B, ...}` as the new preferred shorthand for `%alt(A, B, ...)`, while keeping both `%alt(...)` and
`%(...)` fully supported.

This gives SASE a shorthand whose visual metaphor matches the behavior: a prompt-local, textual set expansion. It is
short, readable, compatible with named alternatives, and naturally explains Cartesian products. The leading `%` keeps it
inside SASE's directive namespace, which avoids the false-positive problems of bare `{...}`.

The implementation should treat `%{...}` as another spelling of the same alternation directive, not as a new directive
with new semantics. It should reuse the existing argument parser and `alt_id` allocation, participate in the same model
fan-out planner, and update both Rust core and Python/editor quick checks. The docs should show `%{...}` as the
recommended shorthand and note that CLI examples must quote prompts, e.g. `sase run '%{#review,#test} analyze this'`, so
shell brace expansion cannot consume the syntax before SASE sees it.
