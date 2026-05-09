---
create_time: 2026-05-09 13:23:52
status: done
prompt: sdd/prompts/202605/agents_count_header_format.md
---
# Plan: Agents Tab Count Header Format

## Goal

Change the Agents tab top info strip in `sase ace` from:

```text
Agents(9): 1 running · 1 waiting · 0 unread · 7 read
```

to:

```text
9 Agents [1 running · 1 waiting · 0 unread · 7 read]
```

The rest of the strip should keep its existing behavior, including optional filter text, view badge, grouping badge, and
auto-refresh countdown.

## Current Shape

The visible header string is presentation-only TUI code. The count values are computed in
`src/sase/ace/tui/actions/agents/_display_detail.py` and passed to `AgentInfoPanel.update_agent_counts()`. The string
form and Rich styles are composed in `src/sase/ace/tui/widgets/agent_info_panel.py`.

The requested change should not move counting logic into a backend layer and should not alter status bucket semantics.
It only changes the order and punctuation of the existing rendered text.

Relevant tests:

- `tests/ace/tui/widgets/test_agent_info_panel.py`
- `tests/ace/tui/test_startup_loading_indicators.py`

## Implementation Steps

1. Update `AgentInfoPanel._update_display()` so the loaded state starts with the styled total count, then `Agents`, then
   a bracketed metric list.
2. Keep the current individual styles for total, running, waiting, unread, and read numbers.
3. Keep loading behavior unchanged as `Agents: …`, because that is a different transient state and the user request
   targets loaded count text.
4. Update tests that assert the old `Agents(N): ...` form to assert the new `N Agents [...]` form.
5. Run focused tests for `AgentInfoPanel` and startup loading.
6. Because this repo requires it after changes, run `just install` if needed and then `just check` before finishing.

## Risks And Checks

The main risk is accidental Rich style regression because the total count moves before the `Agents` label. The existing
style test should still verify distinct styles for all count numbers after the test expectations are adjusted only where
necessary.

The new text is slightly longer by one bracket pair but removes punctuation around `Agents(N):`; the optional
filter/view/group/countdown segments still append after the metric strip with the same spacing.
