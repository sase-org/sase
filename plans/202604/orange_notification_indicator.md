---
create_time: 2026-04-27 16:20:21
status: done
---
# Orange Priority Notification Indicator

## Problem

The ACE top-bar `NotificationIndicator` currently renders the primary segment in red (`#FF4444`) whenever at least one
unmuted unread notification is classified as priority. The user wants that high-priority unread indicator to be orange
instead of red.

The existing implementation already has the right notification bucketing:

- `src/sase/notifications/priority.py` centralizes priority classification.
- `src/sase/ace/tui/actions/agents/_notifications.py` splits unread notifications into `priority`, `rest`, and `muted`
  and passes those counts into the widget.
- `src/sase/ace/tui/widgets/notification_indicator.py` is the only product-code location that hard-codes the top-bar
  priority indicator color.

This should therefore be a narrow visual semantics update, not a behavior or data-model change.

## Goals

1. Render the top-bar notification indicator with an orange background when `priority > 0`.
2. Keep the existing priority/rest/muted count behavior unchanged.
3. Keep gold for regular unread inbox notifications and cyan for muted-only unread notifications unchanged.
4. Update tests and user-facing docs so the indicator semantics say orange instead of red.

## Non-goals

- Do not change priority classification rules.
- Do not change how notification counts are computed or refreshed.
- Do not change notification storage, sender APIs, toast severity, modal action handling, or snooze/mute behavior.
- Do not change the notification modal section taxonomy unless explicitly requested. The modal currently uses red for
  the `PRIORITY` section header; the user asked specifically about the notification indicator, so this plan leaves the
  modal section header color alone.

## Color Choice

Use `#FF8700` for the priority indicator background:

- It is already documented elsewhere in the codebase as the orange used for retrying state, so it is a local palette
  match rather than a new arbitrary shade.
- It is visually distinct from regular unread gold (`#FFD700`) and muted-only cyan (`#5FAFAF`).
- It preserves the existing dark foreground style (`bold #1a1a1a on ...`) and only swaps the background color.

If the implemented screenshot or terminal rendering reads too close to gold, the fallback would be a deeper orange such
as `#FF5F00`, but the first pass should use the established `#FF8700`.

## Implementation Plan

1. Update `src/sase/ace/tui/widgets/notification_indicator.py`.
   - Change the docstring and argument documentation from red to orange.
   - Replace the priority style background from `#FF4444` to `#FF8700`.
   - Leave the rendered text shape unchanged: `✉ {priority}+{rest}` plus optional muted `·{muted}`.

2. Update `tests/test_notification_indicator.py`.
   - Rename red-specific priority tests to orange-specific names.
   - Replace `#FF4444` expectations with `#FF8700`.
   - Keep count assertions exactly the same to verify this is a color-only change.

3. Update documentation references to the top-bar indicator color.
   - `docs/notifications.md`: in "Top-Bar Indicator", change the priority bullet from Red to Orange.
   - `docs/ace.md`: change the notification indicator sentence from red to orange.
   - Leave the `docs/notifications.md` modal section table alone unless the product requirement is broadened to the
     modal section header too.

4. Consider whether to update historical plan/spec files.
   - Do not rewrite old specs/plans by default; they document the original request and implementation history.
   - If grep noise becomes confusing, add the new plan file as the current source of intent instead of modifying the old
     plan.

## Verification

Run focused tests first:

```bash
just install
uv run pytest tests/test_notification_indicator.py tests/test_notification_priority.py
```

Then run the repo-required final check after code changes:

```bash
just check
```

Expected focused-test outcome:

- Priority-only and priority-plus-muted indicator cases still render the same plain text.
- Those priority cases assert `#FF8700` instead of `#FF4444`.
- Regular unread and muted-only cases remain unchanged.

## Risk

The main risk is semantic ambiguity: "priority" rows inside the notification modal may remain red while the top-bar
indicator becomes orange. That is intentional for this request because the ask is specific to the indicator, but it is
worth calling out in the final response so the user can decide whether the modal section header should also change.
