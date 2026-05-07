---
create_time: 2026-05-07 10:25:04
status: done
prompt: sdd/prompts/202605/notification_panel_startup_1.md
---
# Diagnose and Fix Startup Notification Panel

## Problem

`sase ace` sometimes opens the notification modal immediately on startup even though the user did not press the
configured `show_notifications` key (`i`).

## Root-Cause Hypothesis

The notification code itself does not auto-open the modal during startup. The startup flow initializes notification
counts and later polls/toasts, but the only direct modal entry point is the `show_notifications` app binding.

The suspicious startup-only path is terminal graphics detection:

- `handle_ace_command()` calls `detect_graphics_capability()` before `AceApp.run()`.
- The default active Kitty probe writes a Kitty graphics query to the terminal.
- Kitty replies with a control sequence containing `i=31337`.
- `_probe_kitty_graphics()` drains stdin for only a very short fixed window before Textual starts reading.
- If the terminal reply arrives late or is split across reads, Textual can receive the `i` byte as user input and
  dispatch the app-level `show_notifications` binding.

This explains why the issue is intermittent and startup-only.

## Plan

1. Confirm there are no intentional notification modal opens in the startup and auto-refresh paths.
2. Add a focused regression test that simulates a delayed Kitty probe reply and verifies that default graphics detection
   does not leave startup input bytes capable of becoming app keybindings.
3. Change graphics detection so `sase ace` does not perform unsolicited active terminal probes by default:
   - Known Kitty/Ghostty terminals can be trusted from environment detection.
   - Unknown terminals, including tmux with hidden outer-terminal identity, should not be actively probed unless the
     user explicitly opts in with `SASE_TUI_GRAPHICS=kitty` or another force value.
   - Explicit disable values continue to disable graphics.
4. Keep the existing active probe implementation available for forced probing and tests, but make the default startup
   path side-effect-free with respect to stdin.
5. Update affected tests to document the new contract and preserve coverage for the forced active-probe path.
6. Run the targeted graphics/keymap/TUI tests, then run `just install` if needed and `just check` per repo instructions.

## Expected Outcome

Startup no longer emits terminal probe replies that can be misinterpreted as normal keypresses, so the notification
modal will only open from the configured keymap or command paths.
