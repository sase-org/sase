---
create_time: 2026-04-24 12:28:47
status: done
prompt: sdd/prompts/202604/negative_memory_keywords.md
---
# Plan: Negative Keyword Matches for Memory XPrompts

## Goal

Allow entries in the `keywords` field of a memory xprompt (or auto-discovered `memory/long/*.md` file) to be prefixed
with `!` to mark them as **negative/anti keywords**. A memory should be _excluded_ from the `### DYNAMIC MEMORY` section
when any of its negative keywords match the user's prompt — even if positive keywords also matched.

## Motivation

Today dynamic memory only supports inclusive matching: if any keyword fires, the memory is appended. Some memories are
only helpful in certain subcontexts and actively _unhelpful_ (or misleading) in adjacent contexts that share vocabulary.
For example, a `generated_skills.md` memory might be relevant when the prompt talks about `skill`, but _not_ when the
prompt is about deploying skills via the unrelated `vendor` runtime. Negative keywords give memory authors a cheap way
to carve out exceptions without having to restructure their keyword sets or split a single memory into several narrower
ones.

## User-facing Semantics

Given a memory xprompt with the following frontmatter:

```yaml
---
tags: memory
keywords: [skill, SKILL.md, "commit workflow", "!vendor", "!deprecated"]
---
```

- `skill`, `SKILL.md`, `commit workflow` are **positive** keywords.
- `!vendor`, `!deprecated` are **negative** keywords.

A memory is included in `### DYNAMIC MEMORY` iff:

1. At least one **positive** keyword matches the prompt (same word-boundary, case-insensitive rule as today), AND
2. **No negative keyword** matches the prompt.

Concrete rules:

- A memory whose `keywords` list contains _only_ negative entries can never match (no positive hits possible). This is
  consistent with today's rule that an empty `keywords` list skips the memory. We won't add a warning for this — authors
  can see the effect immediately.
