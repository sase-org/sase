---
title: Notification tags
description: Notification tags and the colors and icons used in notification tabs.
---

# Notification tags

This page describes notification tags and their tab colors and icons.

## Tags

Senders may attach `tags` to a notification. Tags are normalized when notifications are
created: whitespace is trimmed, empty values are dropped, values are lowercased, and
duplicates are removed while preserving sender order. Tags do not change priority, error
classification, unread counts, mute, snooze, or auto-dismiss matching.

Successful visible and hidden user-agent completion notifications that jump back to the
agent row carry the `done` tag. Failed user-agent notifications do not carry `done`;
failures remain error reports.

In sase's TUI, tags create modal tabs above the notification list after the synthetic
`Gates`, declared panel tabs, `Errors`, `General`, and `Done` tabs. **Every notification
belongs to exactly one tab.** The Rust core decides which one, by this precedence, so
the panel, the top-bar indicator, and the mobile snapshot always agree:

1. `Snoozed` — muted with a `snooze_until` wake time
2. `Muted` — muted with no wake time
3. the gate's declared `presentation.panel`
4. `Gates` — a `PlanApproval`, `EpicApproval`, `UserQuestion`, `HITL`, `LaunchApproval`,
   `TaskTriage`, or `CustomGate` action (the core still keys this synthetic tab `hitl`;
   only the display label is `Gates`)
5. `Errors` — an error report
6. the **first** stored tag, in sender order
7. `General` — everything else

A row with two tags therefore occupies one tab and is counted once; dismissing it
removes at most one tab. Later tags still render as badges on the row, but they do not
create tabs.

A gate may declare `presentation.panel` to place its notification in a named panel tab.
Panel names are stripped, lowercased, limited to 32 characters, and may contain
lowercase letters, digits, underscores, and hyphens. The synthetic names `errors`,
`gates`, `general`, `hitl`, `muted`, and `snoozed`, along with names beginning with
`__`, are reserved. A panel name matching a tag merges into that tag's tab, which then
sorts as a panel tab.

### Tab colors

Every tab renders with a color, so a brand-new tag tab is never colorless. The color
resolves by precedence, highest first:

1. [`ace.notification_tabs.<tab>.color`](../config/ace-behavior.md#acenotificationtabs),
   when non-empty
2. the color a sender declared on a notification in that tab
3. the built-in default for a tab sase's TUI ships knowing about (`hitl`, `errors`,
   `beads`, `general`, `snoozed`, `muted`)
4. a stable auto-palette entry derived from the tab key, so the same tag keeps the same
   color across restarts

A sender declares a color with `presentation.color` on a gate, or the `color` field of
`sase notify create` JSON input. It must be a `#RRGGBB` hex string; anything else is
rejected at write time rather than stored as junk that would render as an unstyled chip.
When several rows in a tab declare a color, the tab wears the one from the row the panel
lists first — the most recent activity — so the color is deterministic rather than
dependent on render order.

The `done` tab is intended as the quick path for successful agent completions; reading
or jumping to a done Agents-tab row dismisses its matching completion notification, so
it disappears from the `Done` tab after the next refresh. Failed agent notifications
stay untagged by `done` and continue to render under the `Errors` tab.

### Tab icons

Every tab renders with an icon, so the top-bar indicator's chips and the modal's tab
strip are self-identifying instead of relying on color alone. The icon resolves by
precedence, highest first:

1. [`ace.notification_tabs.<tab>.icon`](../config/ace-behavior.md#acenotificationtabs),
   when non-empty
2. the icon a sender declared on a notification in that tab
3. the built-in default for a tab sase's TUI ships knowing about (`hitl`, `errors`,
   `beads`, `general`, `snoozed`, `muted`)
4. a default keyed by the tab's own kind (`panel`, `tag`), so a tab sase's TUI has never
   heard of still gets a glyph that means something about what it is
5. `•`, reachable only when a tab arrives with no kind at all

Unlike color, an icon never falls back to a hashed auto-palette entry: an arbitrary
color is still a usable identifier, but an arbitrary glyph would teach the reader
something false, so the chain always bottoms out at a meaningful or honestly generic
mark instead. The bundled defaults are `⚑` `hitl`, `✖` `errors`, `◈` `beads`, `✉`
`general`, `☾` `snoozed`, and `⊘` `muted`; a gate-declared panel with no closer match
falls to the kind default `◆`, and a tag tab falls to `#`.

sase's TUI resolves icons over the whole ordered tab list before rendering. Configured
icons, sender-declared icons, and the bundled defaults are never rewritten. If two
SASE-chosen generic icons from rung 4 or 5 would collide, sase's TUI walks the tab key
and uses the first unused ASCII letter or digit from that key: `axe` can become `a`,
then `x`, then `e`; `file-hooks` can become `f`; `123-deploy` can become `1`. If every
alphanumeric character in the key is already claimed, the tab keeps the generic mark
rather than inventing a false glyph. Explicit duplicates remain explicit: if two
configured tabs or two gates choose the same glyph, sase's TUI renders that glyph for
both. Run `sase doctor -C config.notification_tabs` to report configured duplicates.

A sender declares an icon with `presentation.panel_icon` on a gate (see
[Command-backed interaction gates](notification-gates.md#command-backed-interaction-gates-1)
below); there is no raw-notification equivalent, since a raw row's own `icon` field
styles the row, not its tab. When several rows in a tab declare a `panel_icon`, the tab
wears the one from the row the panel lists first — the most recent activity — exactly as
color does. A `panel_icon` is donated only to the tab named by the same gate's
`presentation.panel`, so a muted or snoozed row does not carry its panel glyph into
`Snoozed` or `Muted`.

## Related

- [Notifications](notifications.md)
- [Notification types](notification-types.md)
