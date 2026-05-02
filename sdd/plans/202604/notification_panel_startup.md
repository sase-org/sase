---
create_time: 2026-04-30 12:57:47
status: done
prompt: sdd/prompts/202604/notification_panel_startup.md
---
# Plan: Stop Notification Panel From Opening On Startup

## Context

`sase ace` opens the notification modal only through the `show_notifications` action, whose default app binding is `i`.
Startup code does not intentionally push `NotificationModal`.

The likely root cause is the pre-Textual terminal graphics probe in `src/sase/ace/tui/graphics/capability.py`. It writes
Kitty/terminal query escape sequences before `App.run()`, including a Kitty query with `i=31337`. If the terminal or
tmux returns the reply after the probe timeout, those bytes remain queued on stdin. Once Textual starts, it can
interpret leaked reply bytes as normal user input, and the literal `i` opens notifications. The file already documents
the general risk: once Textual owns stdin, probe replies are indistinguishable from user input.

## Implementation

1. Make the graphics probe consume and discard any late terminal response bytes before returning control to Textual.
2. Restore terminal mode with input flushing semantics so queued probe replies cannot survive into `App.run()`.
3. Remove the extra Primary DA query if it is not needed for the current boolean capability result, reducing the amount
   of non-Kitty terminal reply data we can accidentally leak.
4. Add focused unit tests around the probe cleanup behavior using mocked `os.read`, `select.select`, `termios`, and
   `fcntl`, rather than requiring a real TTY.
5. Run the targeted graphics capability tests first, then run `just install` and `just check` per repo instructions
   after code changes.

## Validation

- Targeted tests should prove that the probe still reports Kitty support when an OK response is captured.
- Targeted tests should prove that stdin is flushed when the probe exits.
- Existing capability detection behavior should remain unchanged for env-level decisions and injected `probe_func`
  tests.
