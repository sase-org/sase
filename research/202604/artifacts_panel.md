# Artifacts Panel — Research

Research notes for designing a unified **Artifacts Panel** in the sase TUI. The new panel would
obsolete three existing affordances:

1. The **file panel** on the Agents tab
2. The **thinking panel** on the Agents tab
3. The **agent log** modal triggered from the CLs tab

It must surface every artifact an agent or workflow produces — chat logs, diffs, plans, images,
thinking blocks, attempt history, retry handoff state — and act as a navigation hub between
**Agents ↔ Projects ↔ ChangeSpecs ↔ Artifacts**.

This document is a factual lay-of-the-land plus open design questions. It is _not_ a redesign or
implementation plan.

---

## 1. TUI lay-of-the-land

### 1.1 Framework & entry point

- Framework: **Textual** (Python)
- App class: `AceApp` in `src/sase/ace/tui/app.py:78-276`
  - Mixins: `AgentWorkflowMixin`, `AgentsMixin`, `AxeMixin`, `ChangeSpecMixin`, `NavigationMixin`, …
  - CSS: `src/sase/ace/tui/styles.tcss`
- Tab type: `TabName = Literal["changespecs", "agents", "axe"]` (`app.py:65`)
- Tab bar widget: `src/sase/ace/tui/widgets/tab_bar.py` (`TabBar(Static)`)

### 1.2 Layout (today)

```
Header
├─ TabBar + Indicators (TaskIndicator, LLMOverrideIndicator, NotificationIndicator)
├─ Main Container
│  ├─ #changespecs-view  (default)
│  │  ├─ ChangeSpecInfoPanel | ChangeSpecList | AncestorsChildrenPanel
│  │  └─ SearchQueryPanel    | ChangeSpecDetail
│  ├─ #agents-view
│  │  ├─ AgentInfoPanel
│  │  └─ AgentList | AgentDetail
│  └─ #axe-view
│     ├─ BgCmdList
│     └─ AxeInfoPanel | AxeDashboard
├─ KeybindingFooter (conditional)
└─ Footer
```

`AgentDetail` already composes a stack of scrollable subpanels (`AgentPromptPanel`,
`AgentFilePanel`, `AgentThinkingPanel`) with mode-driven visibility — this is the natural insertion
point for a richer artifacts surface, _or_ for a top-level view that replaces parts of the agent
detail.

---

## 2. The three panels being obsoleted

### 2.1 File panel (Agents tab)

- Path: `src/sase/ace/tui/widgets/file_panel/`
- Class: `AgentFilePanel(FilePanelTrimMixin, FilePanelDisplayMixin, Static)` (`__init__.py:31+`)
- Submodules:
  - `_messages.py` — `FileListChanged`, `FileTrimChanged`, `FileVisibilityChanged` + `FileCacheEntry`
  - `_diff.py` — `compute_diff_cache_key`, `get_agent_diff` + in-flight dedup (`_inflight_diff_tasks`)
  - `_display.py` — Rich rendering + Kitty-protocol image rendering
  - `_trim.py` — line-count / viewport trimming
- Renders: live diffs, plan files, images, markdown, raw text logs; cycles through agent files with
  `]` / `[`; shows current index (`[1/3]`).
- Composed inside `VerticalScroll#agent-file-scroll` in `AgentDetail`.
- Visibility driven by `DetailPanelMode` enum in `_agent_detail_panels.py:21` (AUTO / THINKING / INFO).

### 2.2 Thinking panel (Agents tab)

- Path: `src/sase/ace/tui/widgets/thinking_panel.py`
- Class: `AgentThinkingPanel(Static)` (line 105+); message: `ThinkingVisibilityChanged`
- Module-level `_thinking_cache` (line 51) with age-based invalidation
- Pulls from `sase.ace.tui.thinking`:
  - `parse_thinking_blocks_multi()` — multi-model split
  - `read_codex_thinking()`, `read_gemini_log()`
  - `resolve_agent_sessions()`
- Toggled by `]` / `[` → `action_toggle_thinking()` (cycles AUTO → THINKING → INFO → AUTO).

### 2.3 Agent log modal (CLs tab)

