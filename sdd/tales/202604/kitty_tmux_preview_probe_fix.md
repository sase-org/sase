---
create_time: 2026-04-30 03:41:52
status: done
prompt: sdd/prompts/202604/kitty_tmux_preview_probe_fix.md
---
# Plan: Fix Kitty Image Preview Detection In tmux

## Goal

Make ACE inline image previews work in the user's current Kitty-backed tmux session, where
`kitten icat --passthrough tmux --transfer-mode stream <png>` succeeds but ACE currently falls back with:

> terminal family is not known to support Kitty placeholders

The fix should keep graceful fallback behavior for terminals that do not support Kitty graphics, while allowing an
active Kitty graphics probe to prove support when tmux hides the outer terminal identity.

## Current Findings

The prior `sase-1i` plan added image attachments and TUI preview plumbing. The relevant preview path is:

- `src/sase/main/ace_handler.py` calls `detect_graphics_capability()` before `AceApp.run()`.
- `AceApp` stores the resulting `GraphicsCapability`.
- The notification modal and agent file panel call `image_preview(...)`, which renders a `KittyImageRenderable` only
  when `capability.supported` and `protocol == "kitty"`.

The failure is earlier than rendering. In this tmux session the process environment reports:

- `TERM=tmux-256color`
- `TERM_PROGRAM=tmux`
- `TMUX=...`
- no Kitty-specific environment variables
- no advertised `COLORTERM=truecolor`

The current detector requires a known terminal family (`kitty` or `ghostty`) before probing. It also requires truecolor
advertisement before probing. That is too conservative for tmux passthrough: tmux commonly strips the outer terminal
identity, yet Kitty graphics can still work through DCS passthrough, as shown by the user's working
`kitten icat --passthrough tmux` command.

## Design

Treat the active Kitty graphics probe as the source of truth when tmux passthrough is available or when the user
explicitly forces Kitty probing with `SASE_TUI_GRAPHICS=kitty`.

Concretely:

- Preserve `SASE_TUI_GRAPHICS=off` as an immediate disable.
- Preserve known-terminal fast eligibility for Kitty/Ghostty outside tmux.
- In tmux, attempt the active Kitty graphics probe even when `_terminal_family()` returns `None`, because the outer
  terminal identity is not reliable inside tmux.
- Do not let missing `COLORTERM=truecolor` block an active probe in tmux or force mode. The detector can still record
  whether truecolor was advertised, but successful Kitty probing should enable the feature.
- Keep the existing fallback for unknown non-tmux terminals that have no force override.
- Keep `probe=False` behavior deterministic for tests: it may assume support only when the terminal is known, tmux
  passthrough is present, or force mode is set.

This keeps the change narrow and avoids adding a dependency on the external `kitten` binary. The existing internal probe
already emits Kitty protocol queries and wraps them for tmux, which is the right compatibility layer for ACE.

## Implementation Steps

1. Update `src/sase/ace/tui/graphics/capability.py`.
   - Split "eligible to probe" from "known terminal family".
   - Allow eligibility when `passthrough == "tmux"` or `SASE_TUI_GRAPHICS` is a force value.
   - Reorder checks so tmux/force sessions can reach the active probe even without known terminal family or truecolor
     advertisement.
   - Improve unsupported reasons so diagnostics distinguish "not probed because unknown non-tmux terminal" from "probe
     attempted but failed".

2. Add focused tests in `tests/ace/tui/graphics/test_capability.py`.
   - Unknown non-tmux terminals remain unsupported and do not probe.
   - Unknown tmux terminals call the probe with `passthrough="tmux"` and succeed when the probe succeeds.
   - Unknown tmux terminals report a probed failure when the probe fails.
   - Missing `COLORTERM` does not block a successful tmux probe.
   - `SASE_TUI_GRAPHICS=kitty` forces probing outside tmux even with an unknown terminal and missing truecolor
     advertisement.
   - `SASE_TUI_GRAPHICS=off` still wins.

3. Update documentation.
   - Adjust `docs/agent_images.md` to say capability detection uses active probing for Kitty/Ghostty, tmux passthrough,
     or force mode.
   - Clarify that truecolor advertisement is recorded and useful for placeholders, but absence of `COLORTERM` does not
     block a successful active probe in tmux/force scenarios.

4. Verify.
   - Run `just install` first if needed for this workspace.
   - Run the targeted graphics tests.
   - Run `just check`, because this repo requires it after file changes.
   - Optionally run a quick local Python detection check with the current tmux-shaped environment and a stub successful
     probe to confirm the reason/status shape.

## Risks And Guardrails

- The active probe must still run before Textual starts; no change to that call site is planned.
- Enabling support after a successful probe but without `COLORTERM=truecolor` assumes the terminal/tmux stack can
  preserve truecolor SGR well enough for Kitty Unicode placeholders. The user's working Kitty/tmux image command makes
  this a reasonable tradeoff, and fallback remains available through probe failure or `SASE_TUI_GRAPHICS=off`.
- CI must not depend on a real terminal. All tests should use injected `probe_func` stubs.
