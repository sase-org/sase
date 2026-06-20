---
create_time: 2026-06-20 18:49:37
status: done
prompt: sdd/prompts/202606/alt_empty_whitespace.md
---
# Plan: Smarter whitespace handling for empty alternation renders

## Problem / product context

Fan-out prompts can contain alternation directives (`%{...}` brace form, or the legacy `%alt(...)` / `%(...)` paren
forms). A directive's chosen branch can render to the **empty string** in two situations:

1. A single-branch directive carries an implicit empty variant (the existing "with / without" split), e.g.
   `before %{a} after` produces a variant where `%{a}` renders empty.
2. A correlated group has a key that is missing from one of its directives, e.g. for the recently shipped
   correlated-keys behavior, `%{a=Describe | b=Explain} how this repo works %{a=in detail}.` renders the `b` slot with
   the second directive empty (it has no `b=` branch).

Today, when a directive renders empty, only its exact span is removed; the surrounding whitespace is left untouched.
That leaves awkward artifacts:

| Input (the `b` slot of the reported prompt)               | Today (wrong)                                      | Desired                  |
| --------------------------------------------------------- | -------------------------------------------------- | ------------------------ |
| `… how this repo works %{a=in detail}.`                   | `… how this repo works .` (stray space before `.`) | `… how this repo works.` |
| `before %{a} after` (empty variant)                       | `before  after` (double space)                     | `before after`           |
| `%{a=in detail}` at start, then ` Review` (empty variant) | ` Review` (leading space)                          | `Review`                 |

For the reported prompt the user explicitly called out that, for the `b` alternation, it is "clearly safe and desirable
to remove the white space before where 'in detail' would go." This plan generalizes that into one conservative,
well-specified whitespace-collapse rule applied wherever an alternation branch renders empty.

### Desired behavior

When an alternation branch renders to the empty string, the now-empty directive should leave behind the spacing a human
would have typed had the directive never been there: no doubled space, no space stranded against punctuation, and no
leading/trailing space against a boundary — while never disturbing intentional line structure (newlines, blank lines,
indentation) and never touching non-empty branches.

Concretely, for the reported prompt the two slots become:

| alt_id | rendered prompt                                                |
| ------ | -------------------------------------------------------------- |
| `a`    | `#gh:sase Describe how this repo works in detail.` (unchanged) |
| `b`    | `#gh:sase Explain how this repo works.` (was `… works .`)      |

## Where the logic lives (single source of truth)

All alternation parsing, branch-id allocation, Cartesian/correlation grouping, and **prompt rendering** live in the Rust
core (`sase-core` linked repo), in `crates/sase_core/src/agent_launch/mod.rs`. The single rendering choke point is
`render_alternative_prompt`, which every alternative slot (including the multi-model fan-out path, which routes through
the same alternatives splitter) flows through. Per the repo's "Rust Core Backend Boundary" convention, this is
core/domain behavior and belongs in the Rust core; the Python repo (`sase`) only consumes the rendered slots through the
`sase_core_rs` PyO3 binding and is limited to docstrings/tests here.

Relevant code (current):

- `render_alternative_prompt(prompt, directives, combination)` — collects each selected branch's
  `(directive.start, directive.end, value)` triple, sorts by **descending** `start`, and splices each value into the
  prompt with `String::replace_range`. An empty branch is spliced as `""`, which is exactly why surrounding whitespace
  is left stranded today. This is the **only** function that needs a behavior change.
- The wire shape (`LaunchFanoutSlotWire` / `LaunchFanoutPlanWire`) is unchanged, so the PyO3 binding and schema version
  are untouched.

## Design: empty-branch whitespace collapse

Change `render_alternative_prompt` so that **when, and only when, a branch value is the empty string**, the directive
span is removed together with the appropriate adjacent horizontal whitespace.

### The rule

For each directive that renders empty, treat its removed span as a point `P` and look at its **rendered** neighbors:

- `L` = the nearest non-horizontal-whitespace character to the **left** of `P` in the rendered output (`None` at start
  of string).
- `R` = the nearest non-horizontal-whitespace character to the **right** of `P` (`None` at end of string).

`P`, together with the horizontal-whitespace runs bordering it, collapses to:

- **a single space** iff `L` and `R` are _both alphanumeric_ **and** at least one bordering horizontal-whitespace
  character existed (preserve word separation, e.g. `A %{x} B` → `A B`, and collapse `A  %{x}  B` → `A B`);