- Path: `src/sase/ace/tui/modals/agent_run_log_modal.py`
- Class: `AgentRunLogModal(ModalScreen)` extends `OptionListNavigationMixin`
- Action: `action_show_agent_log` from CLs tab; lists every agent (active + dismissed + bundled) for
  the selected ChangeSpec.
- Loaders: `load_all_agents()`, `load_dismissed_agents()`, `load_dismissed_bundles()`
- Key methods: `_load_agents_for_cl(cl_name)` (line 30), `action_open_chat()` (line ~160) — opens the
  chat transcript in `$EDITOR`.

---

## 3. Artifact taxonomy

All per-agent artifacts live under
`~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>/`. Chat transcripts live alongside in
`~/.sase/chats/`.

```
~/.sase/
├─ projects/<project>/
│  ├─ <project>.gp                              # active ChangeSpecs
│  ├─ <project>-archive.gp                      # terminal ChangeSpecs
│  └─ artifacts/
│     ├─ ace-run/<YYYYmmddHHMMSS>/
│     │  ├─ running.json | done.json
│     │  ├─ agent_meta.json                     # name, chat_path, output_path, response_path
│     │  ├─ raw_xprompt.md                      # pre-expansion prompt
│     │  ├─ diff.md                             # git-style diff
│     │  ├─ plan_path.json                      # → external plan file
│     │  ├─ retry_handoff.json                  # spawn-on-retry chain state
│     │  ├─ workflow_state.json                 # workflow runs only
│     │  ├─ attempts/attempt_<N>.md
│     │  └─ <image>.png|jpg
│     ├─ workflow-<name>/<timestamp>/…
│     ├─ mentor-<profile>/<timestamp>/…
│     ├─ fix-hook/<timestamp>/…
│     └─ crs/<timestamp>/…
├─ chats/<cl_name>[-mentor_<profile>]-<timestamp>.md
└─ agent_tags.json
```

### 3.1 Artifact types and where they come from

| Artifact | Storage | Producer | Reader / accessor |
|---|---|---|---|
| Chat transcript | `~/.sase/chats/*.md` | Agent runtime (Claude/Codex/Gemini) | `agent_meta.json["chat_path"]`; `sase_chats` skill |
| Diff | `artifacts/<wf>/<ts>/diff.md` | Coder agents | `agent.diff_path`; `get_agent_diff()` in `file_panel/_diff.py` |
| Plan | path inside `plan_path.json` | Planner agents (`role_suffix=".plan"`) | `modals/plan_approval_modal.py:105+` |
| Image | `artifacts/<wf>/<ts>/*.png|jpg` | Screenshot/diagram-producing agents | `is_supported_image_path()`; Kitty render in `file_panel/_display.py` |
| Thinking | inline in response or sidecar files | Model-native thinking blocks | `parse_thinking_blocks_multi()`; `read_codex_thinking()`; `read_gemini_log()` |
| `agent_meta.json` | `artifacts/<wf>/<ts>/` | Agent framework | `_loaders/_meta_enrichment.py:39+` (`enrich_agent_from_meta`) |
| `done.json` | `artifacts/<wf>/<ts>/` | Agent framework on completion | history queries; revision tracking |
| `retry_handoff.json` | `artifacts/<wf>/<ts>/` | Spawn-on-retry path (`src/sase/axe/run_agent_retry_spawn.py`) | retry chain reconstruction |
| `workflow_state.json` | `artifacts/workflow-<name>/<ts>/` | Workflow engine | step / output replay |
| `raw_xprompt.md` | `artifacts/<wf>/<ts>/` | Agent dispatcher | `get_raw_xprompt_content()` in `agent_artifacts.py` |
| Attempt history | `artifacts/<wf>/<ts>/attempts/attempt_<N>.md` | In-process retry path | `load_attempt_history()`; `agent.attempt_history` |

### 3.2 Artifact discovery (already centralised)

`agent_artifacts.py:16-103` resolves an agent → artifacts dir:

1. project name from `agent.project_file`
2. workflow name from `agent.agent_type` + `agent.workflow`
3. timestamp from `agent.raw_suffix`, normalised by `extract_artifacts_timestamp()`
4. join → `~/.sase/projects/{project}/artifacts/{workflow_name}/{timestamp}/`

