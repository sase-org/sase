# Rust `sase-tui` Agents Tab MVP Research

Date: 2026-05-14

## Question

What is the best way to create a new `sase-tui` repository that duplicates the
`sase ace` TUI, starting with a highly capable Rust MVP of the Agents tab?

## Related Prior Research

These existing notes in `sdd/research/` already cover adjacent surface and
should be read before treating this MVP as greenfield:

- `202605/rust_tui_plugin_migration.md` — broader Ratatui-vs-Textual analysis,
  pluggy survey, and plugin-discovery options. Establishes that pluggy usage
  in SASE is shallow (only `firstresult=True` plus name-keyed selection), so
  the plugin layer is not a blocker for a Rust MVP that skips launch.
- `202605/sase_chops_rust_repo_research.md` — sibling Rust repo pattern,
  including the maturin binary-wheel distribution channel for `pip install
  sase`. Same packaging story applies if `sase-tui` ever needs to ship inside
  the existing Python distribution.
- `202605/textual_image_rendering_research.md` — current Kitty graphics
  state in the Python TUI; explains why image preview should be deferred.
- `202605/rust_snapshot_migration_landing_research.md` — prior thinking on
  snapshot-test migration that informs the buffer-snapshot strategy below.
- `202605/tui_blocking_audit.md` and the async-loading commits (workflow
  detail, file-panel reads, agent content search) — context for why the
  Tier 1/Tier 2 loading shape is load-bearing.

## Executive Summary

Build the MVP as a Rust-native Ratatui app, but do not treat the current
Textual code as the domain boundary. The current Python Agents tab is a rich
presentation layer over several backend facts: project-file RUNNING claims,
agent artifact markers, workflow state markers, dismissed-agent indexes,
tags, retry state, and query/grouping/fold state. The new repo should reuse
and extend the existing Rust `sase-core` contracts for those facts rather than
re-port Python loaders line by line.

Recommended shape:

1. Create a new Rust workspace repo `sase-tui`.
2. Depend on `sase-core` as a pure Rust crate, not through the PyO3
   `sase_core_rs` binding.
3. Use Ratatui 0.30+ with Crossterm and Tokio.
4. Implement a small local app architecture: state store, event reducer,
   async task supervisor, component renderers, and command/effect queue.
5. Make the first screen the Agents tab only, not a tabbed clone with empty
   placeholder tabs.
6. For the MVP, support loading, refresh, grouping, side panels, folding,
   Vim-style navigation, search/query filters, detail preview, tagging,
   unread toggles, dismiss/kill actions, and artifact/run-log openers.
7. Keep launch/new-agent workflows out of the first MVP unless they can call
   existing shared launch APIs. Launch orchestration still touches Python
   provider/workspace/plugin behavior and is a bad first port.

The most important implementation decision is to create an internal
`AgentListSnapshot`/`AgentRow` model that is UI-neutral and testable. Some of
that model should probably move into `sase-core` once the first Rust TUI proves
which fields are stable enough to share with future web/mobile/editor
frontends.

## Current Local Architecture

The existing ACE TUI is a Textual app in `src/sase/ace/tui/app.py`.
`AceApp.compose()` creates three top-level views: ChangeSpecs, Agents, and AXE.
The Agents view has:

- `AgentInfoPanel` across the top.
- `AgentList` on the left.
- `AgentDetail` on the right, with prompt, file, and tools subpanels.

The Agents tab is not a single widget. Its behavior is spread across many
mixins in `src/sase/ace/tui/actions/agents/`, with the public aggregate in
`_core.py`. The important groups are:

- Loading and refresh:
  - `_loading_disk.py`
  - `_loading_refresh.py`
  - `_loading_helpers.py`
  - `_loading_compute.py`
  - `_loading_finalize.py`
- Display and detail:
  - `_display.py`
  - `_display_panels.py`
  - `_display_detail.py`
  - `_panel_artifacts.py`
  - `_panel_tmux.py`
- Navigation:
  - `_navigation_order.py`
  - `_selection.py`
  - `_folding.py`
  - `_panels.py`
- User actions:
  - `_dismissing.py`
  - `_killing.py`
  - `_tagging.py`
  - `_unread.py`
  - `_revive.py`
  - `_wait_resume.py`
  - `_notification_*`

The current `Agent` model lives in `src/sase/ace/tui/models/agent.py`. It is a
large display/runtime model with fields for status, workspace, workflow step
metadata, artifacts, prompt/error paths, provider/model names, tags, retry
lineage, attempt history, pending plan/question state, and dismissed-bundle
metadata. A Rust port should not copy that dataclass mechanically. It should
split it into:

- A persisted/backend record projection.
- A UI-neutral row summary.
- Local presentation state such as focus, folds, panels, scroll offsets, and
  detail mode.

### Data Sources

