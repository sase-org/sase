---
create_time: 2026-06-27 07:12:39
status: done
prompt: sdd/prompts/202606/admin_center_xprompt_ctrl_i.md
---
# Admin Center XPrompts Ctrl-I Load Plan

## Objective

Add a `Ctrl+I` keymap to the XPrompts tab inside the SASE Admin Center. When the selected row is backed by a non-YAML
xprompt, the key should expand that xprompt the same way the Select XPrompt panel does and load the result into the main
prompt input widget for editing/submission.

The key must be inactive for YAML-backed rows, including workflow files and config-backed YAML entries.

## Current Behavior

- The Select XPrompt modal already supports `Ctrl+I` through `XPromptSelectModal.action_expand_selected()`. The
  prompt-bar request handler wires that action to `expand_inline_xprompt()`, then splices the expanded body into the
  originating prompt pane and stages declared xprompt inputs in prompt frontmatter.
- The Admin Center XPrompts tab is implemented by `XPromptBrowserPane`. It has a grouped xprompt list, preview, edit,
  add, and navigation actions, but no action that opens or fills the prompt input.
- Browser rows already carry enough metadata for this change: name, unified `Workflow`, source path/display path, kind,
  and insertion text.
- The prompt input bar can be seeded with initial text via the existing home-mode prompt path. It can also stage xprompt
  input declarations through `PromptInputBar.merge_frontmatter_inputs()`.

## Design

1. Add a small eligibility helper for XPrompt browser rows.
   - Treat a row as loadable only when it is not YAML-backed.
   - Use cheap source metadata checks instead of resolving files or reading disk on navigation/key handling.
   - Cover regular `.yml`/`.yaml` paths plus source identifiers that resolve to YAML config files such as user config,
     overlays, local config, project-local config, default config, and plugin config.

2. Wire `Ctrl+I` into the XPrompts tab.
   - Add the binding on `XPromptBrowserPane` and forward it from `_BrowserFilterInput`, matching the pane’s existing
     `Ctrl+N`, `Ctrl+P`, and `Ctrl+O` pattern.
   - Mirror the Select XPrompt terminal behavior where `Ctrl+I` may arrive as `tab`: consume `tab` only when the
     highlighted row is eligible, so YAML-backed rows remain inactive.
   - Keep an action-level eligibility guard as a final safety check.

3. Reuse the existing inline expansion behavior.
   - Call `expand_inline_xprompt(item.name, item.workflow, project=self._project)` for the selected eligible row.
   - Preserve the selector’s failure semantics: if expansion reports an error, notify and keep the Admin Center open.
   - Avoid new synchronous UI hot-path work where possible. The action should capture the selected row identity, run
     expansion off the Textual event loop if it may recurse into catalog loading, and apply the result back on the UI
     thread only if the captured selection is still valid.

4. Load the expanded result into the prompt input widget.
   - On successful expansion, close the Admin Center and open the normal prompt input bar in home-mode with the expanded
     text.
   - Use a display/history label based on the selected xprompt name so the prompt context is understandable without
     requiring a project/ChangeSpec selection.
   - Stage any `InlineExpansionResult.inputs` into prompt frontmatter before or immediately after mounting the bar,
     preserving parity with Select XPrompt `Ctrl+I` for declared inputs.

5. Keep UI documentation in sync.
   - Update the XPrompts tab hint text so `^i` is shown only when the highlighted row is loadable, or otherwise make the
     hint wording clearly conditional.
   - Do not add this as an app-level configurable keymap unless the surrounding modal keymaps are already configurable;
     this is scoped to the Admin Center pane.

6. Add focused tests.
   - Unit-test YAML eligibility for `.md`, `.yml`, `.yaml`, config source identifiers, and plugin/config identifiers.
   - Widget-test `Ctrl+I` from the XPrompts tab on a non-YAML xprompt: the modal closes, the prompt input bar mounts,
     and the expanded body is present.
   - Widget-test declared inputs are staged into prompt frontmatter.
   - Widget-test YAML-backed selection does not load a prompt and leaves the Admin Center open.
   - Widget-test `tab` routing on an eligible row, since real terminals can deliver `Ctrl+I` as Tab.

## Verification

After implementation, run:

```bash
just install
just check
```

If the focused widget tests are practical to run independently during development, run them first before the full check.