There is also a memoising layer: `sase.agent.agent_artifacts_cache.get_global_cache()`. Any new
panel should sit on top of this rather than re-implementing path resolution.

---

## 4. Entity graph

### 4.1 Identity keys

| Entity | Identity | Source of truth |
|---|---|---|
| **Agent** | `(agent_type, cl_name, raw_suffix)` tuple; plus optional `agent_name` | `running.json` / `done.json` + `agent_meta.json` |
| **Project** | directory name under `~/.sase/projects/` | filesystem |
| **ChangeSpec** | `cl_name` inside a `.gp` file | `<project>.gp` and `<project>-archive.gp` |
| **Artifact** | `(project, workflow, timestamp)` triple | filesystem path under `artifacts/` |

### 4.2 Linking fields

- `agent.cl_name` → ChangeSpec
- `agent.project_file` → project (`Path(...).parent.name`)
- `agent.raw_suffix` (+ `agent.start_time`) → artifacts directory timestamp
- `agent.agent_name` (from `%name` directive or TUI rename) → human-readable handle, also used in
  other agents' `agent.waiting_for` lists
- `agent.followup_agents` → role-suffixed children (`.plan`, `.code`, `.q`)
- `agent.parent_timestamp` → parent workflow step
- Retry chain (`Agent` model fields):
  - `retry_of_timestamp` (parent), `retried_as_timestamp` (child),
    `retry_chain_root_timestamp` (root), `retry_chain_siblings`, `retry_error_category`

### 4.3 Existing aggregation layers

- `_loaders/__init__.py:load_all_agents()` — scans every
  `~/.sase/projects/*/artifacts/*/*/{running,done}.json`, returns flat `list[Agent]`
- `_loaders/_meta_enrichment.py:enrich_agent_from_meta()` — folds in `agent_meta.json`
- `changespec/cache.py:get_global_snapshot_cache()` — caches parsed `.gp` files

What is **missing** is a service that exposes the full bidirectional graph. Today, each tab
re-derives slices: the CLs tab queries `load_all_agents()` filtered by `cl_name`; the Agents tab
sorts the same list by tag/timestamp. An artifacts panel that needs to walk
agent → CL → siblings → artifacts in both directions will benefit from a small relationship layer
(or at least a shared accessor) rather than ad-hoc joins.

---

## 5. Existing navigation primitives

These are all candidates for reuse / extension when wiring the new panel.

