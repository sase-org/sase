---
create_time: 2026-04-24 12:48:01
status: done
prompt: sdd/prompts/202604/negative_keyword_masking.md
---
# Plan: Refine Negative Memory Keyword Semantics (Masking)

## Goal

Change the matching rule for negative (`!`-prefixed) memory keywords so that a negative keyword only _excludes_ a memory
when removing the text it matched from the prompt would leave no positive-keyword matches. In other words, a negative
keyword is a contextual carve-out around _where_ a positive matched, not a blanket veto.

## Motivation

Today's rule (added in a8833198) is a blanket veto: any negative hit excludes the memory, even if there is an unrelated,
standalone positive hit elsewhere. That is too aggressive when a negative keyword is a _narrowing phrase_ that happens
to contain a positive keyword.

Concrete user scenario with `keywords: [foo, "!/foo/"]`:

| Prompt                                   | Positive hits                              | Negative hits  | Desired  |
| ---------------------------------------- | ------------------------------------------ | -------------- | -------- |
| `Add foo to the /path/to/foo/ directory` | `foo` (standalone) and `foo` (inside path) | `/foo/` (path) | MATCH    |
| `Add bar to the /path/to/foo/ directory` | `foo` (inside path only)                   | `/foo/` (path) | NO MATCH |

Today, both prompts are excluded. The author's intent is: "match `foo` as a token, but if the only `foo` in the prompt
is part of a file path, don't match." The current semantics can't express that without ugly workarounds.

## User-facing Semantics

Given a memory with `keywords: [<positives...>, "!<negatives...>"]`:

1. Compute the set of character spans in the prompt matched by any negative keyword (same word-boundary,
   case-insensitive regex as today).
2. "Mask" those spans in the prompt — replace each matched span with the same number of space characters so offsets and
   surrounding word boundaries are preserved.
3. Run positive-keyword matching against the **masked** prompt.
4. A memory is included iff at least one positive keyword matches the masked prompt.

Properties:

- If no negative keyword matches, masking is a no-op and behavior is identical to the original simple-matching logic.
- If negatives match but the positives also match **outside** the masked spans, the memory is still included.
- If negatives match and positives only matched **inside** the masked spans, the memory is excluded — the prior use case
  of `["skill", "!vendor"]` on "deploy a skill via vendor" still excludes, because `vendor` is the negative-matched span
  and `skill` still matches outside it → include. Wait: this is actually the case the current spec _excludes_.

### Migration note on prior behavior

The previous spec (plans/202604/negative_memory_keywords.md) documented a stricter veto: `["skill", "!vendor"]` +
`"deploy a skill via vendor"` → excluded. Under the new rule, `skill` still matches outside the `vendor` span, so the
memory is **included**. This is a behavioral change for any existing memory that relied on the blanket veto.

Current state of the repo:

- No checked-in memory files use `!`-prefixed keywords (the feature is brand new; the only mention is in
  `memory/short/gotchas.md` as an example).

So the migration cost is zero in-tree. Authors who want the old blanket-veto semantics can still get close to it by
using a broader negative keyword that covers the whole context they want to exclude, but we should be clear in docs that
`!x` no longer implies "if `x` appears anywhere, drop this memory regardless of positives."

### Edge cases to pin down

- **Overlapping negative spans**: take the union (mask every character covered by any negative hit). No special handling
  needed.
- **Negative that covers the entire prompt**: everything is masked, no positive can match, the memory is excluded.
  Matches intuition.
- **Negative matches but does not overlap any positive**: mask is irrelevant, positives still match, memory is included.
  This differs from today's behavior (today would exclude).
- **Negative-only keyword list**: no positives → never match, same as today.
- **Same keyword appears positive and negative** (`["skill", "!skill"]`): the negative masks every occurrence of `skill`
  in the prompt, so positive `skill` cannot match anywhere → excluded. Same outcome as today, for a different reason.
- **Bare `!` in keywords**: still dropped by `_split_keywords`, unchanged.

## Scope

In scope:

- Update `src/sase/memory/dynamic.py` matching logic: add a masking helper, replace the early-exit-on-negative with the
  mask-then-match flow.
- Update existing negative-keyword tests in `tests/test_dynamic_memory.py` whose expectations change under the new rule,
  and add new tests pinning the masking behavior (including the `[foo, "!/foo/"]` example from the user).