- **the empty string** otherwise — i.e. when a side is a boundary, a newline, or punctuation, or when there was no
  bordering whitespace at all (e.g. `works %{x}.` → `works.`, `%{x} Review` → `Review`, `A %{x}` → `A`, and `A%{x}B` →
  `AB` with no invented space).

Boundary discipline (the "clearly safe" guardrails):

- **Horizontal whitespace only.** Only spaces and tabs are absorbed; `\n` / `\r` are hard boundaries that whitespace
  runs never cross. A directive alone on its own line still collapses to a blank line (unchanged), and an empty
  directive before a newline still does not pull the following line up.
- **Indentation is preserved.** Horizontal whitespace that is line-leading (immediately preceded by a newline or
  start-of-string) is treated as indentation and kept, not absorbed. Trailing horizontal whitespace before a newline
  _is_ safe to drop.
- **Non-empty branches are byte-for-byte unchanged** — there is no general whitespace normalization; the collapse only
  ever fires at an empty-directive site.

### Why neighbors must come from the _rendered_ text (key implementation subtlety)

Two directives can be separated by only whitespace (e.g. `%{a=A|b=B} … %{a=C} %{x=Z}`). When one of them renders empty,
its right neighbor in the **raw** prompt is the next directive's delimiter (`%`/`}`), not that directive's substituted
value. Classifying neighbors off the raw prompt would mis-handle the join (e.g. produce `B XZ` instead of `B X Z`).
Neighbor classification must therefore use the rendered values.

The cleanest implementation: during span replacement, splice each **empty** branch as a single internal sentinel
character (e.g. a private-use/`NUL` marker that is not expected in prompt text) instead of `""`; non-empty branches
splice their value as today. Then run one left-to-right pass that finds each maximal run of `[sentinel | space | tab]`
that contains at least one sentinel and does not cross a newline, classifies the characters bounding that run (with the
line-leading-indentation guard above), replaces the run with a single space or nothing per the rule, and finally drops
any remaining sentinels. This keeps the existing descending-splice step intact and confines all new logic to one
post-pass. (Adjacent empty directives fall out naturally — a run may contain several sentinels.)

### Worked examples (drive the tests)

- `… how this repo works %{a=in detail}.` (`b` slot) → `L='s'`, `R='.'` → empty → `… how this repo works.`
- `before %{a} after` (empty variant) → `L='e'`, `R='a'`, had ws → single space → `before after`
- `%{a=in detail} Review` (empty variant) → `L=None` (start), `R='R'` → empty → `Review`
- `A %{x}` (empty, end) → `L='A'`, `R=None` → empty → `A`
- `A%{x}B` (no surrounding ws) → no bordering ws → empty → `AB`
- `%{a=1|b=2} x %{a=3} y %{a=4|b=5}` (`b` slot) → middle directive empty between `x` and `y` → single space → `2 x y 5`
  (today: `2 x  y 5`)
- `Header\n%alt(extra)\nFooter` (empty variant) → newline-bounded → `Header\n\nFooter` (unchanged)

## Implementation steps

### A. Rust core (`sase-core` linked repo) — primary change

> Open the linked repo with `sase workspace open -p sase-core -r "<reason>" <workspace_num>` and use the printed path.
> Do not hard-code workspace paths.

1. In `crates/sase_core/src/agent_launch/mod.rs`, modify `render_alternative_prompt` to implement the empty-branch
   whitespace-collapse rule above:
   - Keep the existing descending `replace_range` splice, but splice an internal sentinel for empty values.
   - Add a small helper that performs the single collapse pass over the sentinel-bearing string (run detection, neighbor
     classification with the alphanumeric/punctuation/boundary distinction, line-leading-indentation guard, sentinel
     removal). Define `is_horizontal_ws` (space/tab) and reuse `char::is_alphanumeric` for word classification, matching
     the existing `safe_launch_name` convention.
   - Add doc comments describing the empty-render whitespace semantics and the boundary guarantees.
2. No change needed to grouping, id allocation, model fan-out, or the wire types — verify by test that non-empty model
   branches and the implicit-empty newline cases are unaffected.

### B. Rust tests (`crates/sase_core/src/agent_launch/mod.rs` `#[cfg(test)]`)

Update the existing assertions that encode the old stranded-space output (these become regression coverage for the new
behavior):

