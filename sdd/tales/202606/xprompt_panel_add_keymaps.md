---
create_time: 2026-06-18 10:08:37
status: done
prompt: sdd/prompts/202606/xprompt_panel_add_keymaps.md
---
# Plan: Split Frontmatter Panel Add Property vs Add Entry Keymaps

## Context

The prompt Frontmatter Panel is the structured property editor shown above the prompt input stack. Its current rows-mode
`a` key is context-sensitive:

- On an ordinary or empty panel, it posts `FrontmatterPanel.AddRequested`, and the host bar opens `AddPropertyModal`.
- On the `input` or `xprompts` structured field header, or on a child item inside either subtree, it bypasses the
  property picker and opens `InputItemModal` / `XPromptItemModal`.

That second behavior is the source of the reported regression: after the `xprompts` property exists, pressing `a` while
the selection is on the `xprompts` row opens the local-xprompt item modal, so the user loses the predictable single-key
path into the add-property picker.

## Product Behavior

Make the add semantics stable and mnemonic:

- `a` always means "add a top-level frontmatter/xprompt property" from the supported-property picker.
- `A` means "add an entry to the currently selected structured property", e.g. a new `input` entry or local `xprompts`
  helper.
- Existing edit/delete behavior remains: `e` / `enter` edit selected scalar or item; `d` deletes the selected field or
  selected structured item. Existing `begin_add("xprompts")` behavior from the property picker still opens the local
  xprompt sub-form for the first item.

`A` should be active when the selection is on:

- the `input` header,
- an `input` child item,
- the `xprompts` header,
- an `xprompts` child item.

When the selection is not inside a structured field, `A` should be a no-op (or a handled no-op) rather than opening the
property picker, so the two add concepts stay distinct.

## Implementation Outline

1. Update `FrontmatterPanel` rows-mode key dispatch.
   - Change lowercase `a` handling to unconditionally request the add-property modal.
   - Add uppercase `A` handling that routes through the existing structured-item add flow.
   - Keep edit/raw modes unchanged so literal `a` / `A` input still works inside the inline input and raw YAML editor.

2. Split the editing helper responsibilities in `_frontmatter_panel_editing.py`.
   - Replace the current context-sensitive `_add_at_selection()` behavior with two explicit paths:
     - one method for top-level property picker requests;
     - one method for structured item insertion based on selected nav row.
   - Reuse the existing logic that maps `("field", "input")`, `("input", name)`, `("field", "xprompts")`, and
     `("xprompt", name)` to `InputItemModal` / `XPromptItemModal`.
   - Preserve `begin_add(field)` as the add-property picker callback, including the current behavior where selecting a
     structured property opens its first item modal.

3. Update visible guidance and docs.
   - Change the panel border subtitle from `a add` to wording that distinguishes `a` property and `A` item.
   - Update `docs/xprompt.md` so it describes `a` as the stable property picker and `A` as structured item insertion.
   - Update relevant module/test docstrings that currently describe `a` as the structured item add key.
   - No `src/sase/default_config.yml` or app keymap schema update is expected, because these are panel-local `on_key`
     shortcuts rather than configurable app keymaps; still verify this assumption while implementing.

4. Add regression tests.
   - Keep existing empty-panel `a` picker tests.
   - Add a test proving that, with `xprompts:` already present and selected, pressing `a` opens `AddPropertyModal`
     rather than `XPromptItemModal`.
   - Add tests proving `A` opens `InputItemModal` on the `input` header and `XPromptItemModal` on the `xprompts` header.
   - Update existing subeditor tests that currently press `a` on structured headers to press `A`.
   - If the subtitle text changes visual snapshots, update the frontmatter panel PNG snapshot intentionally after
     inspecting the diff.

5. Verify focused behavior first, then broader checks.
   - Run the focused widget tests:
     `pytest tests/ace/tui/widgets/test_frontmatter_panel.py tests/ace/tui/widgets/test_frontmatter_panel_subeditors.py`.
   - Run frontmatter-related visual tests if subtitle/rendering changed:
     `pytest tests/ace/tui/visual/test_ace_png_snapshots_frontmatter_panel.py`.
   - Because source changes in this repo require it, run `just install` if needed, then `just check` before finalizing.

## Risks and Edge Cases

- Textual uses uppercase key names in this codebase already (`R` is handled in the panel), so `A` should be reliable,
  but tests should press uppercase `A` through the pilot to confirm.
- If `a` opens the property picker while all top-level properties are already set, the current host behavior returns
  early because there are no addable properties. That behavior can remain unchanged unless product review wants
  feedback.
- `e` / `enter` on a structured header currently adds an item. This plan preserves that behavior to avoid unnecessary
  churn, while making `A` the explicit add-entry key.