- If the exact same keyword appears both positive and negative in a single entry list, the negative wins. (In practice a
  user wouldn't write this; we just need deterministic behavior.)
- `!` is parsed only at the start of the keyword string. Interior `!` characters are literal (they were already
  supported via `re.escape()`).
- The `!` sigil is _not_ part of the keyword for matching purposes — i.e. `!vendor` matches the word `vendor` in the
  prompt.
- The `YAML` parser will treat `!vendor` as a plain string when quoted. Unquoted `!foo` is a YAML tag directive and will
  error — so the documentation and examples MUST show quoted form: `"!vendor"`.

## Scope

In scope:

- Parsing of `!` prefix for keywords in all three current parse sites:
  1. YAML frontmatter of xprompt `.md` files (`src/sase/xprompt/loader.py::_load_xprompt_from_file`)
  2. YAML frontmatter of auto-discovered `memory/long/*.md` files
     (`src/sase/xprompt/loader.py::_load_memory_long_xprompts`)
  3. Structured xprompt entries in `sase.yml` / default configs
     (`src/sase/xprompt/loader_parsing.py::parse_xprompt_entries`)
- Matching logic update in `src/sase/memory/dynamic.py::generate_dynamic_memory`.
- Exposing the split in the `XPrompt` / `Workflow` models so the matching layer doesn't re-parse sigils.
- Test coverage for: negative-only, mixed, negative overrides positive, case-insensitive, word-boundary still honored,
  quoted vs unquoted YAML.
- Doc update to `memory/short/` or a memory-related doc noting the `!` convention (including the YAML-quoting gotcha).

Out of scope:

- Wildcards, regex keywords, boolean groups (`OR`/`AND`), or nested conditions.
- Per-keyword weighting.
- Surfacing the exclusion reason back to the user (no "would have matched but excluded" annotation — silent exclusion is
  fine).
- Changing the `### DYNAMIC MEMORY` output format.

## Design

### Model shape

We keep `keywords: list[str]` as the **public** schema (per user requirement) but introduce a derived split on the
model. Two viable shapes:

- **Option A (preferred):** Keep `keywords: list[str]` (raw, including `!` prefixes) as the canonical field, and add a
  small helper that returns `(positives, negatives)` split on read. This keeps the serialized form, the model field, and
  the YAML schema all aligned to the raw list — no new fields to maintain, no risk of the two halves going out of sync.
- Option B: Parse at load time into two separate fields (`keywords`, `negative_keywords`) on `XPrompt`/`Workflow`.

**Choose A.** It's a smaller change, has fewer sync points (one list, one parse helper), keeps the schema the user asked
for literally, and matches how the YAML serializes back. The split is only needed at matching time, which is a single
call site.

The helper lives next to the matching logic (`src/sase/memory/dynamic.py`) so that parsing the `!` sigil is colocated
with the rule that consumes it. A keyword is negative iff it starts with `!`; the remainder (after stripping the `!`) is
the keyword text used for regex matching.

### Matching logic

`generate_dynamic_memory` changes from:

```python
hits = [kw for kw in wf.keywords if re.search(..., kw, prompt, ...)]
if hits:
    matched.append(...)
```

to (sketch):

```python
positives, negatives = _split_keywords(wf.keywords)
if any(_keyword_matches(n, prompt) for n in negatives):
    continue  # excluded
hits = [kw for kw in positives if _keyword_matches(kw, prompt)]
if hits:
    matched.append(MatchedMemory(..., keywords_matched=hits, ...))
```

Notes:

- `keywords_matched` on `MatchedMemory` keeps only **positive** hits (the existing semantics describe "why this was
  included"; listing the negatives that _didn't_ fire would be confusing).
- Early-exit on the first negative hit — no need to enumerate all.
- `_keyword_matches` reuses the existing word-boundary, case-insensitive regex. We factor it out to avoid duplication
  between positive/negative branches.

### Parse-time validation

No validation is required at parse time: the model stores the raw strings. One light touch in the two loader paths that
currently check `isinstance(keywords, list)` — we keep the same check; `!`-prefixed strings are still strings, so no
additional work.

### Display / observability

No change to `format_dynamic_memory_section`. If the user wants insight into _why_ a memory was excluded, that's a
future feature (see "Out of scope").

## Files to Touch

Implementation:

- `src/sase/memory/dynamic.py` — add `_split_keywords` / `_keyword_matches` helpers and update `generate_dynamic_memory`
  match loop (lines 131–143).

Docs:

- Add a short note to one of: `memory/short/gotchas.md` (most likely) or a new short doc. Must mention the YAML-quoting
  requirement for `!`-prefixed strings, otherwise users will write unquoted `!foo` and hit a YAML parse error.

Tests (`tests/test_dynamic_memory.py`):

- `!keyword` excludes the memory when prompt contains the negative word.
- `!keyword` is ignored when the negative word is absent (memory still matches via positives).
- Negative-only keyword list never matches.
- Negative match overrides a positive match in the same entry.
- Case-insensitive applies to negative keywords.
- Word-boundary applies to negative keywords (e.g. `!test` doesn't exclude on the word `testing`).
- Frontmatter round-trip: loading an `.md` file with `"!foo"` quoted in the YAML list preserves the `!` through to the
  model.
- Config-entry round-trip: same for `parse_xprompt_entries`.

No schema tests exist today for `memory/long/*.md` negative keywords specifically, so we'll add one there as well (uses
the loader path at `loader.py:455`).

## Risks & Mitigations

- **YAML parsing gotcha:** Unquoted `!foo` is a YAML tag. If a user writes `keywords: [!deprecated]` they'll see a
  loader error rather than silent misbehavior — but it's an error in an unexpected place. Mitigation: call this out
  explicitly in the docs change and in any example we ship.
- **Keyword `"!"` alone:** A single `!` would parse as negative keyword with empty text, producing an empty regex that
  matches everywhere and excludes the memory unconditionally. We'll skip empty (post-strip) keywords in the split helper
  so this degenerate case is a no-op, not a footgun. Add a test.
- **Existing memories unaffected:** No existing keyword starts with `!`, so current behavior is preserved for all
  existing memories. The change is strictly additive.
- **`MatchedMemory.keywords_matched` semantics:** Tests in `tests/test_dynamic_memory.py` assert on this list; they
  continue to pass because we only store positives there (which is what they assert on today).

## Rollout

Single-PR change. `just check` before commit. No migration needed — no existing memory files use `!`-prefixed entries.

## Open Questions

None that block implementation. Candidates the user may want to weigh in on later, but not for v1:

- Should we expose negative-match exclusions in a debug flag (`SASE_DYNAMIC_MEMORY_DEBUG=1` etc.)? Deferred.
- Should the `### DYNAMIC MEMORY` section note entries that were _considered but excluded_? Deferred — current line
  rejects this.

## Update 2026-04-24 — superseded semantics

The "blanket veto" rule in `## User-facing Semantics` above has been superseded. The refined rule masks each negative
keyword's matched text out of the prompt before positive-keyword matching runs; a memory is excluded only when every
positive hit fell inside a masked region. Concretely, under the new rule the `["skill", "!vendor"]` +
`"deploy a skill via vendor"` example is **included** (the standalone `skill` still matches outside the `vendor` mask),
reversing the behavior documented above. See `plans/202604/negative_keyword_masking.md` for the full refined design and
its motivation.