`src/sase/ace/tui/models/agent_loader.py` shows the current source mix:

1. Project-file RUNNING field workspace claims.
2. `done.json` marker files.
3. home-mode `running.json` marker files.
4. `workflow_state.json` and prompt-step marker files.
5. ChangeSpec HOOKS/MENTORS/COMMENTS suffixes.
6. Dismissed-agent identities and dismissed bundles.
7. Tags, retry state, and attempt history.

Recent work already moved the expensive artifact walk to Rust. The Python
loader calls `sase.core.agent_scan_facade.scan_agent_artifacts()` and, when
available, `query_agent_artifact_index()` against
`~/.sase/agent_artifact_index.sqlite`. The wire contract is in
`src/sase/core/agent_scan_wire.py` and mirrored in
`../sase-core/crates/sase_core/src/agent_scan/wire.rs`.

That is the best starting point for `sase-tui`. The new Rust TUI can depend on
`sase_core::agent_scan::{scan_agent_artifacts, query_agent_artifact_index}` and
avoid the Python binding layer entirely.

### Current Performance Pattern To Preserve

The current loader has a Tier 1/Tier 2 shape:

- Tier 1: use persistent artifact index when present, otherwise a bounded
  newest-first source scan.
- Tier 2: reconcile from source-of-truth artifact files in the background.

This was introduced to keep first paint independent of years of agent history.
The Rust TUI should keep the same product contract:

- First render should show active/incomplete rows and recent completed rows.
- Full history should reconcile asynchronously.
- Missing/stale index should degrade to bounded source scan, not block startup.

## Existing Rust Core Surface

`../sase-core` is already a Rust workspace with:

- `crates/sase_core`: pure Rust domain/backend crate.
- `crates/sase_core_py`: PyO3 binding crate exposing `sase_core_rs`.
- `crates/sase_gateway`: gateway/server work.
- `crates/sase_xprompt_lsp`: editor/LSP work.

Relevant existing Rust modules:

- `agent_scan/scanner.rs`
- `agent_scan/index.rs`
- `agent_scan/wire.rs`
- `agent_cleanup/*`
- `agent_archive/*`
- `notifications/*`
- `query/*`
- `project_spec.rs`
- `status/*`

The `agent_scan/index.rs` module already stores a SQLite materialized view of
artifact summaries, using `rusqlite` with WAL mode and the canonical scanner
record JSON as payload. That is exactly the kind of stable backend primitive a
new frontend should use.

### Boundary Recommendation

Follow the existing memory rule: shared backend/domain behavior belongs in
`../sase-core`, while frontend rendering and key handling belong in the TUI.

For `sase-tui`, this means:

- In `sase-core`:
  - artifact scan/index;
  - project spec/RUNNING parsing;
  - dismissed/tag/index read/write helpers when they are shared;
  - query parsing/evaluation if a web/mobile/client would need identical
    results;
  - cleanup/dismiss/kill side-effect planners.
- In `sase-tui`:
  - keymaps;
  - view state;
  - panel focus and scroll state;
  - rendering;
  - Ratatui widgets;
  - local command palette/modals;
  - async task orchestration.

The MVP can begin with a local adapter from `AgentArtifactRecordWire` to
`AgentRow`, but the adapter should be designed as pure data code with no
Ratatui imports so it can be promoted into `sase-core` if it becomes shared.

## External Findings

Ratatui is the right default for a Rust-native SASE TUI. The current 0.30 line
modularized the crate into core/widgets/backend crates, added the `run()` API,
and is explicitly positioning `ratatui-core` as a more stable base for third
party widgets. Source:
https://ratatui.rs/highlights/v030/

Ratatui is intentionally immediate-mode. The user owns the event loop,
application state, and redraw decisions. Its FAQ notes that Ratatui itself is
not inherently async; async becomes useful for app-owned work such as event
streams and background tasks. SASE has substantial background work, so Tokio is
appropriate. Source:
https://ratatui.rs/faq/

Ratatui's official async tutorial uses Tokio, Crossterm event streams,
`tokio-util`, and futures for an event-driven async app. Source:
https://ratatui.rs/tutorials/counter-async-app/

Ratatui's official component-architecture page describes a trait-based
component pattern where components draw themselves and handle keyboard/mouse
events. That pattern maps well to SASE's panels, but SASE should keep domain
state above components rather than giving each component independent ownership
of backend data. Source:
https://ratatui.rs/concepts/application-patterns/component-architecture/

Ratatui's testing recipe recommends `TestBackend` plus `insta` snapshots. This
is a direct replacement for a large part of Textual `Pilot` snapshot coverage.
Source:
https://ratatui.rs/recipes/testing/snapshots/

Ratatui 0.30's `ratatui::init()` installs a panic hook that restores raw mode
and the alternate screen before panicking. The MVP should use this or an
equivalent `color-eyre` setup from day one. Sources:
https://docs.rs/ratatui/latest/ratatui/fn.init.html
https://ratatui.rs/recipes/apps/color-eyre/