- Update docs:
  - `memory/short/gotchas.md` negative-keyword note: reword to describe the masking rule, not the veto rule.
  - `specs/202604/negative_memory_keywords.md` and `plans/202604/negative_memory_keywords.md`: append a brief "Update:
    refined semantics" note (or replace the semantics section) so SDD history stays coherent. Do **not** rewrite these
    files to pretend the original rule never existed; add a dated addendum.

Out of scope:

- Any change to `keywords_matched` / display format. We still report only positive hits that match the masked prompt.
- Wildcards, regex keywords, per-keyword weighting, boolean groups.
- Surfacing "considered but masked-out" reasons to the user.
- Changing YAML quoting rules or parser behavior — still unchanged: `"!foo"` must be quoted.

## Design

### Masking helper

Add a private helper in `src/sase/memory/dynamic.py`:

```python
def _mask_negative_spans(prompt: str, negatives: list[str]) -> str:
    """Return `prompt` with every span matched by any negative keyword replaced by spaces.

    Uses the same word-boundary, case-insensitive regex as `_keyword_matches`.
    Overlapping spans naturally coalesce because every covered character is blanked.
    Replacing with spaces (rather than removing) preserves surrounding word boundaries,
    so a positive keyword adjacent to a masked span still matches correctly.
    """
```

Implementation sketch:

```python
masked = list(prompt)
for neg in negatives:
    for m in re.finditer(rf"\b{re.escape(neg)}\b", prompt, re.IGNORECASE):
        for i in range(m.start(), m.end()):
            masked[i] = " "
return "".join(masked)
```

Iterating over the original `prompt` (not a progressively-mutated one) is important so that a later negative still sees
the same input; the writes go to `masked`. Length is preserved so no span indices shift.

### Updated matching loop

Replace lines 156–159 of `generate_dynamic_memory` with:

```python
positives, negatives = _split_keywords(wf.keywords)
search_prompt = _mask_negative_spans(prompt, negatives) if negatives else prompt
hits = [kw for kw in positives if _keyword_matches(kw, search_prompt)]
if hits:
    matched.append(...)
```

Two small wins:

- Skip building `masked` when there are no negatives (the common case today).
- We no longer need a short-circuit early-exit; the fallthrough handles exclusion naturally (no positive matches the
  masked prompt → not appended).

### Why "replace with spaces" rather than "remove"?

- Removing would shift offsets and, more importantly, could glue two word tokens together across the deletion
  (`"foo!bar"` with `!` masked-out becomes `"foobar"`, breaking word boundaries). Replacing with spaces preserves the
  original word structure on both sides of the mask. Space is a non-word char, guaranteeing `\b` still fires at the mask
  edges.

### Interaction with existing helpers

- `_split_keywords` unchanged.
- `_keyword_matches` unchanged — it just operates on the masked prompt.
- `_strip_dynamic_memory_section` unchanged — masking is layered on top of it (we still strip the existing
  `### DYNAMIC MEMORY` section before matching).
- `MatchedMemory.keywords_matched` continues to list only positive hits, now filtered by the masked prompt.

## Files to Touch

Implementation:

- `src/sase/memory/dynamic.py`:
  - Add `_mask_negative_spans`.
  - Rewrite the relevant stanza in `generate_dynamic_memory` (currently lines 156–159).
  - Update the module docstring / `generate_dynamic_memory` docstring to describe the masking rule in one sentence.

Tests (`tests/test_dynamic_memory.py`):

Tests to **update** (their current expectations describe the old veto semantics):

- `test_negative_keyword_excludes_memory` — today asserts that `["skill", "!vendor"]` + `"deploy a skill via vendor"`
  yields no match. Under the new rule, `skill` still matches outside the `vendor` mask → **this should now match**. Flip
  the assertion to expect a single match whose `keywords_matched == ["skill"]`. Consider renaming the test to
  `test_negative_keyword_does_not_exclude_when_positive_matches_outside_mask` so the name doesn't lie.
- `test_negative_keyword_case_insensitive` — today asserts that `"VENDOR skill deploy"` with `["skill", "!vendor"]`
  excludes. Under the new rule, `skill` matches outside the masked `VENDOR` span → should include. Flip the assertion;
  rename to reflect that we're checking the negative match itself is case-insensitive (i.e. an uppercase `VENDOR` does
  get masked), not that the whole memory is excluded.
- `test_negative_overrides_positive_in_same_list` — `["skill", "!skill"]` + `"update the skill"` still yields no match
  (masking covers every `skill`). Expectation survives; keep the test, maybe tweak the docstring to reflect the masking
  explanation.

