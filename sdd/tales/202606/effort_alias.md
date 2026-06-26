---
create_time: 2026-06-26 07:49:00
status: done
prompt: sdd/prompts/202606/effort_alias.md
---
# Plan: make `%e` an alias for `%effort`

## Goal

Make `%e` behave as the short alias for the `%effort` directive everywhere SASE understands launch directives. The alias
should set `PromptDirectives.reasoning_effort` exactly like `%effort`, participate in duplicate/conflict validation
under the canonical directive name `effort`, be stripped from cleaned prompts/history previews, and be discoverable in
ACE/editor completion.

## Current State

- Python runtime directive parsing currently maps `%e` to the removed `%edit` directive so it raises a migration hint.
  `%edit` itself is still deprecated.
- Docs explicitly say there is no `%e` alias and that submitting `%edit` / `%e` raises a `DirectiveError`.
- ACE prompt-bar completion already treats `%e` as a way to narrow to `%effort`, but it does not advertise `%e` as an
  accepted alias because the parser alias table maps `e -> edit`.
- The linked `sase-core` editor registry currently says `effort` has no alias. Rust fan-out parsing canonicalizes names
  through that registry, so Rust parity should change with the editor registry rather than carrying a separate alias
  table.

## Design

1. Treat `%e` as a real alias for `%effort`.
   - Update the canonical directive alias map from `e -> edit` to `e -> effort`.
   - Keep `%edit` in deprecated-directive handling so old full-form `%edit` buffers still get the targeted
     editor-review-marker migration message.
   - Accept `%e:<level>` and `%e(<level>)` anywhere `%effort:<level>` and `%effort(<level>)` work today.
   - Bare `%e` should now fail with the existing canonical effort message: `%effort` requires a level argument.

2. Preserve canonical semantics.
   - Duplicate detection should report `Duplicate directive '%effort'` for `%e:low` plus `%effort:high`, because both
     resolve to the same canonical directive.
   - Conflict checks with `%model:...@<effort>` should report the canonical `%effort:<level>` conflict message.
   - Cleaned prompts, `strip_known_directives`, and history previews should remove/summarize `%e` as `effort`.

3. Update editor/completion parity.
   - ACE prompt-bar directive completion should advertise `%e` as an alias in `%effort` metadata. Existing `%e`
     completion can still insert `%effort`; the behavior becomes truthful rather than only prefix narrowing.
   - ACE directive-argument completion should classify `%e:` as the `effort` argument context and offer the canonical
     effort vocabulary.
   - In `sase-core`, set the `effort` directive metadata alias to `Some("e")`. This makes Rust editor completion, hover
     metadata, diagnostics, and Rust fan-out canonicalization agree on the alias.

4. Update documentation.
   - Add `%e` to the `%effort` directive table/examples and remove the claim that `%e` is unavailable.
   - Keep the removed `%edit` documentation, but narrow it to `%edit` only.

## Implementation Scope

Primary repo:

- `src/sase/xprompt/_directive_types.py`
  - Change `_DIRECTIVE_ALIASES["e"]` from `"edit"` to `"effort"`.
  - Update comments so the alias table documents the new behavior.

- `src/sase/ace/tui/widgets/directive_completion.py`
  - The metadata should pick up the parser alias table automatically. Add or adjust tests to lock this in; avoid
    duplicating another alias map.

- `src/sase/history/prompt_metadata.py`
  - No code change is expected if it continues deriving summaries from `_DIRECTIVE_ALIASES`, but add coverage for
    `%e:xhigh`.

- `docs/xprompt.md`
  - Document `%e` as the `%effort` alias and update the removed `%edit` section.

Linked `sase-core` repo:

- `crates/sase_core/src/editor/directive.rs`
  - Change `effort.alias` to `Some("e")`.
  - Update editor registry tests for canonical alias resolution, completion detail, and `%e` completion.

- `crates/sase_core/src/editor/completion.rs`
  - Expected to work through `canonical_directive_name`; add/update a test for `%e:` argument context if existing
    coverage does not catch it.

- `crates/sase_core/src/agent_launch/mod.rs`
  - Expected to work through the shared editor directive registry. Update tests that currently assert
    `canonical_directive_name("e") == "e"` and add coverage that `%e:%{medium | high}` fans out like `%effort:%{...}`.

## Test Plan

Run focused Python tests first:

```bash
just install
uv run pytest \
  tests/test_directives_effort.py \
  tests/test_directives_flags.py \
  tests/history/test_prompt_metadata.py \
  tests/ace/tui/widgets/test_directive_completion_candidates.py \
  tests/ace/tui/widgets/test_directive_arg_extraction.py \
  tests/ace/tui/widgets/test_directive_arg_completion.py
```

Run focused Rust/core parity tests in the linked `sase-core` repo:

```bash
cargo test -p sase-core editor::directive
cargo test -p sase-core editor::completion
cargo test -p sase-core agent_launch
```

Then run the primary repo check required after source/doc changes:

```bash
just check
```

## Risks and Mitigations

- Behavior change for stale `%e` prompts: `%e` will no longer show the removed `%edit` migration hint. This is
  intentional for the requested alias; `%edit` remains the migration surface for old editor buffers.
- Alias drift between Python and Rust: use the existing Rust dependency on the shared editor directive registry and add
  tests on both sides.
- Completion/documentation mismatch: assert ACE metadata advertises `%e` as an alias and update docs in the same change.
