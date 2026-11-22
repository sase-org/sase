---
title: Gate Debug
description: Inspect a gate bundle, hashes, and execution errors from sase's TUI.
---

# Gate Debug

This page names Gate Debug: the TUI overlay for inspecting a gate bundle, hashes, and
execution errors.

## Debugging a gate

Press `d` on any notification row or from an open plan, epic, question, launch,
custom-gate, or workflow HITL panel to open **Gate Debug**. The sudo review modal is the
exception: there `d` denies the request, so open Gate Debug from the notification row.
The overlay keeps the underlying form mounted, so closing it returns to the same
selected branch, checked group options, and typed feedback. Non-gate inbox rows use the
same view and show an explicit no-bundle state alongside their raw notification JSON.

Gate Debug loads bundle I/O and hash verification away from the TUI event loop. Its tabs
show the lifecycle overview, the canonical `request.json`, the terminal `response.json`
or `cancellation.json`, bounded execution error records, and the raw row from
`notifications.jsonl`. The overview re-verifies request and resource hashes live and
includes timeout, pending-action transport/staleness, and notification state. Missing,
malformed, or oversized artifacts render as diagnostics instead of preventing the modal
from opening.

| Key                 | Gate Debug action                                             |
| ------------------- | ------------------------------------------------------------- |
| `[` / `]`           | Switch tabs                                                   |
| `j` / `k`           | Scroll one line                                               |
| `Ctrl+D` / `Ctrl+U` | Scroll half a page                                            |
| `g` / `G`           | Jump to the top / bottom                                      |
| `y`                 | Copy the current tab's raw text                               |
| `Y`                 | Copy the gate bundle path                                     |
| `e`                 | Open the current tab's backing artifact in `$EDITOR`          |
| `d` / `Esc` / `q`   | Close Gate Debug and return to the underlying notification UI |

## Related

- [Command-backed interaction gates](notification-gates.md)
- [Notifications](notifications.md)