Tests to **keep as-is**:

- `test_split_keywords_basic`, `test_split_keywords_bare_bang_dropped` — parser-level, not affected.
- `test_negative_keyword_ignored_when_absent` — the negative doesn't match, masking is a no-op, positive still fires.
  Outcome unchanged.
- `test_negative_only_keywords_never_match` — no positives, no match. Outcome unchanged.
- `test_negative_keyword_word_boundary` — `!test` does not match `testing` (word boundary), so masking is a no-op and
  `skill` still matches. Outcome unchanged.
- The three frontmatter / config round-trip tests — parser-level, unaffected.

Tests to **add**:

- `test_negative_mask_allows_positive_outside_span` — the user's example: `["foo", "!/foo/"]` +
  `"Add foo to the /path/to/foo/ directory"` → match (positive `foo` matches the standalone word). Assert
  `keywords_matched == ["foo"]`.
- `test_negative_mask_excludes_when_positive_only_inside_span` — the user's other example: `["foo", "!/foo/"]` +
  `"Add bar to the /path/to/foo/ directory"` → no match (the only `foo` is inside the masked `/foo/`).
- `test_negative_mask_preserves_word_boundaries_at_edges` — construct a prompt where a positive sits adjacent to a
  negative-matched span (e.g. `keywords: ["bar", "!foo"]`, prompt `"foobar"` — positive `bar` should _not_ match because
  there was no word boundary in the first place, confirming our mask-with-spaces doesn't invent one either). This pins
  the "replace with spaces, not delete" design choice.
- `test_negative_mask_overlapping_negatives` — two negative keywords whose matched spans overlap (e.g. `"!foo bar"` and
  `"!bar baz"` over the prompt `"foo bar baz"`). Assert the union is masked and behavior is deterministic.
- Optional: `test_negative_mask_covers_entire_prompt` — a negative that matches the whole prompt excludes even when the
  same text contains positives.

Docs:

- `memory/short/gotchas.md` lines 15–18 (the `!`-prefix note): rewrite the semantic clause. Current wording says "a
  match on any negative keyword excludes the memory from `### DYNAMIC MEMORY` even if positive keywords also matched."
  Replace with something like: "a negative keyword masks its matched text out of the prompt for positive-keyword
  matching; a memory is excluded only if all positive hits fell inside masked regions." Keep the YAML-quoting caveat
  verbatim.
- `specs/202604/negative_memory_keywords.md`: append a short `### Update 2026-04-24` section noting the semantics
  refinement and pointing at the new plan file.
- `plans/202604/negative_memory_keywords.md`: same — add a dated addendum referencing this plan, rather than editing the
  prior `## User-facing Semantics` section in place. The prior plan is marked `status: done`; preserve that but flag the
  superseded semantics.

## Risks & Mitigations

- **Behavior change for any author who already adopted `!`-keywords**: Zero such files in the repo today. External
  consumers of this code (if any) are on a commit published ~1 day ago; the window for adoption is narrow. Mitigation:
  docs clearly describe the new rule, and the prior plan gets an explicit "superseded" addendum.
- **Regex performance on long prompts**: `re.finditer` over each negative over the full prompt is O(N·len(prompt)) where
  N is number of negatives. Memory xprompts typically have ≤ 10 keywords and prompts are a few KB; this is not a hot
  path. No optimization needed.
- **Mask spans vs. `\b` mid-mask**: Using spaces as the mask char guarantees `\b` fires at the _edges_ of the masked
  region (word→space transition). Inside the masked region there are no word characters, so no positive regex can match
  there. This is the property we want.
- **Unicode / non-ASCII word chars**: Python's `\b` uses the default Unicode word definition in `re`. Spaces are safely
  non-word in every locale, so mask boundaries behave identically to any other space in the prompt.

## Rollout

Single PR. Run `just check` before commit. No migration needed — no existing memories use `!`-keywords. The SDD
spec/plan addenda make the history self-explanatory.

## Open Questions

None that block implementation. One stylistic call for the implementer: whether to append addenda to the prior spec/plan
files or rewrite their semantics sections in place. Default (above): addenda, because the spec/plan are historical
artifacts of the original work item, and later readers are better served by seeing "this was refined on 2026-04-24, see
`sase_plan_negative_keyword_masking.md`" than by a silent rewrite.
