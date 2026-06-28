---
create_time: 2026-06-28 15:41:42
status: done
prompt: sdd/prompts/202606/agent_neighbors_hoods.md
---
# Agent Neighbors and Hoods Terminology Plan

## Objective

Replace the Agents-tab "agent siblings" / dotted "agent family" namespace terminology with "agent neighbors" and "hoods"
throughout the live codebase and current documentation. The behavioral model should change from "same first dotted
segment" to "same immediate dotted namespace":

- `foo.bar` is in the `foo` hood.
- `foo.bar.baz` is in the `foo.bar` hood.
- `foo.bar` is a sub-hood of `foo`, regardless of whether an agent named `foo.bar` exists.
- Agents are neighbors when they are visible agents in the same exact hood.
- Dotless agent names have no named hood in this V1 and do not participate in hood-neighbor navigation.

This should make `foo.bar` and `foo.baz` neighbors, and make `foo.bar.baz` and `foo.bar.qux` neighbors, while avoiding
the old behavior where `foo`, `foo.bar`, and all deeper descendants were all considered one sibling family.

## Current Findings

The agent-specific sibling implementation is concentrated in:

- `src/sase/ace/tui/models/agent_siblings.py`
- `src/sase/ace/tui/actions/agents/_siblings.py`
- `src/sase/ace/tui/modals/agent_sibling_modal.py`
- `src/sase/ace/tui/widgets/agent_info_panel.py`
- `src/sase/ace/tui/widgets/_keybinding_bindings.py`
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py`
- `src/sase/ace/tui/styles.tcss`
- focused unit, modal, navigation, cache, footer, info-panel, and visual tests under `tests/`

Related dotted-name grouping code already models root and first-two-segment prefixes in
`src/sase/ace/tui/models/agent_groups/`. Its docstrings and tests still use "name root", "name prefix", and sometimes
"agent family" language. The new hood language should align with that grouping without adding per-keystroke rebuilds.

"Sibling" is heavily overloaded elsewhere. The implementation should not rename unrelated concepts:

- ChangeSpec siblings and query syntax such as `sibling:bar` / `~bar`.
- Linked-repository compatibility names such as `sibling_repos` and `SASE_SIBLING_*`.
- Project lifecycle state `sibling`.
- Generic code-organization comments that describe sibling modules.
- Historical `CHANGELOG.md` entries and archival SDD prompt/tale/epic records, unless the user explicitly wants history
  rewritten.
- Persisted plan-chain metadata fields such as `agent_family` and `agent_family_role`; those are durable artifact schema
  and describe plan-chain membership, not dotted-name hoods.

## Implementation Plan

1. Establish the hood model in one small helper module.
   - Replace the agent-specific sibling helper with an agent hood helper, likely by moving `agent_siblings.py` to
     `agent_hoods.py`.
   - Add helpers such as `agent_hood(agent) -> str | None` and, if useful for labels, `agent_subhood_parent(hood)`.
   - Use case-folded hood keys for matching, preserving the current case-insensitive behavior.
   - Reject empty or malformed dotted names with empty segments.
   - Keep the helper pure and data-only so it remains cheap to use from navigation and grouping tests.

2. Rename the agent-specific index and navigation code.
   - Rename `AgentSiblingRow` / `AgentSiblingIndex` to neighbor/hood equivalents, with methods like `neighbors_for()`
     and `neighbor_count()`.
   - Rename `AgentSiblingMixin` and `_siblings.py` to `_neighbors.py`, and update `AgentDisplayMixin` imports.
   - Rename cache/state members such as `_agent_sibling_index_cache` to `_agent_neighbor_index_cache`.
   - Keep the cached-index shape and invalidation triggers intact: agents object identity, panel keys, grouped panel
     mode, grouping mode, and fold-registry version.
   - Preserve the existing fast focus path: direct jump for one neighbor, modal for multiple neighbors, no full list
     rebuild on jump, immediate highlight refresh, debounced detail refresh.

3. Update the shared `~` command carefully.
   - `start_sibling_mode` is currently shared by ChangeSpec sibling navigation and Agents-tab agent sibling navigation.
   - Keep the existing keymap/config action name for compatibility unless a broader keymap migration is explicitly
     desired; it still accurately describes ChangeSpec behavior.
   - Inside the Agents-tab branch, delegate to `_start_agent_neighbor_navigation()`.
   - Update Agents-tab user-facing text to "neighbor" / "neighbors"; keep ChangeSpec help and query docs using
     "sibling".
   - If a new `start_neighbor_mode` alias is added later, update `src/sase/default_config.yml`, keymap types, command
     metadata, and compatibility tests in the same change.

4. Rename and relabel the chooser UI.
   - Rename `AgentSiblingModal` / `AgentSiblingChoice` and CSS ids/classes to neighbor names.
   - Change modal title from `Sibling Agents: <family>` to a hood label such as
     `Neighbor Agents: <hood> hood  [N neighbors]`.
   - Change info-panel badge from `siblings: N (~)` to `neighbors: N (~)`.
   - Change footer labels from `sibling` / `siblings (N)` to `neighbor` / `neighbors (N)`.
   - Change Agents help text to "Jump to neighbor agent".
   - Update visual snapshot names and goldens for the changed rendered text after inspecting actual/diff artifacts.

5. Align dotted-name grouping documentation with hoods.
   - Update `agent_groups` package docstrings and test names/comments where they describe dotted-name root/prefix
     groupings as "agent family" or namespace-like relationships.
   - Treat the existing first-segment grouping as a root hood grouping and first-two-segment grouping as sub-hood
     grouping in prose.
   - Avoid changing grouping behavior unless tests show the neighbor hood model and grouping tree disagree in a
     user-visible way.

6. Update current documentation and generated instruction docs.
   - Replace the top-level "Agent Family" glossary entry in `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and
     `OPENCODE.md` with "Agent Hood" / "Agent Neighbor" wording.
   - Update `memory/glossary.md` only with explicit approval, because project instructions mark memory files as
     protected.
   - Update live docs such as `docs/ace.md` anywhere the Agents-tab dotted namespace model is described.
   - Leave xprompt/Jinja "namespace" docs alone unless they specifically describe agent-name hoods; those are separate
     namespace mechanisms.
   - Leave historical SDD plans/prompts/tales and changelog entries unchanged by default so old records remain accurate.

