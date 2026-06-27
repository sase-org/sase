---
create_time: 2026-06-27 13:19:23
status: done
prompt: sdd/prompts/202606/yaml_literal_chomping.md
---
# Plan: Use `|-` For Config-Saved Snippets And XPrompts

## Problem

Saving a prompt draft through the `gx` / `<ctrl+g>x` flow can create YAML-backed reusable entries:

- snippets under `ace.snippets` via `Create a new snippet...`
- xprompts under top-level `xprompts` when creating or overwriting a config-backed xprompt

The generated YAML currently uses literal block headers like `|` and `content: |`. Because the writer strips trailing
newlines before generating the block body, `|` changes the intended value by adding a final newline when the YAML is
loaded. The chezmoi commit `ba933a886872` demonstrates the desired output: generated multiline snippet values should use
`|-`, not `|`, so stripped prompt text remains stripped after round-trip.

## Evidence

- `src/sase/xprompt/snippet_config_yaml.py` is the direct snippet write path used by the `gx` save modal. Its
  `_generate_snippet_yaml()` function does `template.rstrip("\n")` and then emits `name: |`.
- `src/sase/xprompt/config_yaml.py` is the config-backed xprompt write path. `generate_xprompt_yaml()` and
  `_generate_frontmatter_xprompt_yaml()` do the same for short-form xprompt entries and long-form `content` blocks.
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt.py` and `_prompt_bar_save_xprompt_snippets.py`
  correctly run discovery and writes off the Textual event loop, so this should remain a serializer-only change rather
  than a UI flow rewrite.
- The existing parser/block-detection logic matches entry keys and indentation, so changing the scalar header from `|`
  to `|-` should not affect insertion, replacement, sorting, or preservation of neighboring comments.

## Scope

1. Change generated literal block headers in the minimal-edit YAML writers from `|` to `|-` for new or overwritten
   snippet/xprompt content blocks.
2. Preserve the current minimal-edit behavior: do not reflow unrelated YAML, comments, blank-line spacing, sort order,
   or existing entries not being overwritten.
3. Keep Markdown xprompt saves unchanged; this issue is specific to YAML config-file persistence.
4. Leave general-purpose YAML display dumping alone unless tests reveal it is part of this save path. PyYAML already
   chooses chomping indicators based on string content there, and broad changes would have unnecessary blast radius.

## Implementation Approach

1. Update `src/sase/xprompt/snippet_config_yaml.py`:
   - Emit `    <name>: |-` from `_generate_snippet_yaml()`.
   - Update docstrings/comments that currently describe `name: |`.

2. Update `src/sase/xprompt/config_yaml.py`:
   - Emit `  <name>: |-` for short-form xprompts.
   - Emit `    content: |-` for long-form xprompts with inputs and for frontmatter-backed config xprompts.
   - Keep the existing empty-content handling, including `content: ""` for frontmatter entries with no body.
   - Update comments/docstrings that describe `|`.

3. Update tests to assert both formatting and semantics:
   - `tests/xprompt/test_snippet_config_yaml.py`: expect `|-` and expect newly written snippets to load without an
     implicit final newline.
   - `tests/xprompt/test_config_yaml_minimal_edits.py`: expect inserted config xprompts to use `|-` while preserving
     comments, order, and blank-line spacing.
   - `tests/xprompt/test_save.py`: expect config-saved xprompt content headers to be `content: |-` and loaded content to
     equal the submitted body without needing `rstrip("\n")` for the new-entry assertion.
   - `tests/ace/tui/test_xprompt_config_insert.py`: update compatibility-shim expectations for `|-`.
   - `tests/ace/tui/actions/test_prompt_save_xprompt.py`: update the end-to-end snippet save flow expectations so the
     refreshed snippet cache contains the stripped active-pane body, not the body plus an added newline.

4. Add or adjust focused regression assertions where useful:
   - A single-line saved snippet should render as a block scalar with `|-` and load as exactly `"body"`.
   - A multiline saved snippet/xprompt should render as `|-` and load as exactly the original stripped multiline text.
   - Existing untouched `|` entries in a file should remain untouched.

## Verification

1. Run targeted tests first:
   - `pytest tests/xprompt/test_snippet_config_yaml.py`
   - `pytest tests/xprompt/test_config_yaml_minimal_edits.py tests/xprompt/test_save.py`
   - `pytest tests/ace/tui/test_xprompt_config_insert.py tests/ace/tui/actions/test_prompt_save_xprompt.py`
2. Because this repo requires it after file changes, run `just install` if needed, then `just check`.

## Risks And Mitigations

- Risk: Existing tests or call sites may assume saved snippet/xprompt values include a trailing newline. Mitigation:
  Update only the YAML config save path, where the writer already strips trailing newlines before emitting YAML. This
  makes loaded values match the writer's existing normalization intent.
- Risk: Empty literal blocks can be awkward with `|-`. Mitigation: Add/keep coverage for empty or missing-section
  fallbacks and rely on existing `content: ""` behavior for frontmatter-backed empty bodies.
- Risk: Accidentally reformatting user-managed YAML. Mitigation: Keep the current line-oriented minimal-edit insertion
  strategy; change only the generated block header for the specific inserted/replaced entry.