The widget ecosystem is good enough for the Agents tab:

- Built-in: `Block`, `List`, `Paragraph`, `Tabs`, `Table`, `Scrollbar`.
- Third-party: `ratatui-textarea`, `tui-tree-widget`, `tui-scrollview`,
  `tui-widget-list`, `tui-logger`, `ratatui-image`.

Source:
https://ratatui.rs/showcase/widgets/
https://ratatui.rs/showcase/third-party-widgets/

`ratatui-image` supports multiple terminal graphics protocols, including
Sixel, Kitty, and iTerm2, but its compatibility matrix is terminal-specific.
For the Agents MVP, use text/file/detail panes first and treat rich image
preview as a later capability. Source:
https://docs.rs/crate/ratatui-image/8.1.1

Zellij is the most relevant precedent for long-term plugin thinking: it uses
WebAssembly/WASI plugins and builds parts of its UI from plugins. That is
useful background for future SASE extension points, but it is too much surface
for the Agents-tab MVP. Source:
https://zellij.dev/documentation/plugins.html

## Framework Decision

Use Ratatui directly rather than `tui-realm` for the first MVP.

`tui-realm` is credible and adds a retained/component-style layer, but SASE's
existing UI complexity is not mainly "we need components." The hard parts are:

- stable data contracts;
- async refresh and file changes;
- tree/list navigation;
- detail-pane workers;
- keymaps and modal focus;
- parity with existing SASE semantics.

Ratatui direct keeps the dependency stack smaller and makes tests simpler:
render from `AppState` to a `Buffer`, drive `update()` with synthetic events,
and assert snapshots. If a framework layer becomes useful after one real
Agents-tab slice exists, evaluate it against that slice, not against a toy app.

## Proposed `sase-tui` Repo Layout

```text
sase-tui/
  Cargo.toml
  crates/
    sase_tui/
      Cargo.toml
      src/
        main.rs
        app.rs
        cli.rs
        config.rs
        events.rs
        keymap.rs
        terminal.rs
        task.rs
        agents/
          mod.rs
          action.rs
          adapter.rs
          detail.rs
          grouping.rs
          model.rs
          query.rs
          render.rs
          snapshot.rs
          state.rs
          update.rs
          widgets.rs
    sase_tui_test/
      Cargo.toml
      src/
        fixtures.rs
        harness.rs
```

Keep one binary crate until there is a proven need for a separate library
crate. The code can still be modular. If the adapter/query/grouping logic
starts being useful outside the TUI, move it to `sase-core`.

Suggested dependencies:

- `sase_core` via path/git dependency.
- `ratatui = "0.30"` with Crossterm backend features.
- `crossterm`.
- `tokio` with `rt-multi-thread`, `sync`, `time`, `signal`, and FS-related
  needs.
- `color-eyre`.
- `serde`, `serde_json`, `toml` or YAML config parser as needed.
- `chrono` or `time` for timestamps; match `sase-core` where possible.
- `notify` for filesystem events after the polling MVP works.
- `arboard` or platform clipboard crate only when copy actions are ported.
- `insta` and `rstest` for tests.

## App Architecture

Use a TEA-like reducer plus explicit effects:

```text
Terminal/Input/Timer/File events
        |
        v
   AppEvent enum
        |
        v
update(&mut AppState, AppEvent) -> Vec<Effect>
        |
        +--> render(&AppState, Frame)
        |
        +--> TaskSupervisor executes effects and sends AppEvent results back
```

Core state:

```text
AppState
  current_screen: Agents
  agents: AgentsState
  status_line/toasts/modal state
  terminal size
  config/keymap state

AgentsState
  snapshot: AgentListSnapshot
  load_state: Loading | Tier1 | Full | Error
  focus: FocusTarget
  selected_row_id
  panel_focus
  grouping_mode
  fold_registry
  query
  detail_mode
  marks
  unread overrides
  pending_commands
```

Background tasks:

- Load Tier 1 snapshot.
- Rebuild/query artifact index.
- Reconcile Tier 2 snapshot.
- Watch artifact/project/dismissed/tag files.
- Load selected-agent prompt/detail files.
- Execute kill/dismiss/tag/unread side effects.
- Open external viewer/editor/tmux commands.

Renderers should be pure-ish functions from state to Ratatui widgets:

- `render_agents_screen()`
- `render_agent_info()`
- `render_agent_panels()`
- `render_agent_list()`
- `render_agent_detail()`
- `render_footer()`
- `render_modal()`

The renderer should not read the filesystem.

## MVP Feature Scope

### Must Have

The first MVP should be useful as a daily Agents tab replacement:

- Start directly on Agents view.
- Load active/incomplete agents and recent completed agents quickly.
- Background full-history reconcile.
- Manual refresh.
- Periodic refresh.
- Count strip: starting/running/waiting/failed/unread/read/total.
- Tag side panels:
  - untagged panel;
  - one panel per tag;
  - `J`/`K` panel focus cycling.
- Grouping modes:
  - by project/ChangeSpec/name root;
  - by date;
  - by status;
  - `o`/`O` cycle.
- Fold groups with `h`/`l`, `H`/`L` where practical.
- Render workflow parent/child rows.
- Preserve selected identity across refreshes.
- Vim navigation `j`/`k`, top/bottom `g`/`G`, page/scroll keys.
- Query filter with at least the existing core keys:
  `status`, `cl`, `project`, `name`, `model`, `provider`, `tag`, `type`,
  `source`, `needs`, `hidden`, `attention`, `age`.
- Detail pane:
  - header/status/timing/provider/model;
  - raw prompt;
  - error/traceback for failures;
  - response/diff/file list when paths exist;
  - output path and artifact dir;
  - basic scrolling.
- Tag edit action.
- Toggle manual unread.
- Dismiss completed/failed row.
- Kill active row with confirmation.
- Open artifact directory or selected file in `$EDITOR`/system opener.
- Help modal for implemented bindings.

### Should Have Soon After

- Revive dismissed agents.
- Run-log modal.
- Attempt-history display.
- Notification/HITL integration.
- Detail tools pane.
- Image/PDF artifact preview.
- Entry jump hints.
- Clipboard/copy mode.
- Agent cleanup panel.

### Defer

- Launching new agents from the TUI.
- Plan approval/question response flows.
- AXE tab.
- ChangeSpecs tab.
- Full command palette.
- Plugin architecture.
- Rich terminal image rendering.

### Explicit Non-Goals for the MVP

These are not just "later"; they should be actively refused if scope-creep
appears during the first slice:

- **Pixel parity with Textual.** Ratatui will render differently. The
  parity bar is semantic (data, ordering, action effects), not visual.
- **Embedding Python.** No PyO3, no subprocess shell-outs to `python -m
  sase`. The MVP either talks to `sase-core` or it does not have the
  feature.
- **Cross-process IPC with the Python TUI.** Two TUIs sharing live state
  is not the goal; sharing on-disk artifacts/index is.
- **Custom widget framework.** Build the Agents tab against Ratatui +
  small reducer; do not invent a SASE-flavored widget system before the
  first screen is real.
- **Multi-pane tmux orchestration from Rust.** Continue to shell out to
  the existing tmux helpers for now.
- **Theming/CSS engine.** A small typed theme struct is enough; no
  user-loadable CSS-like system.

Launch is deliberately deferred because current launch behavior still depends
on Python provider/workspace/plugin machinery. Porting it first would force the
new repo to either embed Python or duplicate unstable orchestration. A strong
Agents MVP can be read/control oriented while launch APIs continue maturing in
`sase-core`.

## Data Model Recommendation

Create a narrow `AgentRow` for the TUI:

```rust
struct AgentRow {
    id: AgentId,
    kind: AgentKind,
    status: AgentStatus,
    project_name: Option<String>,
    project_file: Option<PathBuf>,
    cl_name: Option<String>,
    display_name: String,
    agent_name: Option<String>,
    raw_suffix: Option<String>,
    parent_id: Option<AgentId>,
    workflow: Option<String>,
    step: Option<WorkflowStepSummary>,
    started_at: Option<DateTime>,
    stopped_at: Option<DateTime>,
    workspace_num: Option<i64>,
    workspace_dir: Option<PathBuf>,
    pid: Option<i64>,
    model: Option<String>,
    llm_provider: Option<String>,
    vcs_provider: Option<String>,
    tag: Option<String>,
    hidden: bool,
    approve: bool,
    retry: RetrySummary,
    artifacts_dir: Option<PathBuf>,
    prompt_path: Option<PathBuf>,
    response_path: Option<PathBuf>,
    diff_path: Option<PathBuf>,
    output_path: Option<PathBuf>,
    extra_files: Vec<PathBuf>,
    error: Option<String>,
    traceback: Option<String>,
}
```

Then make separate presentation records:

```rust
enum RenderRow {
    Banner(GroupBanner),
    Agent(AgentId),
}

struct AgentPanel {
    key: Option<String>,
    rows: Vec<RenderRow>,
}
```

This separation matters. It lets the app preserve focus by stable identity,
test grouping separately from rendering, and avoid using list indices as
long-lived identity.

## Query and Grouping

The existing Python agent query language is pure and already frontend-adjacent.
It lives under `src/sase/ace/agent_query/`. For MVP speed, `sase-tui` can
implement the same parser/evaluator locally, but the better long-term home is
`sase-core` because a web/mobile Agents view would need identical filtering.

