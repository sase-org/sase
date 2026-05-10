---
create_time: 2026-05-10 10:50:40
status: done
prompt: sdd/prompts/202605/artifacts_for_marked_agents.md
---
# Plan: `A` keymap aggregates artifacts from all marked agents

## Goal

Extend the agents-tab `A` keymap (`open_agent_artifacts`) so that, when one or more agents are marked via the `m`
keymap, the artifact picker panel shows the union of artifacts from **all marked agents** instead of only the focused
agent's artifacts. With no marks, behavior is unchanged.

This brings `A` in line with the established "bulk mode if marks exist, else focused agent" pattern already used by
other agents-tab actions (`action_kill_agent`, `action_add_agent_tag`, wait-resume).

## Why

Mark + bulk-action is the standard power-user flow on the Agents tab. Today, `A` is the lone agent-level action that
ignores `_marked_agents` — users who want to scan artifacts across a set of related agents (e.g. all phases of an epic,
or all retried siblings) have to press `A` once per agent and dismiss the modal each time. A single combined picker is
the natural interaction.

## Product design

### Trigger and dispatch

`action_open_agent_artifacts` (in `src/sase/ace/tui/actions/agents/_panel_artifacts.py`) currently:

1. Returns early on non-Agents tab.
2. Closes any tracked artifact tmux pane and returns (so `A` toggles).
3. Reads the focused agent, lists its artifacts, opens the picker.

New flow inserts a bulk branch between steps 2 and 3 — mirroring `action_kill_agent` (`_kill_action.py:396`) and
`action_add_agent_tag` (`_tagging.py:43`):

- If `self._marked_agents` is non-empty: collect artifacts from every marked agent (resolved via
  `[a for a in self._agents_with_children if a.identity in self._marked_agents]`, the same pattern the kill / tag / wait
  flows use).
- Otherwise: the existing single-agent flow.

The tmux-pane toggle short-circuit stays at the top so `A` continues to close a live artifact pane regardless of marks.

### Aggregation

For each marked agent, call the existing `self._list_selected_agent_artifacts(agent)` helper and concatenate. Agents
that have no artifacts (status not yet DONE/FAILED, or empty artifacts dir) contribute nothing — they are silently
skipped. Order: marked agents in their current `_agents_with_children` order; within each agent, the order returned by
`list_agent_artifacts`.

Empty / edge cases:

- **No marked agents remain alive** (all stale): notify `"No marked agents remain"` and return. Mirrors
  `_tagging.py:50`.
- **Marked agents exist but the union of their artifacts is empty**: notify `"No artifacts found in marked agents"` and
  return.
- **Single marked agent with no artifacts**: same notification as the bulk empty case (do not silently fall back to
  focused-agent behavior — marks are an explicit user intent).

### Disambiguation in the picker

When artifacts come from multiple agents, label collisions become likely (every coder agent has a `proposal.md`,
`change.diff`, etc.). The picker must make it obvious which agent each artifact belongs to. Two-part change to
`AgentArtifactSelectionModal`:

1. **Per-row agent prefix.** The constructor accepts an optional parallel list of agent labels
   (`agent_labels: list[str | None] | None`). When present and the entry is non-`None`, the option's first line is
   rendered as `{agent_label}  ·  {artifact_label}  [kind]`. When absent or `None` (the single-agent path), rendering is
   unchanged. Prefix uses `agent.display_name` (with an optional `@agent_name` suffix when present), truncated to keep
   total label width within the existing `_MAX_LABEL_LEN` budget.

2. **Modal title.** Title becomes `Agent Artifacts  [N from M agents]` when `M > 1`, otherwise unchanged.

The modal stays a flat list (no per-agent group headers / dividers). A flat list keeps in-modal mark (`m`), `Open All`
(`A`), and selector keys working exactly as today; grouping would require reworking the selector-key budget and footer
hints for marginal benefit.

### Open behavior is unchanged

`_open_agent_artifacts(selected_artifacts)` already accepts a list and dispatches to `view_agent_artifacts_in_tmux_pane`
for `len > 1`. Each artifact carries an absolute `path`, so the viewer doesn't need to know which agent an artifact came
from. No changes needed below the modal.

### Help / footer copy

Mirror the existing tagging convention ("Tag/untag agent (or marked set)"):

- `src/sase/ace/tui/modals/help_modal/bindings.py:351` — change description from `"Toggle artifacts pane"` to
  `"Toggle artifacts pane (or marked set)"`.
- The conditional footer entry in `src/sase/ace/tui/widgets/_keybinding_bindings.py:162` already shows `"artifacts"`
  only when the focused agent has artifacts. The bulk path should also surface a footer hint when marks exist — extend
  the marked-agents footer logic so `A` shows up as `"artifacts (marked)"` when `_marked_agents` is non-empty
  (regardless of whether the focused agent has its own artifacts). Exact wiring lives in the same widget; treat it as a
  small follow-on tweak alongside the action change.

## Touch list

Code:

- `src/sase/ace/tui/actions/agents/_panel_artifacts.py`
  - Rework `action_open_agent_artifacts` to add the marked-set branch.
  - Add a small `_collect_marked_agent_artifacts()` helper returning `(artifacts, agent_labels, marked_count)` so the
    modal call site stays small.
- `src/sase/ace/tui/modals/agent_artifacts_modal.py`
  - Constructor takes optional `agent_labels` and an optional `subtitle` / `agent_count` for the title.
  - `_artifact_option_text` (and `_create_options` / `_refresh_option`) accept and render the optional per-row agent
    prefix.
- `src/sase/ace/tui/modals/help_modal/bindings.py` — copy update.
- `src/sase/ace/tui/widgets/_keybinding_bindings.py` — surface `artifacts (marked)` in the footer when marks exist.

Tests (add alongside whatever tests already cover `_panel_artifacts.action_open_agent_artifacts` and the modal):

- Bulk path: two marked agents, each with two artifacts → modal shows four rows with agent-prefixed labels and
  `[4 from 2 agents]` in the title.
- Bulk path with stale marks: the surviving subset is used; pruning happens via the existing `_agents_with_children`
  filter.
- Bulk path with empty union: notify `"No artifacts found in marked agents"`.
- Bulk path with all-stale marks: notify `"No marked agents remain"`.
- No-marks path: existing single-agent behavior is byte-identical (no agent prefix in row labels, original title text).

## Out of scope

- No changes to the artifact data model, on-disk layout, or `list_agent_artifacts` / `agent_artifact_facade`.
- No changes to the artifact viewer (`view_agent_artifact[s]*`).
- No new keymap — this reuses `A` and the existing `m`-mark mechanism.
- No changes to `Agent.identity`, `_marked_agents` storage, or marking semantics.
- No grouping/header rows in the picker — flat list with prefixes only.
