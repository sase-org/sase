---
create_time: 2026-05-28 22:19:39
status: done
prompt: sdd/prompts/202605/tui_prompt_live_completion.md
---
# TUI Prompt Live Completion Plan

## Goal

Add fast, flow-preserving live completion to the ACE prompt input, inspired by the existing Neovim/LSP experience,
without adding typing latency or changing submit/snippet/navigation behavior unexpectedly.

## Constraints From Current Code

- The prompt input is `PromptTextArea`, a Textual `TextArea`; it does not have `Input`'s built-in suggester support.
- Existing manual completion is behind `Ctrl+T` and uses `_file_completion_active`; while active, `Enter` accepts a
  completion instead of submitting the prompt.
- The existing completion panel in `PromptInputBar` increases the docked prompt bar height, so showing it automatically
  while typing would visibly move the UI.
- Xprompt catalog construction is too slow for the key path, but filtering a warm list is cheap.
- Path completion uses `os.scandir()` and must remain explicit for the first version.
- Shared editor completion behavior already exists in Rust, but `sase_core_rs` does not expose it yet. A Python/TUI
  implementation is the practical first slice; PyO3 parity can follow.

## Product Shape

Implement default automatic completion as a soft suggestion, not an auto-open menu:

- Render the best warm suggestion in the prompt bar subtitle, e.g. `[^L] accept #review`.
- Do not set `_file_completion_active` for automatic suggestions.
- Keep `Enter` as submit, `Tab` as snippet/tabstop behavior, and `Ctrl+N`/`Ctrl+P` as existing MRU/completion navigation
  depending on explicit completion state.
- Accept the soft suggestion only with `Ctrl+L`.
- Leave explicit `Ctrl+T` as the rich panel path.

This gives as-you-type completion without layout shift or key semantic changes. Automatic popup menus can be added later
behind config once the non-disruptive path is proven.

## Implementation Steps

1. Add prompt completion settings.
   - Extend `ace` config with `prompt_completion.auto`, `debounce_ms`, `auto_file_paths`, and `max_auto_rows`.
   - Default to `auto: soft`, `debounce_ms: 90`, `auto_file_paths: false`.
   - Store parsed settings on `AceApp`, with a fallback default for tests/minimal apps.

2. Cache xprompt assist entries per project in `PromptTextArea`.
   - Replace the single project cache with a project-keyed cache.
   - Warm the current project's entries in a Textual worker when the prompt bar mounts.
   - Auto completion must use only warm entries. If entries are cold, schedule a warm refresh and show nothing.
   - Manual `Ctrl+T` may still build synchronously as a fallback, but should reuse cached entries whenever available.

3. Add a soft completion model and builder.
   - Represent a soft suggestion as candidate + completion kind + absolute replacement range + display text.
   - Classify only cheap contexts on each edit: xprompt/slash-skill token, directive token, xprompt arg name/value, and
     optionally snippet triggers if snippets are already warm.
   - Skip automatic path completion unless `auto_file_paths` is explicitly enabled.
   - Prefer exact current behavior for accept semantics: xprompt suggestions use the same xprompt skeleton logic as
     `Ctrl+T`; directive and arg completions use normal replacement; snippet suggestions expand the snippet template.

4. Debounce and discard stale suggestions.
   - Increment a generation counter after relevant text/cursor changes.
   - Schedule suggestion computation with `set_timer(debounce_ms / 1000)`.
   - On fire, compare generation/text/cursor before rendering.
   - Clear pending/visible soft suggestions on submit, cancel, escape, normal mode, explicit completion, snippet
     tabstops, blur-sensitive mode changes, and text that no longer matches the replacement range.

5. Render without layout movement.
   - Use `PromptInputBar` border subtitle for soft suggestions.
   - Preserve the existing mode subtitles when no suggestion is visible.
   - Keep the existing completion panel exclusively for explicit completion and xprompt arg hint panels.

6. Tests.
   - Unit tests for cached xprompt candidate building.
   - Widget tests for debounced xprompt, slash-skill, directive, and xprompt-arg suggestions.
   - Regression tests that `Enter` submits with a soft suggestion visible, `Tab` still expands snippets, and `Ctrl+T`
     still opens/accepts explicit completion.
   - A cold-cache test that automatic completion does not call catalog construction synchronously.

## Validation

- Run focused widget tests for prompt completion.
- Run `just install` if needed, then `just check` because source files will change.
- If failures are broad or slow, at minimum run the focused tests plus `just lint`/`just test` subsets and report any
  skipped validation clearly.

## Follow-Up Architecture

After the Python/TUI slice lands, add PyO3 bindings in `../sase-core` for the Rust editor completion classifier/builders
and migrate the TUI soft/explicit builders to those APIs. Do not add an LSP client inside ACE unless future prompt
features need process-isolated hover/diagnostics/definition behavior.
