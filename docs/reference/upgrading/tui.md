---
title: TUI migration notes
description:
  Upgrade notes for sase tui command names, aliases, query tokens, and stored layouts.
---

# TUI migration notes

This page records TUI changes an upgrading reader needs. Newest notes first. Current
behavior lives on the [TUI](../tui/index.md) pages.

## Command name `sase tui` {#command-name-sase-tui}

The TUI command is `sase tui`. Settings still live under the `ace:` section of
`sase.yml` (for example `ace.keymaps` and `ace.page_size`). See
[Launching the TUI](../tui/launching.md).

## `--model-size` and tab aliases {#model-size-and-tab-aliases}

`--model-size` (`big` or `little`) remains accepted as an alias of `--model-tier`
(`large` or `small`). Startup `--tab` still accepts `axe` for `services` and
`changespecs` / `patches` for `artifacts`. See the generated [`sase tui`](../cli/tui.md)
page.

## Agent query tokens {#agent-query-tokens}

Older `agent_query` spellings still parse. A known older token such as `age>2h` or
`type:run` appends the unified replacement hint when it fails:

| Older (`agent_query`)                                                                                                             | Current (`agents-live`)                    |
| --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| `type:workflow` / `type:run` / `type:running`                                                                                     | `kind:workflow` / `kind:agent`             |
| `age>2h`, `age>=2h`                                                                                                               | `until:2h` (started at or before 2h ago)   |
| `age<5m`, `age:5m`                                                                                                                | `since:5m` (started at or after 5m ago)    |
| `status:foo` (substring)                                                                                                          | `status:FOO` (enum, completion-assisted)   |
| `project:foo` (substring)                                                                                                         | `project:foo` (exact; completion-assisted) |
| `tribe:` (bare, "any tribe")                                                                                                      | no direct equivalent; OR explicit tribes   |
| everything else (`cl:`, `machine:`, `pinned:`, `needs:input`, `source:axe`, `text:`, booleans, `AND`/`OR`/`NOT`, parens, quoting) | unchanged spelling                         |

See [Agents tab search and modes](../tui/agents-tab-modes.md).

## Prompt history store {#prompt-history-store}

A `~/.sase/prompt_history.json` store is migrated into monthly shards under
`~/.sase/prompt_history/` before normal reads and writes when the shard directory has
not already been created. See [Prompts overlay](../tui/prompts-overlay.md).

## Config and keymap aliases {#config-and-keymap-aliases}

These older keys remain accepted:

- `ace.artifacts.commits.default_query` is an alias of
  `ace.artifacts.stitches.default_query`.
- Gate-modal `activate_control` is an alias of `submit_primary`.
- Stale `ace.keymaps.app.search_forward` and
  `ace.keymaps.modes.leader_mode.keys.edit_query` overrides are ignored with a warning;
  use `ace.keymaps.modes.leader_mode.keys.search_forward` and
  `ace.keymaps.app.edit_query`.
- `tasks.history_limit` is an alias of `procs.history_limit`.
- Workflow `meta_changespec` is an alias of `meta_patch`.

See [Filtering](../tui/filtering.md), [Global controls](../tui/global-controls.md),
[Procs tab](../tui/procs-tab.md), and
[Agents tab main deck](../tui/agents-main-deck.md).

## In-process pager {#in-process-pager}

Paging runs the SASE pager in-process and passes the structured document directly. See
[SASE Pager](../tui/pager.md) and [`sase pager`](../cli/pager.md).

## Detached procs {#detached-procs}

`sase.procs.submit_detached_proc()` records the same unattributed `command` row as
`sase.procs.submit_proc(session_id=None)`. Historical `detached` rows remain visible. A
hidden `--kind` filter remains on `sase proc list` for those rows. See
[Procs tab](../tui/procs-tab.md).

## Dismissed-name prefix {#dismissed-name-prefix}

Older dismissed bundles may still contain `YYmmdd.<base>` names. Bare `%wait` skips
those prefixed candidates so it anchors on a live, visible agent. See
[Agent statuses](../tui/agent-statuses.md#legacy-dismissed-name-prefix).

## HITL and launch-request fallbacks {#hitl-and-launch-request-fallbacks}

Older HITL bundles retain a direct response-file fallback. Launch approval retains the
older launch-request fallback alongside hash-verified command bundles. See
[Notifications modal](../tui/notifications-modal.md) and
[Launch Approval](../tui/agent-workflows.md#launch-approval).

## Glossary lane and `sase/sase.yml` {#glossary-lane-and-sasesaseyml}

The `SASE CONTEXT / GLOSSARY` lane shows audited events from the retired
`sase glossary read` command. Current `sase memory read glossary:<keyword>` reads
surface in the `MEMORY` lane. Reports from those older events may name a `sase/sase.yml`
source. See [Agents tab main deck](../tui/agents-main-deck.md).

## Prompt stack restore and macro sources {#prompt-stack-restore-and-macro-sources}

Older stash rows and failed-launch recovery rows have no saved cursor, so they restore
to the last pane at end of text. Labeled compatibility macro sources remain browseable
and read-only; they are never new-write destinations. See
[Prompt stacks](../tui/prompt-stacks.md) and [Snippets](../tui/snippets.md).

## Session member suffixes {#session-member-suffixes}

sase's TUI still canonicalizes older dotted suffixes (`.plan`, `.2`, `.code`) and
single-dash suffixes (`-plan`, `-2`, `-code`) when reading older artifacts. New
plan-session metadata stores double-dash `role_suffix` values. See
[Agent workflows](../tui/agent-workflows.md).

## Artifacts Agent pane {#artifacts-agent-pane}

Agent history lives in the Agents tab Archive (`,a`). The Artifacts ▸ Agent sub-tab is
off by default (`artifacts_agent_pane_retired`);
`sase flag disable artifacts_agent_pane_retired` restores it. See
[Tabs and panes](../tui/tabs-and-panes.md) and
[Files and preview](../tui/files-and-preview.md).

## Keymap moves {#keymap-moves}

- `,n` is replaced by `Enter` on the Agents tab. The direct Patch jump survives as the
  unbound `jump_to_agent_patch` command.
- The Agents-tab detail-view picker is gone; the tab always shows agent data decks and
  cards. Press `p` for the deck picker.
- Glossary-panel bindings folded into Memory-panel actions. `ace.keymaps.glossary` is
  still accepted in config for one release, but it is inert. `sase doctor` warns when a
  loaded config layer sets it and points at `ace.keymaps.memory`.
- `ace.prompt_completion.history_word_min_length` is replaced by `word_min_length`.
- Launch Control rows use the grid `ownership gutter | name | value/model | state`. Kind
  labels such as `launch` and `setting` are not a column.

See [Agents tab](../tui/agents-tab.md), [Agent statuses](../tui/agent-statuses.md),
[Global controls](../tui/global-controls.md),
[Prompt completion](../tui/prompt-completion.md), and
[Launch Control](../tui/launch-control.md).

## Auto-name migration {#auto-name-migration}

`sase agent names migrate-auto` moves older generated names into the permanent
namespace. Pass `--force` to rerun after the migration marker is present, or `--json`
for machine-readable output. See [Agent workflows](../tui/agent-workflows.md).

## Related

- [TUI hub](../tui/index.md) — current TUI behavior.
- [Upgrading](index.md) — other upgrade notes.