| Primitive | Keys | Implementation |
|---|---|---|
| Switch tab | `Tab` / `Shift+Tab` | `action_next_tab()` / `action_prev_tab()`; reactive `current_tab` (`app.py:295`) |
| Jump mode (within tab) | `'` | `action_jump_to_entry()` in `actions/navigation/_advanced.py:158-238` |
| Jump mode (cross-tab) | `` ` `` | `action_jump_to_all_entries()` |
| Entry selection | `j` / `k` | `action_next_changespec()` / `action_prev_changespec()`; reactive `current_idx` |
| File cycling | `]` / `[` | `action_next_agent_file()` / `action_prev_agent_file()` |
| Detail panel mode toggle | `]` / `[` | `action_toggle_thinking()` (cycles AUTO → THINKING → INFO) — _shared keymap with file cycling, context-dependent_ |
| Modal commands | command palette | `commands/catalog.py` + `commands/availability.py` + `commands/execute.py` |
| Keybindings | configurable | `keymaps/loader.py`; defaults in `bindings.py`; user override at `~/.sase/keybindings.json` |

There is **no URI / scheme handler** today — cross-entity navigation happens by setting
`current_tab` + `current_idx` directly (see `watch_current_tab()` for the swap dance). A
artifact-link affordance ("jump to the agent that produced this diff", "jump to the ChangeSpec
this plan is for") would need either a small URI scheme or a typed action verb.

---

## 6. Reusable widgets and infrastructure

### 6.1 Lists & containers
- `OptionList` extensions: `AgentList`, `ChangeSpecList`, `BgCmdList` (group-aware, multi-level)
- `VerticalScroll` is the canonical detail-panel wrapper
- `section_builders.py` — reusable renderers for Commits, Hooks, Comments, Mentors, Deltas

### 6.2 Rendering
- `prompt_panel/__init__.py` — Rich text + markdown + model/provider badges
- `file_panel/_display.py` — Pygments syntax highlighting + Kitty image protocol + diff coloring
- `_text_formatting.py`, `_line_rendering.py` — duration/timestamp/truncation helpers

### 6.3 State & focus
- `app.current_idx` (reactive) auto-clears attempt selection on tab/entry change
- `app._current_attempt_number` pins a prior attempt; `None` = live
- `_agent_detail_generation` counter (`app.py:55`) discards stale async results
- Jump-hint mappings: `_entry_jump_hint_to_index`, `_entry_jump_index_to_hint`,
  `_entry_jump_hint_to_banner`

### 6.4 Modals
- Base: `OptionListNavigationMixin`
- Examples:
  - `confirm_action_modal.py` — yes/no
  - `project_select_modal.py`, `parent_select_modal.py` — list pick
  - `command_input_modal.py`, `agent_name_modal.py` — text entry
  - `plan_approval_modal.py` — read-only display + accept/reject (most analogous to a "view
    artifact" modal)
  - `agent_cleanup_modal.py` — multi-select kill/dismiss
  - `agent_run_log_modal.py` — _the very modal we're trying to obsolete_

### 6.5 Caching
- `file_panel/_messages.py:FileCacheEntry` — content cache keyed by `(agent, content type)`
- `file_panel/_diff.py:DiffCacheKey` + `_inflight_diff_tasks` — diff dedup
- `thinking_panel.py:_thinking_cache` — age-validated thinking cache
- `agent_artifacts_cache.get_global_cache()` — artifact dir memoisation

### 6.6 Async loading pattern
- Textual `Worker` for non-blocking fetches (used by file & thinking panels)
- `call_after_refresh()` for batched UI updates
- Generation counters to discard stale completions when the user moves on

---

## 7. Design considerations / open questions

These are the questions a design will need to answer; tradeoffs noted but no answers picked.

### 7.1 Scope

- **One panel or a new tab?** A panel inside the Agents tab keeps context next to live agent state
  but inherits the AUTO/THINKING/INFO mode jumble. A top-level "Artifacts" tab gets dedicated
  navigation but duplicates the agent list. A third option: keep it _inside_ AgentDetail but
  collapse file + thinking + attempts into one consistent artifacts surface, and move the
  CLs-tab agent-log modal to "open this CL's agents in the artifacts panel".
- **Agent-scoped or graph-scoped?** Today's panels are agent-scoped (you pick an agent, then see
  its files). The user request mentions linking agents/projects/CLs/artifacts — implying the
  panel may need to be browsed _from_ any of those three entry points (agent → its artifacts;
  CL → all agents' artifacts; project → all artifacts).

### 7.2 Information architecture

- **List shape.** Choices include:
  - **Flat** list of artifacts (one row per file) — familiar but loses grouping.
  - **Tree** keyed by agent → artifact category → file — matches filesystem layout, mirrors how
    `agent_artifacts.py` resolves things, but deep trees are hard to skim.
  - **Faceted**: top-level facet picker (Chats / Diffs / Plans / Images / Thoughts / Other) + flat
    list within each facet.
- **What is a row?** A single file? A logical artifact group (e.g. all attempts of one agent
  collapsed)? A retry chain? Decide before picking a widget — `OptionList` is great for flat,
  `Tree` for hierarchical.
- **Default ordering.** Chronological (newest first) is the obvious default. But artifact category
  matters too — if you opened the panel from a CL, "diff" and "plan" probably want top billing.

### 7.3 Cross-entity navigation

- The cleanest existing pattern is the `action_jump_to_all_entries` cross-tab jump-mode hint
  system. An artifacts panel could expose verbs like:
  - `g a` — go to the agent that produced this artifact
  - `g c` — go to the ChangeSpec this artifact's agent runs against
  - `g p` — go to the project
  - `g r` — go to the retry-chain root agent
- Alternatively, introduce a real URI scheme (`sase://agent/<ts>`, `sase://changespec/<cl>`,
  `sase://artifact/<project>/<wf>/<ts>/<file>`) and a single `open` verb that dispatches by
  scheme. URIs are more work but pay off when artifacts cross-reference each other (e.g. a chat
  log mentioning a sibling agent).

