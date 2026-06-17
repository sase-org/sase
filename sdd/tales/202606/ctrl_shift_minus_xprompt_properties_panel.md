---
create_time: 2026-06-17 10:27:48
status: done
prompt: sdd/prompts/202606/ctrl_shift_minus_xprompt_properties_panel.md
---
# Ctrl+Shift+- XPrompt Properties Panel Toggle Plan

## Context

The prompt bar already has the panel this request describes: `FrontmatterPanel`, mounted by `PromptInputBar` directly
above `#prompt-stack`, which places it above the top prompt input widget. It is currently activated by `,f`, by typing a
leading `---` followed by a newline in an empty prompt, or automatically when an opened xprompt already carries
frontmatter. Existing close behavior is:

- empty panel: `esc` / `q` returns focus to the active prompt and hides/removes empty frontmatter;
- populated panel: `esc` / `q` returns focus to the active prompt but keeps the properties panel visible.

The new keymap should reuse this lifecycle instead of creating a second panel path. It must also stay lightweight on the
Textual event loop: no disk reads, subprocess work, or expensive parsing beyond the existing in-memory model sync
already used when the panel is shown.

## Behavioral Contract

Add a prompt-widget-local `Ctrl+Shift+-` keymap that toggles activation of the xprompt properties panel in prompt mode
only.

- If the prompt body owns focus and the panel is hidden, the chord syncs live prompt text, shows the panel, and focuses
  it.
- If the prompt body owns focus and the panel is already visible, the chord focuses the existing panel after resyncing
  it from the stack.
- If the panel, its inline editor, or its raw YAML editor owns focus, the chord deactivates the panel and returns focus
  to the active prompt input.
- Deactivation preserves existing panel semantics: empty properties hide and clear empty frontmatter; populated
  properties remain visible above the stack.
- `,f`, leading `---`, and auto-show-on-existing-frontmatter keep working.
- Feedback and approve-prompt bars remain no-ops because they do not mount a properties/frontmatter panel.
- Handle both Textual key spellings for the physical chord: `ctrl+shift+minus` and `ctrl+underscore`. The latter matters
  because many terminals encode `Ctrl+Shift+-` as `Ctrl+_`.

For editing submodes, the toggle should be predictable:

- inline scalar/list edit: cancel the in-progress inline edit using the existing `Esc` semantics, then deactivate the
  panel;
- raw YAML edit: try to apply the raw YAML using the existing raw `Esc` semantics, then deactivate only if parsing
  succeeds. If parsing fails, keep focus in raw mode so invalid edits are not silently discarded.

## Implementation Plan

1. Add a shared private key helper or constant for the two accepted key names. Use it from both prompt-body key handling
   and panel key handling so the alias list cannot drift.

2. Add a small public deactivation method to `FrontmatterPanel`. This method should wrap the existing private behaviors
   rather than duplicate model logic:
   - rows mode posts `FrontmatterPanel.Closed`;
   - inline edit mode cancels the inline edit, then posts `Closed`;
   - raw mode calls `_commit_raw()` first and only posts `Closed` if the panel actually returned to rows mode.

3. Add a `toggle_frontmatter_panel()` method to `PromptInputBarFrontmatterMixin`. The method should:
   - no-op unless `_mode == "prompt"` and `#frontmatter-panel` is mounted;
   - if the panel owns focus, ask it to deactivate;
   - otherwise sync live pane text, show the panel if hidden, resync the panel from `self._stack.frontmatter`, focus it
     after refresh, and schedule the normal height update.

4. Wire the keymap in `PromptTextArea._on_key()` near the structural prompt stack chords (`Ctrl+Shift+J/K`,
   `Ctrl+Shift+H/L`, `Ctrl+-`). The handler should work in both insert and normal mode, always stop and prevent default,
   clear transient completion/arg-hint state, and then call `bar.toggle_frontmatter_panel()`. This keeps the chord from
   falling through to text insertion, completion acceptance, normal-mode editing, or app-level bindings.

5. Wire the same keymap in `FrontmatterPanel.on_key()` before mode-specific key dispatch, so pressing `Ctrl+Shift+-`
   while the panel is active deactivates it. Stop and prevent default there as well.

6. Update discoverability and comments:
   - help modal Prompt Input section should advertise `Ctrl+Shift+- / ,f / ---` as the xprompt properties panel path;
   - docstrings/comments that describe the frontmatter panel activation paths should mention the new toggle;
   - keep existing dense prompt subtitles unchanged unless testing shows the new wording still fits cleanly.

## Test Plan

Add focused widget-level tests in the existing frontmatter/prompt stack test style:

- `Ctrl+Shift+-` from insert mode opens and focuses an empty panel.
- `Ctrl+Shift+-` from normal mode opens and focuses the panel.
- Pressing the chord again while the empty panel owns focus deactivates it, hides it, clears empty frontmatter, and
  focuses the prompt in insert mode.
- With existing/populated frontmatter, pressing the chord from the prompt focuses the visible panel; pressing it again
  from the panel returns focus to the prompt while keeping the panel visible and preserving frontmatter.
- `ctrl+underscore` alias opens/toggles the panel as well.
- Feedback or approve-prompt mode ignores the chord and does not create a panel.
- Optional editing-submode coverage: inline edit cancels before closing; raw edit applies before closing, and invalid
  raw YAML keeps the raw editor active.
- Help modal tests assert the new prompt-input help entry.

Run targeted tests first:

```bash
pytest tests/ace/tui/widgets/test_frontmatter_panel.py tests/ace/tui/widgets/test_prompt_stack_keymaps.py tests/test_keymaps_display_help.py
```

Then run the repo check:

```bash
just check
```

## Risks And Mitigations

- Terminal key normalization is the main risk. Handling both `ctrl+shift+minus` and `ctrl+underscore` mitigates this.
- Prompt text areas aggressively refocus themselves on blur. The existing `_frontmatter_panel_owns_focus()` guard
  already protects panel focus; the new toggle should reuse that rather than adding a separate focus path.
- Raw YAML mode can contain invalid text. Deactivation must not close the panel if `_commit_raw()` refuses to parse it.
- The prompt footer is already dense, especially for multi-pane stacks. Help modal discoverability is safer than adding
  another always-visible subtitle token unless implementation testing shows there is room.