Recommendation:

1. Port agent query AST/parser/evaluator into `sase-core`.
2. Expose it as pure Rust API first.
3. Use the same API from `sase-tui`.
4. Later replace the Python evaluator with `sase_core_rs` if useful.

Grouping logic has the same shape. Current behavior in
`src/sase/ace/tui/models/agent_groups/` is deterministic and testable. Port it
as pure Rust functions over `AgentRow`, not as widget logic.

## Refresh and File Watching

Start with polling plus coalescing:

- Initial Tier 1 load on startup.
- Manual refresh effect.
- Periodic refresh every configured interval.
- Last-request-wins refresh guard.
- Do not apply refresh results while a navigation burst is in progress if it
  causes visible j/k stalls.

Then add `notify`-based watching:

- project spec files;
- artifact marker directories;
- dismissed identities/bundles;
- tag state;
- artifact index file.

The watcher should emit "dirty" events into the same coalesced refresh path.
It should not mutate app state directly.

## Side Effects

Treat side effects as planned commands, not inline UI code:

```text
Action::KillSelected
  -> Effect::Confirm(...)
  -> Effect::KillAgent(AgentId)
  -> AppEvent::CommandFinished(...)
  -> refresh
```

For MVP side effects:

- Dismiss should update dismissed identity state and delete/hide loader files
  through shared cleanup helpers.
- Kill should use existing core cleanup/process helpers if available; if not,
  implement the minimal process-kill path behind an interface so it can move to
  `sase-core`.
- Tag/unread state can be file-backed initially, matching current SASE files,
  but should use atomic writes.

Every side effect should schedule a refresh through the same path as file
events. The Textual code already relies on explicit `request_agents_refresh()`
because there is no guaranteed immediate filesystem watcher.

## Testing Strategy

Use three layers.

### Pure State Tests

Test without Ratatui:

- scan/index record -> `AgentRow` conversion;
- dedupe/status override behavior;
- grouping tree output;
- query parsing/evaluation;
- focus preservation across refresh;
- fold registry behavior;
- side-effect planning.

These should run fast and should use small fixture artifact trees.

### Ratatui Buffer Snapshots

Use `ratatui::backend::TestBackend` and `insta` snapshots for:

- empty Agents tab;
- active/running/waiting/failed mix;
- tag panels;
- grouping modes;
- folded groups;
- selected failed agent detail;
- narrow terminal truncation;
- modal/confirmation rendering.

Snapshot the terminal buffer, not PNG, for the MVP. Add screenshot tooling only
after the rendering contract stabilizes.

### Parity Tests Against Current ACE

Before claiming replacement quality, build a parity harness that runs the
Python loader or existing ACE test fixtures and compares:

- row count;
- status counts;
- display names;
- stable identities;
- grouping bucket labels;
- selected-row restoration;
- query results for a corpus.

Do not require pixel parity with Textual. Ratatui will render differently.
Require semantic parity for data, ordering, and key actions.

## Packaging and Development

For the first repo:

- Standard Cargo workspace.
- `cargo run -- agents` or just `cargo run`.
- Later: `cargo install --git https://github.com/sase-org/sase-tui`.
- Later: release binaries with `cargo-dist` or a GitHub Actions matrix.
- Later: optional Python-side wrapper in `sase` that finds `sase-tui` on PATH.

Do not package the MVP as a Python wheel unless there is an immediate install
requirement. This repo can be pure Rust. If SASE later wants `pip install sase`
to install the TUI binary, use the same maturin binary-wheel pattern already
considered for Rust chop binaries (see
`202605/sase_chops_rust_repo_research.md` for the full pattern).

### `sase-core` Dependency Source

The new repo needs a concrete answer for *how* it depends on `sase-core`.
Pick one explicitly at repo-init time:

1. **Path dependency** during initial development (`sase-core = { path =
   "../sase-core/crates/sase_core" }`). Fastest iteration but forces every
   sase-tui contributor to have both repos checked out side by side.
2. **Git dependency** with a pinned commit
   (`sase-core = { git = "...", rev = "..." }`). No side-by-side checkout
   required; bumping the pin is a deliberate PR. Recommended default once
   the API stabilizes.
3. **Published crate** on crates.io. Not yet — `sase-core` is not
   currently published, and the API churn rate is too high for releases.

Recommend starting with path deps in a `Cargo.toml` `[patch.crates-io]`
override so the same source can be consumed via git in CI. This mirrors
how `sase-core_py` is wired today.

## Risks

### Risk: Recreating Python Loader Drift

If `sase-tui` hand-rolls every loader rule, it will drift immediately from
`sase ace`.

Mitigation: consume `sase-core` scan/index wires, port pure grouping/query
logic with parity tests, and move stable shared adapters into `sase-core`.

### Risk: Ratatui App Framework Sprawl