7. Update tests.
   - Replace agent sibling test modules with neighbor/hood names.
   - Add behavior tests for:
     - `foo.bar` -> hood `foo`
     - `foo.bar.baz` -> hood `foo.bar`
     - `foo` -> no named hood
     - `foo.bar` and `foo.baz` are neighbors
     - `foo.bar.baz` and `foo.bar.qux` are neighbors
     - `foo`, `foo.bar`, and `foo.bar.baz` are not all neighbors
     - malformed dotted names do not produce hoods
     - case-insensitive hood matching
   - Preserve coverage for render-order neighbor lists, hidden collapsed rows, non-rendered STARTING rows, panel
     switching, artifact-viewer guards, jump-stack back navigation, info-panel caching, footer labels, and modal quick
     selection.

8. Add terminology guards before finishing.
   - Run targeted `rg` checks for stale agent-specific names:
     - `agent_sibling`
     - `AgentSibling`
     - `sibling agent`
     - `Sibling Agents`
     - `siblings:`
     - old agent-family glossary wording
   - Manually classify remaining `sibling` hits as ChangeSpec, linked-repo, project lifecycle, historical, or generic
     module-sibling usage.
   - Run targeted `rg` checks for accidental "hood" wording in unrelated xprompt/Jinja namespaces.

## Validation Plan

Because this change touches repo files, run the repo-mandated setup and validation:

```bash
just install
just check
```

Before the full check, run focused tests while iterating:

```bash
pytest tests/ace/tui/models/test_agent_neighbors.py \
  tests/ace/tui/test_agent_neighbor_navigation.py \
  tests/ace/tui/test_agent_neighbor_index_cache.py \
  tests/ace/tui/modals/test_agent_neighbor_modal.py \
  tests/test_keybinding_footer_agent.py \
  tests/ace/tui/widgets/test_agent_info_panel.py
```

Run the visual snapshot suite if rendered text or modal ids changed:

```bash
just test-visual
```

If visual failures are only the intended sibling-to-neighbor text changes, inspect the artifacts under the visual
failure cache and update PNG goldens with `--sase-update-visual-snapshots`.

## Risks and Mitigations

- Broad search-and-replace would break unrelated `sibling_repos`, ChangeSpec query syntax, project lifecycle state, and
  status-state-machine terminology. Mitigate by editing only agent-specific hits and classifying leftovers with `rg`.
- Renaming `start_sibling_mode` outright could break user keymap config while ChangeSpec navigation still uses sibling
  terminology. Mitigate by keeping the shared action name in this pass and changing Agents-tab labels/delegation.
- Hood semantics intentionally drop old root/descendant jumps. Mitigate with explicit tests proving parent agents and
  sub-hood descendants are not neighbors unless they share the same immediate hood.
- TUI performance could regress if the hood index rebuilds on every highlight. Mitigate by preserving the existing cache
  keys and selective refresh path, and by avoiding disk I/O or subprocess work in key handlers.
- Persisted `agent_family` artifact fields are durable. Mitigate by leaving schema fields intact and documenting them as
  plan-chain metadata rather than dotted hood terminology.
