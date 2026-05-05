---
create_time: 2026-05-05 13:06:04
status: wip
prompt: sdd/prompts/202605/artifacts_tui_panel.md
---
# Epic 4 Plan: Artifacts TUI Panel

## Context

Epic 4 builds the fast `A` artifacts panel described in `sdd/legends/202605/unified_artifacts.md`. In this checkout, the
unified artifact graph Python facade and CLI surfaces already exist:

- `src/sase/core/artifact_facade.py`
- `src/sase/core/artifact_wire/`
- `src/sase/main/parser_artifact.py`
- `src/sase/main/artifact_handler.py`
- `src/sase/xprompts/skills/sase_artifact.md`

This plan therefore treats Rust graph persistence and CLI wiring as prerequisites and scopes the work to Textual UI, TUI
action/keymap wiring, detail rendering, parity coverage, and performance verification.

Each phase below is intended to be handled by a distinct agent instance. Later phases should assume previous phases have
landed. Every implementation phase must run `just install` first in its workspace, and every phase that edits code must
finish with `just check`.

## Product Contract

Pressing `A` in ace opens a modal artifacts panel from the current tab context:

- AXE tab: artifact `/`
- CLs tab: current ChangeSpec `NAME`
- Agents tab: selected agent artifact ID, preferring agent name and falling back to the graph's documented legacy agent
  ID convention

The panel shows the current artifact, metadata, tree children from reverse `parent` links, typed inbound/outbound link
groups, and a kind-specific detail preview. Navigation should never rebuild or broadly scan the graph on normal `j/k`
movement. Expensive preview/export work must be lazy, cancellable, or debounced.

Old agent-specific surfaces are not removed in this epic. The existing Agent Run Log modal, file panel, and thinking
panel should remain available through existing code paths or through links from the artifacts panel until the new panel
has equivalent coverage.

## Phase 4.1: Modal Skeleton, Keymap, And Launch Contexts

Goal: make `A` open a functional artifacts modal from every tab, with loading and error states, but only minimal detail
rendering.

Primary files:

- `src/sase/default_config.yml`
- `src/sase/ace/tui/bindings.py`
- `src/sase/ace/tui/keymaps/types.py`
- `src/sase/ace/tui/commands/catalog.py`
- `src/sase/ace/tui/modals/help_modal/bindings.py`
- `src/sase/ace/tui/actions/`
- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/__init__.py`
- `src/sase/ace/tui/styles.tcss`
- tests replacing `tests/ace/tui/test_show_agent_run_log_keymap.py`

Implementation shape:

- Add `open_artifacts_panel` as the app-level action and default `A` binding.
- Replace the default/keymap metadata entry for `show_agent_run_log` with `open_artifacts_panel`.
- Keep `action_show_agent_run_log` and `AgentRunLogModal` code present for now, but stop advertising it as the `A`
  default.
- Add an action mixin/helper that resolves the starting artifact ID from the current tab.
- Add `ArtifactPanelModal` with:
  - async/threaded initial `artifact_show(default_index, artifact_id)` load
  - loading state
  - not-found/error state
  - basic title, node ID/kind/title, path-to-root, children count, link counts
  - `Esc`/`q` close and `j/k` list navigation
- Add TCSS for the modal layout using the existing modal style conventions.

Acceptance checks:

- Unit tests prove default config binds `A` to `open_artifacts_panel`.
- Unit tests prove CLs, Agents, and AXE launch contexts produce the expected starting IDs.
- A fake artifact facade can drive the modal without importing Rust.
- Existing keymap/catalog coverage tests pass.

## Phase 4.2: Navigation Model And Link Actions

Goal: make the modal useful for graph traversal while keeping query scope narrow and state easy for later renderers to
consume.

Primary files:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- optional helper module `src/sase/ace/tui/modals/artifact_panel_state.py`
- optional helper module `src/sase/ace/tui/modals/artifact_panel_render.py`
- tests under `tests/ace/tui/modals/`

Implementation shape:

- Introduce an explicit navigation state object:
  - current artifact ID
  - back stack
  - forward stack
  - selected row/group
  - current text filter
  - last loaded `ArtifactDetailWire`
- Render selectable rows for:
  - tree children from `detail.children`
  - outbound links grouped by `link_type`
  - inbound links grouped by `link_type`
  - path-to-root breadcrumbs
- Add actions:
  - open selected artifact/link target
  - back
  - forward
  - parent
  - root
  - search/filter
  - copy artifact ID
  - open file in editor for file artifacts
  - graph preview/export on demand
- Use only `artifact_show` for normal navigation. Use `artifact_graph` or `artifact_export` only when the graph
  preview/export action is invoked.
- Display a clear "truncated or too many rows" affordance if local row limits are needed before Rust exposes narrower
  child/link pagination.

Acceptance checks:

- Tests cover history back/forward semantics and no duplicate pushes when reopening the current node.
- Tests cover parent/root behavior from `path_to_root`.
- Tests cover grouping and selecting inbound vs outbound links.
- Tests cover filter updates without re-querying Rust.
- Tests verify graph export calls happen only from explicit export actions.

## Phase 4.3: Detail Renderers

Goal: provide kind-specific previews and metadata without changing the modal navigation contract.

Primary files:

- `src/sase/ace/tui/modals/artifact_panel_renderers.py`
- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- reusable imports from:
  - `src/sase/ace/tui/widgets/file_panel/_display.py`
  - `src/sase/ace/tui/graphics/`
  - `src/sase/ace/tui/util/lazy_syntax.py`
  - `src/sase/ace/tui/widgets/thinking_panel.py` where formatting concepts are reusable without coupling to `Agent`

Implementation shape:

- Add a renderer dispatch by `node.kind`.
- File artifacts:
  - path, size, mtime
  - syntax-highlighted text preview with line limits
  - supported image preview through the existing graphics layer
  - editor action
- Directory artifacts:
  - filesystem summary
  - child artifact summary
- Project, ChangeSpec, Commit artifacts:
  - parsed/source metadata from payloads and node metadata
  - linked agents, files, beads, and source location when present
- Bead artifacts:
  - status, parent/children/dependencies, worker link
- Agent artifacts:
  - status, model/provider/workspace
  - transcript, diff, plan, question, thought, retry/follow-up, ChangeSpec, and bead links
- Thought artifacts:
  - timeline-style compact card using source, timestamp/ordinal, title, and expandable/full text affordance

Acceptance checks:

- Renderer tests use constructed `ArtifactDetailWire` objects for each kind.
- File preview tests cover missing file, empty file, text file, diff-ish file, and supported image path fallback
  behavior.
- Renderer output handles absent payloads/metadata gracefully.

## Phase 4.4: Parity, Obsolete Panel Coverage, And UX Polish

Goal: ensure the new panel covers the old workflows well enough to be the default `A` destination while preserving
legacy surfaces.

Primary files:

- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_renderers.py`
- `src/sase/ace/tui/modals/agent_run_log_modal.py` only if a direct bridge is needed
- `src/sase/ace/tui/widgets/keybinding_footer.py`
- `src/sase/ace/tui/widgets/_keybinding_bindings.py`
- `src/sase/ace/tui/modals/help_modal/bindings.py`
- `src/sase/ace/tui/styles.tcss`