Textual currently provides retained widgets, CSS, workers, bindings, and
screens. Ratatui does not.

Mitigation: keep a small explicit architecture with reducer/effects/components.
Avoid inventing a generic UI framework before the Agents screen has real needs.

### Risk: Startup Still Walks Too Much History

A naive Rust port may feel fast in development but regress for users with
years of artifacts.

Mitigation: preserve Tier 1/Tier 2 loading and persistent artifact index use.
Test with a synthetic large artifact corpus.

### Risk: Terminal State Breakage on Panic

Raw-mode terminal apps can leave the terminal broken after panic.

Mitigation: use `ratatui::init()`/restore or the official color-eyre setup from
day one and add an integration test/smoke path for clean restore.

### Risk: Launch Scope Pulls in Python Plugins

Agent launch touches provider/workspace/VCS plugin machinery that is not yet a
pure Rust boundary.

Mitigation: defer launch from MVP. Make read/control excellent first.

## Open Questions

- Should `AgentRow` conversion live in `sase-tui` initially or be added to
  `sase-core` before the new repo starts?
- Should query/grouping be ported to `sase-core` first, or copied locally and
  promoted after parity tests?
- How much kill/dismiss functionality already exists in `sase-core` versus
  still depending on Python helpers?
- Should the first UI preserve exact default keymaps from
  `src/sase/default_config.yml`, or should it use a smaller keymap with a
  compatibility mode?
- Does the MVP need dismissed archive/revive on day one, or can it ship after
  visible active/completed rows are solid?

## Recommended First Implementation Plan

0. Create an SDD epic for the new repo (e.g. `sase-tui-agents-mvp`) and a
   bead tree mirroring the steps below, so the work threads back into
   the existing SASE planning system. Land an empty `sase-tui` repo with
   `Cargo.toml`, `rustfmt.toml`, `.editorconfig`, GitHub Actions skeleton,
   and `CODEOWNERS` before any feature work.
1. Create `sase-tui` Rust workspace and wire terminal init, event loop, panic
   restore, logging, and a static Agents screen.
2. Add `sase-core` dependency and load `AgentArtifactScanWire` from the
   artifact index with fallback to bounded scan.
3. Implement `AgentRow` adapter for done/running/waiting/workflow records.
4. Render info strip, panels, list rows, selection, and detail header/prompt.
5. Port grouping/fold logic and add snapshot tests.
6. Port query parser/evaluator or move it to `sase-core`, then wire `/`.
7. Add background refresh and full-history reconcile.
8. Add tag/unread/dismiss/kill actions behind confirmation and refresh.
9. Add parity tests against representative Python ACE fixtures.
10. Only then evaluate launch/revive/notifications.

## Additional Gap Research (2026-05)

### Prior-Art Rust TUIs

- **gitui**: pure-Crossterm DIY, no Tokio. Threads + `std::sync::mpsc` and a
  synchronous repaint queue. Lesson: a `Component` trait with
  `event() -> EventState::{Consumed,NotConsumed}` lets bubbling stay explicit;
  copy that for SASE modals/panels.
  https://github.com/extrawurst/gitui
- **atuin**: Crossterm + Tokio. `EventStream` polled in `tokio::select!` against
  a tick interval and a search-debounce future. Lesson: debounce the
  *user-input-derived* refresh future, not the file-watcher future — they have
  different latency budgets.
  https://github.com/atuinsh/atuin/tree/main/crates/atuin/src/command/client/search
- **helix (helix-term)**: a `Compositor` owns `Vec<Box<dyn Component>>` layers
  and a single `run` loop drives an `EventStream` plus LSP/DAP futures via
  `tokio::select!`. Lesson: model "modal layers" (help, confirm, query) as
  pushed Components rather than enum-state inside the main view.
  https://github.com/helix-editor/helix/blob/master/docs/architecture.md
  https://github.com/helix-editor/helix/blob/master/helix-term/src/compositor.rs
- **yazi**: 20+ crate workspace, `LocalSet` per thread, task-priority queue
  with explicit cancellation. Lesson: split *render-blocking* vs *streaming*
  tasks — sase-tui should mark artifact scan as streaming so the first paint
  never waits on Tier 2.
  https://deepwiki.com/sxyazi/yazi
- **oha**: Ratatui + Tokio + Hyper. Has a clean separation between a "stats
  collector" task that owns the data and a render task. Lesson: prefer a
  single Arc<Mutex<Snapshot>> updated by the collector and read by render,
  rather than channelling every row delta.
  https://github.com/hatoo/oha
- **bottom**: Crossterm DIY, full `insta`-based snapshot suite over `Buffer`.
  Lesson: golden-buffer snapshots scale; PNG is overkill until visual parity
  with Textual is a product requirement.
  https://github.com/ClementTsang/bottom

### Ratatui Alternatives — Honest Take