- `fanout_planner_correlates_shared_named_alt_keys`: `"#gh:sase Explain how this repo works ."` → `"… works."`
- `fanout_planner_correlates_transitive_alt_keys`: `"2 x  y 5"` → `"2 x y 5"`
- `fanout_planner_cartesian_products_independent_correlated_groups`: `["A X C Z", "A Y C ", "B X  Z", "B Y  "]` →
  `["A X C Z", "A Y C", "B X Z", "B Y"]`
- `fanout_planner_correlated_group_mixes_named_and_unnamed_ids`: `["X Z", "Y "]` → `["X Z", "Y"]`
- `fanout_planner_brace_single_branch_has_implicit_empty_variant`: `"before  after"` → `"before after"`

Add focused new tests for the rule's edge cases: empty branch before punctuation (no space before `.`), between two
words (single space), at start-of-string (no leading space), at end-of-string (no trailing space), with no surrounding
whitespace (`A%{x}B` → `AB`), multiple-space collapse (`A  %{x}  B` → `A B`), and a newline/indentation case proving
newlines are not crossed and indentation is preserved.

### C. Python repo (`sase`) — tests + docs only

1. Rebuild the binding so Python picks up the Rust change: `just install` (detects the local `../sase-core` checkout via
   `SASE_CORE_DIR` / `SASE_LINKED_REPO_SASE_CORE_DIR` and runs `maturin develop` for `sase_core_rs`). Run
   `just rust-test` for the Rust suite.
2. Update existing Python assertions that encode the old output (all flow through the rebuilt binding):
   - `tests/test_directives_split_alternatives.py`:
     - `single_arg_nested_directive` second variant: `" Review this code"` → `"Review this code"`
     - `single_arg_combined` empty variants: `" c\nDo work"` / `" d\nDo work"` → `"c\nDo work"` / `"d\nDo work"`
     - `shared_named_keys_correlate` second result: `"… works ."` → `"… works."`
   - `tests/test_directives_split_models.py`: `"%name:foo.b\nExplain how this repo works ."` → `"… works."`
   - `tests/test_core_agent_launch_wire.py`: `"#gh:sase Explain how this repo works ."` → `"… works."`
3. Keep (and rely on as guardrails) the cases that must stay the same — they confirm newlines are not collapsed:
   `single_arg_splits_with_empty` and `shorthand_single_arg` → `"\nDo work"`; `single_arg_own_line` →
   `"Header\n\nFooter"`. Add a focused new `split_prompt_for_alternatives` test for the punctuation case (`… works.`)
   plus a start-of-string case, mirroring the existing test style.
4. Docstrings: update `src/sase/xprompt/_directive_alt.py` (module docstring + `split_prompt_for_alternatives` /
   `split_prompt_for_models`), which currently say only that a missing key "renders as empty text", to also note that
   the empty render collapses adjacent horizontal whitespace (no doubled space / no space before punctuation), while
   newlines and indentation are preserved.

### D. Docs

- `docs/xprompt.md`: in the correlated-keys / named-branches section, update the worked example from
  `"Explain how this repo works ."` to `"Explain how this repo works."`, and add a short note describing the
  empty-branch whitespace-collapse rule and its boundary guarantees (horizontal whitespace only; newlines/indentation
  preserved; non-empty branches untouched).

### E. Verify

- `just rust-test` (Rust suite) and `just check` (Python lint + mypy + pytest) both green. Per repo rules,
  `just install` must precede `just check` in an ephemeral workspace.
- Manual sanity: feeding the reported prompt through the planner yields the `b` slot as `… how this repo works.` with no
  stray space, and `before %{a} after` yields `before after` for the empty variant.

## Risks & decisions

- **Behavior change scope.** This changes output only for slots where an alternation branch renders empty. Non-empty
  renders, model fan-out values, and newline-bounded empties are unchanged. The handful of existing tests that encoded
  the old stranded-space output are updated to the new, intended output and become the regression net.
- **Sentinel choice.** An internal marker is needed because adjacent directives force neighbor classification onto
  rendered (not raw) text. The marker is a character not expected in prompt text and is fully stripped before returning;
  if extra safety is wanted, the renderer can guard against (or strip) a pre-existing occurrence in the input.
- **Conservative boundaries.** Newlines, blank lines, and indentation are intentionally left untouched ("clearly safe"
  scope). Aggressive multi-line reflow is explicitly out of scope. Whole-line removal for an own-line empty directive is
  also out of scope (it remains a blank line, matching today and existing tests).
- **Boundary discipline.** All semantic logic stays in `sase-core`; Python changes are docstrings/tests only. The wire
  schema and PyO3 binding are unchanged.
