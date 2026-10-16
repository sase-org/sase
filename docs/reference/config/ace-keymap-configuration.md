---
title: "ACE keymap configuration"
description: "Configuration behavior for SASE Admin Center and TUI keymaps."
---

# ACE keymap configuration

This page explains how configurable keymap scopes interact. The generated
[TUI keymap reference](../tui/keymaps.md) lists action names and current bindings; the
generated [configuration reference](tui.md#ace-keymaps) documents the config shape and
defaults.

## `ace.keymaps`

Keymaps are scoped to the surface that handles them. An active pane or modal can reuse a
key that belongs to another surface because only one scope receives the event. App-level
actions apply across surfaces and have a small set of intentional overlaps between
mutually exclusive tabs.

The [keymap reference](../tui/keymaps.md) groups bindings by surface, including the
application, Admin Center panes, prompt panels, and prefix modes. Use it as the single
catalog of action names and bindings.

### Admin Center scopes

Gate, Config, Statistics, Memory, Snippets, Projects, Machines, and Tools keymaps are
active only while their surface has focus. Their actions do not become application
shortcuts. Memory and Snippets also have fixed numbered-chip gestures; those digits are
part of the panel interaction rather than configurable action bindings.

The Projects keymap serves the Projects, Repos, and Workspaces sub-tabs. Some actions
are limited to one sub-tab: project creation and editing belong to Projects, while the
shared project picker and filter clearing apply to Repos and Workspaces. The selected
sub-tab and focused filter determine which actions handle input.

### Application scope

`open_config_center` also controls the Admin Center home page's resume action.
Agents-tab actions can open a pending gate or Patch, and the action chooser appears when
both apply. Starting an agent from a Patch uses the most recently launched VCS macro
when available; otherwise it opens a home-workspace prompt.

Remote-agent actions are available through the command palette. A configured key only
acts when the Agents tab and selected remote row support that action. Query editing uses
the shared app action across Patches, Stitches, Plans, Files, Services, and Agents; the
Agents tab also has its own filter action and inline deck search.

The saved-query prefix arms slot selection. Its digit subkeys are fixed slot
identifiers, not separate configurable bindings.

### Prefix modes

The built-in Fold, Copy, Leader, and Bang modes can be reconfigured, and custom modes
can be added. A custom mode defines exactly one of `shell` or `action`. See the
generated [keymap reference](../tui/keymaps.md) for the built-in mode bindings and the
[configuration reference](tui.md#ace-keymaps) for the mode schema.

### Validation

Invalid keys fall back to their defaults. Duplicate bindings within a scope are warned
about, and conflicts between custom-mode prefixes and app bindings are detected. A small
allowlist permits known app-level overlaps whose actions cannot be active on the same
surface. An override that collides with an action outside that allowlist is logged and
reverted to its default while the rest of the keymap remains in place.

The `glossary` scope is accepted as compatibility input but has no effect: it defines no
defaults or active bindings. Configure the Memory panel through `ace.keymaps.memory`.

## Related

- [TUI keymaps](../tui/keymaps.md) — generated action names and bindings.
- [TUI configuration](tui.md) — generated keymap settings and defaults.
- [SASE Admin Center](../tui/admin-center.md) — Admin Center panes and behavior.