- **iocraft**: React-like declarative API with hooks and flexbox via taffy.
  Genuinely nicer for forms/dialogs but immature ecosystem, no `insta` story,
  and no comparable widget breadth. Not a better fit for sase-tui — list,
  detail pane, and grouping are exactly what Ratatui's immediate-mode list
  widget is best at.
  https://github.com/ccbrown/iocraft
- **cursive**: retained-mode, callback-driven, handles its own event loop.
  Awkward for an async/Tokio app and lacks fine-grained redraw control.
  Reject.
- **dioxus TUI (Rink)**: Dioxus's `dioxus-tui` (formerly Rink) is alpha and now
  builds on top of Ratatui internally; you would inherit Ratatui's behavior
  plus a VDOM layer SASE does not need.
  https://github.com/DioxusLabs/dioxus/issues/1311
- **crossterm-only DIY**: viable (gitui, bottom) but you re-implement layout,
  text wrapping, and styled spans. Not worth it given Ratatui's widget set.

Verdict: stay on Ratatui 0.30.

### Async/Tokio Canonical Pattern (late 2025 / 2026)

The current Ratatui-recommended shape, matching the `async-template` and the
`counter-async-app` tutorial:

1. `crossterm::event::EventStream::new()` (requires `event-stream` feature).
2. A `Tui` (or `EventHandler`) struct holding a `tokio_util::sync::CancellationToken`,
   a `JoinHandle`, and an `mpsc::UnboundedReceiver<Event>`.
3. Inside the spawned task: `tokio::select!` over `crossterm_stream.next()`,
   `tick_interval.tick()`, `render_interval.tick()`, and
   `cancel_token.cancelled()`.
4. On shutdown: `cancel_token.cancel()` then `handle.await`.

Render-storm avoidance: do NOT render on every `AppEvent`. The accepted
pattern is a separate `render_interval` (e.g. 30 Hz) plus a dirty flag set by
the reducer; the render tick only draws when dirty. For file-watch fanout,
use `notify-debouncer-full` (250–500 ms window) which collapses duplicate
paths from the typical 3–12 events Vim/VSCode emit per save.

Sources:
- https://ratatui.rs/tutorials/counter-async-app/async-event-stream/
- https://ratatui.rs/tutorials/counter-async-app/full-async-events/
- https://ratatui.github.io/async-template/02-structure.html
- https://docs.rs/notify-debouncer-full

### Terminal Compatibility

- **Ratatui 0.30** modularized into `ratatui-core`/`ratatui-widgets`/backends
  and now allows multiple Crossterm majors via `crossterm_{version}` features,
  so sase-tui can pin to whatever Crossterm matches its kitty-protocol
  requirements. https://ratatui.rs/highlights/v030/
- **Kitty keyboard protocol**: Crossterm's `PushKeyboardEnhancementFlags` is
  the supported path (disambiguate Ctrl+letter, modifiers on release,
  Esc/Tab disambiguation). Required for Vim-style chord keymaps to feel
  correct in Kitty/WezTerm/foot.
  https://sw.kovidgoyal.net/kitty/keyboard-protocol/