### 7.4 Retry chains & followups

- The retry-chain fields (`retry_of_timestamp`, `retried_as_timestamp`, `retry_chain_root_timestamp`,
  `retry_chain_siblings`) imply that "all artifacts of an agent" is sometimes really "all artifacts
  of all retry attempts of an agent". The panel should decide whether to:
  - show only the surviving (latest) agent's artifacts, with siblings reachable via a verb, or
  - show the whole chain inline, grouped by attempt.
- Same question for `agent.attempt_history` (in-process retries).
- And for `followup_agents` (`.plan`, `.code`, `.q`) — do they collapse into the parent's view, or
  appear as sibling rows?

### 7.5 Data layer

- Centralising artifact-discovery behind a single `ArtifactsService` (or extending
  `agent_artifacts_cache`) would let both this panel and the existing `agent_artifacts.py` callers
  share one indexer. Rebuilding the file/thinking/attempt loaders on top of this service is
  probably necessary before you can collapse them into one panel.
- Live updates: the file panel uses generation counters + workers to invalidate; the thinking
  panel uses TTL caching. The new panel needs to pick one or compose both. Watching the
  filesystem (e.g. `inotify`) is _not_ used today — polling is the norm.

### 7.6 Rendering

- Rich already covers markdown/diff/syntax/Kitty images, so the rendering primitives exist. The
  bigger question is _embedding_ — do you render the artifact inline in the panel, or open it in a
  dedicated viewer modal (the way `plan_approval_modal` does)? A two-pane "list + preview" inside
  the artifacts panel is the natural compromise but adds layout complexity.

### 7.7 Migration / coexistence

- The three obsoleted surfaces have keybindings (`]` / `[`, the CLs-tab agent-log action) that
  users already have muscle memory for. The new panel should probably steal those keys verbatim
  and let users re-bind, rather than introducing a parallel keymap.
- The `DetailPanelMode` enum in `_agent_detail_panels.py:21` is currently the central thing that
  decides which sub-panel is visible. Either extend it (add `ARTIFACTS` mode) or rip it out and
  let the new panel own visibility itself.

---

## 8. Files most likely to change

A non-exhaustive checklist of modules that any artifacts-panel implementation will touch:

- `src/sase/ace/tui/widgets/file_panel/` — collapse / repurpose
- `src/sase/ace/tui/widgets/thinking_panel.py` — collapse / repurpose
- `src/sase/ace/tui/modals/agent_run_log_modal.py` — replace
- `src/sase/ace/tui/widgets/agent_detail.py` + `_agent_detail_panels.py` — recompose
- `src/sase/ace/tui/app.py` — possibly a new view container
- `src/sase/ace/tui/actions/navigation/` — new cross-entity verbs
- `src/sase/ace/tui/commands/catalog.py` + `availability.py` — register new commands
- `src/sase/ace/tui/keymaps/` + `bindings.py` — bind keys
- `src/sase/agent/agent_artifacts.py` + `agent_artifacts_cache.py` — likely candidate for extending
  into a richer service
- `src/sase/ace/tui/_loaders/` — possibly a new "all artifacts for entity" loader
- Tests under `tests/ace/tui/` mirroring the above

---

## 9. Open questions for the user

1. **Scope of obsolescence**: do you also want this to absorb the `prompt_panel` (which already
   shares space with file/thinking), or only the three you named?
2. **Tab vs panel**: top-level "Artifacts" tab, or a new mode inside `AgentDetail`?
3. **Entry points**: should the panel be openable from the CLs tab, the Agents tab, _and_ a new
   project picker? (Today there is no project-as-entity tab.)
4. **Retry chains and followups**: collapse by default, or expand?
5. **URI scheme** vs typed `g <letter>` verbs for cross-entity nav?
6. **Live preview pane** inside the panel, or modal viewer per artifact?