Implementation shape:

- Make ChangeSpec views clearly expose linked agents, commits, plans, questions, transcripts, diffs, and beads.
- Make Agent views clearly expose all created artifacts plus related ChangeSpecs and beads.
- Add discoverable modal footer hints for the modal's local keybindings.
- Add an in-panel action or link path to the legacy Agent Run Log when viewing a ChangeSpec, if the graph cannot yet
  show equivalent agent history.
- Keep agent file and thinking panels intact on the Agents tab.
- Update help/footer/command labels from "Agent run log" to "Artifacts" for the `A` binding.

Acceptance checks:

- Tests prove `A` no longer opens `AgentRunLogModal`.
- Tests prove the old run log can still be opened by the chosen compatibility route if that route is added.
- Pilot tests cover opening from CLs, Agents, and AXE and navigating at least one link.
- Visual layout tests or snapshot-style assertions cover small terminal dimensions well enough to catch obvious overlap.

## Phase 4.5: Performance Verification And Hardening

Goal: prove the modal is fast on large graphs and does not regress normal TUI navigation.

Primary files:

- `tests/ace/tui/modals/test_artifact_panel_modal.py`
- `tests/ace/tui/test_artifact_panel_launch.py`
- `tests/perf/` or `tests/ace/tui/bench_artifact_panel.py`
- any debounce/cancellation helpers under `src/sase/ace/tui/util/` if needed

Implementation shape:

- Add a large fake graph fixture that does not require Rust or user state.
- Add a smoke benchmark for opening from each tab:
  - AXE root
  - current ChangeSpec
  - current Agent
- Assert normal `j/k` row movement does not call `artifact_show`.
- Assert opening a selected row calls exactly one `artifact_show`.
- Assert graph preview/export is bounded and explicit.
- Add cancellation/debounce coverage for detail preview work where the renderer reads files or images.
- Run the focused TUI/modal tests plus `just check`.

Acceptance checks:

- Benchmark output documents open latency and query counts on the large fixture.
- Tests fail if row navigation accidentally rebuilds, scans, or exports the graph.
- No broad Rust graph calls occur during modal list cursor movement.

## Cross-Phase Guardrails

- Do not modify Rust core for this epic unless a phase discovers that the existing facade cannot satisfy the TUI
  contract. If that happens, stop and record the missing binding/query shape before crossing the Rust/Python boundary.
- Do not remove `AgentRunLogModal`, agent file panel, or thinking panel in Epic 4.
- Do not add runtime-specific provider branches for artifact behavior. Agent metadata should be treated uniformly across
  Claude, Gemini, Codex, and plugin providers.
- Prefer fake facade responses in modal tests so TUI tests remain fast and deterministic.
- Keep generated skill files out of scope unless a later epic explicitly asks for artifact-skill updates.

## Suggested Agent Order

1. Phase 4.1 first. It defines the action name, modal module, and launch contract everyone else builds on.
2. Phase 4.2 second. It stabilizes navigation state and row semantics.
3. Phase 4.3 third. It can work against the Phase 4.2 state/render contract.
4. Phase 4.4 fourth. It is mostly integration, help/footer polish, and parity.
5. Phase 4.5 last. It verifies the final shape and closes performance gaps.