- **Bracketed paste, focus events, mouse**: Crossterm's
  `EnableBracketedPaste`/`EnableFocusChange`/`EnableMouseCapture` are
  separately opt-in; emit them from `terminal.rs` init and undo on restore.
  Without bracketed paste, multi-line clipboard pastes get interleaved with
  keymap handling — there is an active class of bugs (see e.g. Kiro #6634)
  caused by missing this.
- **Grapheme/wide-char**: Ratatui uses `unicode-width`; emoji/CJK width works
  but flag sequences and ZWJ clusters still mis-measure. Truncate display
  names with `unicode-segmentation`, not `str::chars().take(n)`.
- **tmux passthrough**: `set -g allow-passthrough on` (tmux 3.2+) is required
  for any DCS-wrapped Kitty graphics; tmux master has experimental native
  Kitty graphics support on the `ta/kitty-img` branch but is not in
  released tmux 3.6a. Plan for: Kitty image preview works direct; inside
  tmux requires passthrough; inside screen, give up gracefully and fall
  back to halfblocks. https://github.com/tmux/tmux/issues/4902

### Logging / Observability

Consensus: `tracing` + `tracing-subscriber` + `tracing-appender` writing to a
rolling file under the data dir (e.g. `~/.local/state/sase-tui/`). Never
write logs to stdout — Ratatui owns the alternate screen. Add `tui-logger`
(v0.10+ is Ratatui-only) only if you want an in-app log panel, since its
internal hot/main double-buffer is overkill for just a file sink.
- https://ratatui.rs/recipes/apps/log-with-tracing/
- https://github.com/gin66/tui-logger

### Error Handling

Consensus pattern, codified by the Ratatui `color-eyre` recipe:
- `color-eyre` in `main()` for the panic + error hook (installs the
  terminal-restore hook around the panic handler).
- `eyre::Result<T>` everywhere in TUI code.
- `thiserror` only inside `sase-core` for shared library error enums that
  callers (web/mobile/CLI) might `match` on.
- Do not use `anyhow` and `eyre` in the same workspace; `color-eyre`
  subsumes `anyhow`'s ergonomics.

Sources:
- https://ratatui.rs/recipes/apps/color-eyre/
- https://github.com/eyre-rs/eyre

### Config Sharing With Python

Three options:

1. **Duplicate** `default_config.yml` keymaps as a Rust `serde` parse.
   Fast, drifts.
2. **Generate** a typed Rust config crate from the same YAML via a
   `build.rs` that reads the Python repo's `default_config.yml`.
   Avoids drift but couples build environments.
3. **Move config parsing into `sase-core`** as a `sase_core::config`
   module reading the same on-disk YAML. Python keeps its current loader
   for behaviors `sase-core` does not own; `sase-tui` calls
   `sase_core::config::load()`.

Recommendation: option 3 for keymap, theme, and any value that affects
both frontends; option 1 short-term for TUI-only widget state. This
matches the existing rule that web/editor frontends should match TUI
behavior. The default_config.yml itself can stay in the sase Python repo
and be referenced by path (or vendored into sase-core as a build asset).

### Distribution

Current 2026 consensus for a Rust TUI you want users to actually install:

- **cargo-dist** (axodotdev) for release pipelines: generates GitHub
  Releases with platform tarballs, MSI/PKG, shell + PowerShell installers,
  and Homebrew tap formulas from one Cargo.toml config.
  https://github.com/axodotdev/cargo-dist
- **cargo-binstall** for `cargo install`-style UX backed by the
  cargo-dist artifacts. https://github.com/cargo-bins/cargo-binstall
- **Homebrew**: prefer a bottle from a tap that `cargo-dist` populates
  rather than a `head`-from-source formula.
- **GitHub artifact attestations** (`actions/attest-build-provenance`) are
  now the de-facto standard for supply-chain provenance on releases.

`pip install sase-tui` is not the right channel; ship the binary
independently and let the Python sase package optionally find it on PATH.

### Performance Benchmarking

Ratatui itself uses Criterion in-tree for its widget benchmarks. For
application-level benchmarks (full-screen render of a 1000-row Agent list,
scroll-through throughput), `divan` is increasingly the choice because
its black-box API and per-iteration setup fit "build state, render once"
better than Criterion's looped sampling. CodSpeed supports both for CI.

Practical baseline: render of a full-screen `List`/`Paragraph` is well
under 1 ms on modern hardware (ratatui discussion #1880); the realistic
budget for sase-tui is 16 ms total per frame at 60 Hz, of which Ratatui
draw should stay under 2 ms. Benchmark the row-build path
(`AgentRow -> Vec<ListItem>`) separately — that is where 1000+ row lists
typically regress.

Sources:
- https://github.com/ratatui/ratatui/discussions/1880
- https://github.com/nvzqz/divan
- https://codspeed.io/docs/guides/how-to-benchmark-rust-with-divan

### Image / PDF Preview

`ratatui-image` (8.x) supports Kitty, Sixel, iTerm2, and a Unicode
halfblocks fallback, with auto-detection by env vars + control-sequence
query. Kitty requires terminal Kitty ≥ 0.28; Sixel works in foot,
WezTerm, xterm-with-sixel, mlterm; iTerm2 protocol works in iTerm2 and
WezTerm. Inside tmux, all of these require `allow-passthrough on` and
even then placement is fragile.

Alternatives:
- **Spawn `chafa`**: high-quality fallback, works anywhere, returns ANSI
  to draw inline. Easy to integrate but does not coexist with Ratatui's
  alternate-screen redraws cleanly — best for a leave-altscreen preview
  mode. https://github.com/hpjansson/chafa
- **Spawn `viu`**: native Kitty/iTerm2 support, simpler than chafa.
  https://github.com/atanunq/viu
- **Überzug++**: external image-overlay daemon; best quality, worst
  packaging.

PDF preview specifically has no good Rust crate; the realistic path is
`pdftoppm | chafa` (or render to PNG via `pdfium-render` and feed to
`ratatui-image`). Defer past the MVP.

Sources:
- https://github.com/benjajaja/ratatui-image
- https://docs.rs/crate/ratatui-image/latest

## Bottom Line

The best MVP is not "Rust Textual." It is a Rust frontend over SASE's existing
Rust backend contracts, with Ratatui as the rendering layer and a deliberately
small local app architecture. The Agents tab is a good first target because
the hardest data path, artifact scan/index, is already in `sase-core`. Use that
advantage, keep launch out of scope initially, and make semantic parity tests
the guardrail before expanding to the rest of ACE.

