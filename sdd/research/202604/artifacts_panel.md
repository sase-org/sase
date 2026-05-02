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

Most per-agent marker artifacts live under
`~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>/`. Chat transcripts, archived plans,
and some sharded diffs live alongside under other `~/.sase/` roots.

```
~/.sase/
├─ projects/<project>/
│  ├─ <project>.gp                              # active ChangeSpecs
│  ├─ <project>-archive.gp                      # terminal ChangeSpecs
│  └─ artifacts/
│     ├─ ace-run/<YYYYmmddHHMMSS>/
│     │  ├─ running.json | done.json | waiting.json
│     │  ├─ agent_meta.json                     # name, chat_path, output_path, response_path
│     │  ├─ raw_xprompt.md                      # pre-expansion prompt
│     │  ├─ *_prompt.md                         # expanded prompt(s), step-specific for workflows
│     │  ├─ live_reply.md
│     │  ├─ live_reply_timestamps.jsonl
│     │  ├─ response.md or provider response file via done/agent_meta
│     │  ├─ diff.md                             # git-style diff
│     │  ├─ plan_path.json                      # → external plan file
│     │  ├─ plan_feedback.jsonl | qa_log.jsonl
│     │  ├─ retry_state.json | retry_handoff.json
│     │  ├─ usage.json | interrupt_log.jsonl | interrupt_request.json
│     │  ├─ codex_thinking.jsonl
│     │  ├─ workflow_state.json                 # workflow runs only
│     │  ├─ prompt_step_<N>.json
│     │  ├─ embedded_workflows.json | embedded_workflows_<step>.json
│     │  ├─ commit_diff.diff | commit_result.json
│     │  ├─ attempts/<N>/attempt_meta.json
│     │  ├─ attempts/<N>/live_reply.md
│     │  ├─ attempts/<N>/live_reply_timestamps.jsonl
│     │  ├─ markdown_pdfs/index.json
│     │  ├─ markdown_pdfs/*.pdf
│     │  └─ <image>.png|jpg|jpeg|gif|webp
│     ├─ workflow-<name>/<timestamp>/…
│     ├─ mentor-<profile>/<timestamp>/…
│     ├─ fix-hook/<timestamp>/…
│     └─ crs/<timestamp>/…
├─ chats/<cl_name>[-mentor_<profile>]-<timestamp>.md
├─ plans/<YYYYmm>/...                         # archived plan files
├─ diffs/<YYYYmm>/...                         # sharded workflow/commit diffs
└─ agent_tags.json
```

### 3.1 Artifact types and where they come from

| Artifact | Storage | Producer | Reader / accessor |
|---|---|---|---|
| Chat transcript | `~/.sase/chats/*.md` | Agent runtime (Claude/Codex/Gemini) | `agent_meta.json["chat_path"]`; `sase_chats` skill |
| Live reply | `artifacts/<wf>/<ts>/live_reply.md` + `live_reply_timestamps.jsonl` | LLM subprocess stream adapter | `Agent.get_live_reply_content()`; `render_agent_reply_content()` |
| Response | `done.json["response_path"]` / `agent_meta.json["chat_path"]` fallback | Agent runner / runtime | prompt panel and agent-log modal |
| Expanded prompt | `*_prompt.md` in artifacts dir | `llm_provider.postprocessing.save_prompt_to_file()` / workflow executor | prompt panel `get_prompt_content()` |
| Raw xprompt | `raw_xprompt.md` | Agent dispatcher | `get_raw_xprompt_content()`; agent-log modal |
| Diff | `artifacts/<wf>/<ts>/diff.md` | Coder agents | `agent.diff_path`; `get_agent_diff()` in `file_panel/_diff.py` |
| Plan | path inside `plan_path.json` | Planner agents (`role_suffix=".plan"`) | `modals/plan_approval_modal.py:105+` |
| Plan feedback | `plan_feedback.jsonl` | plan-review / feedback flow | `history/chat_extras.py` formats into chat history |
| Q&A log | `qa_log.jsonl` | question/answer flow | `history/chat_extras.py` formats into chat history |
| Image | `artifacts/<wf>/<ts>/*.png|jpg` | Screenshot/diagram-producing agents | `is_supported_image_path()`; Kitty render in `file_panel/_display.py` |
| Markdown PDF | `markdown_pdfs/*.pdf` + `markdown_pdfs/index.json` | `attachments/markdown_pdf.py` | `done.json["markdown_pdf_paths"]` → file panel extra files |
| Thinking | inline in response or sidecar files | Model-native thinking blocks | `parse_thinking_blocks_multi()`; `read_codex_thinking()`; `read_gemini_log()` |
| Codex thinking | `codex_thinking.jsonl` | Codex NDJSON streaming parser | `read_codex_thinking()` in `thinking/parser.py` |
| `agent_meta.json` | `artifacts/<wf>/<ts>/` | Agent framework | `_loaders/_meta_enrichment.py:39+` (`enrich_agent_from_meta`) |
| `done.json` | `artifacts/<wf>/<ts>/` | Agent framework on completion | history queries; revision tracking |
| `running.json` | `artifacts/ace-run/<ts>/` for home-mode agents | Agent launcher | `load_running_home_agents_*()` |
| `waiting.json` | `artifacts/<wf>/<ts>/` | wait/resume flow and TUI wait edits | `_meta_enrichment.py` overrides RUNNING → WAITING |
| `retry_state.json` | `artifacts/<wf>/<ts>/` | in-process retry / fallback loop | `_meta_enrichment.py` retry fields |
| `retry_handoff.json` | `artifacts/<wf>/<ts>/` | Spawn-on-retry path (`src/sase/axe/run_agent_retry_spawn.py`) | retry chain reconstruction |
| `workflow_state.json` | `artifacts/workflow-<name>/<ts>/` | Workflow engine | step / output replay |
| `prompt_step_*.json` | workflow artifacts dir | workflow executor | workflow step agents and embedded workflow rendering |
| Embedded workflow metadata | `embedded_workflows*.json` | workflow prompt expansion | prompt panel header and workflow-step rendering |
| Attempt history | `artifacts/<wf>/<ts>/attempts/<N>/attempt_meta.json` + reply files | In-process retry path | `load_attempt_history()`; `agent.attempt_history` |
| Usage log | `usage.json` | LLM subprocess wrapper | not currently surfaced in TUI detail |
| Interrupt log/request | `interrupt_log.jsonl`, `interrupt_request.json` | provider interrupt support | not currently surfaced as artifacts |
| Commit workflow marker | `commit_diff.diff`, `commit_result.json` | commit workflow | commit post-processing / ChangeSpec drawers |

### 3.2 Artifact discovery (already centralised)

There are now **two distinct layers** that matter:

1. `src/sase/ace/tui/models/agent_artifacts.py` resolves a loaded `Agent` →
   artifacts dir and reads individual prompt/reply files.
2. `src/sase/core/agent_scan_facade.py` / `agent_scan_wire.py` performs the
   global artifact-tree scan, backed by the Rust `scan_agent_artifacts` binding.

`agent_artifacts.py` resolves an agent → artifacts dir:

1. project name from `agent.project_file`
2. workflow name from `agent.agent_type` + `agent.workflow`
3. timestamp from `agent.raw_suffix`, normalised by `extract_artifacts_timestamp()`
4. join → `~/.sase/projects/{project}/artifacts/{workflow_name}/{timestamp}/`

The global scan contract visits `projects/*/artifacts/<workflow>/<timestamp>/`
and parses a fixed marker set: `agent_meta.json`, `done.json`, `running.json`,
`waiting.json`, `workflow_state.json`, `plan_path.json`, and `prompt_step_*.json`.
The TUI loader already uses one snapshot per refresh via
`models/agent_loader.py:_scan_artifacts_for_loader()` with prompt-step markers
enabled and raw prompt snippets disabled.

There is also a memoising layer:
`sase.agent.agent_artifacts_cache.get_global_cache()`. It caches per-file reads
and append-only live replies, but it is **not** the global index. Any new panel
should probably build its index from `AgentArtifactScanWire` and then use
`agent_artifacts.py` / `agent_artifacts_cache.py` for per-file content.

### 3.3 Current artifact consumers not mentioned in the initial surface list

- `AgentPromptPanel` is already an artifact viewer. It reads `*_prompt.md`,
  `raw_xprompt.md`, `live_reply.md`, `live_reply_timestamps.jsonl`,
  `response_path`, `chat_path`, `workflow_state.json`,
  `prompt_step_*.json`, and `embedded_workflows*.json`.
- `AgentContentSearchCache` indexes artifact content for Agents-tab `/` search:
  raw xprompt, live reply, response/chat fallback, and prior-attempt replies.
- `AgentRunLogModal` previews raw xprompt and response content, then opens
  `agent.response_path` in `$EDITOR`.
- `history/chat_extras.py` folds `plan_path.json`, `plan_feedback.jsonl`, and
  `qa_log.jsonl` into archived chat history.

This matters for the new panel because "artifact viewer" behavior is currently
spread across prompt panel, file panel, thinking panel, search, and history
formatters — not only across the three surfaces named for replacement.

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

- `models/agent_loader.py:load_all_agents()` — returns the flat `list[Agent]` used by the
  Agents tab; internally it now acquires one `AgentArtifactScanWire` snapshot and adapts done,
  running-home, workflow-state, and workflow-step records from that snapshot.
- `_loaders/_meta_enrichment.py:enrich_agent_from_meta()` and
  `enrich_agent_from_meta_wire()` — filesystem and snapshot mirrors for folding in
  `agent_meta.json` / `waiting.json`.
- `_loaders/_done_loaders.py:_done_extra_files()` — the current list of file-panel extras:
  plan path, generated Markdown PDFs, and image paths from `done.json`.
- `_loaders/_workflow_snapshot_loaders.py` — snapshot-backed workflow and workflow-step adapters.
- `changespec/cache.py:get_global_snapshot_cache()` — caches parsed `.gp` files

`load_all_agents()` already performs some graph assembly after loading:

- Propagates `.code` child `diff_path` to the `.plan` parent so the parent file panel shows code
  changes instead of only the planner artifact.
- Attaches follow-up children (`parent_timestamp`, no `parent_workflow`) to `parent.followup_agents`.
- Builds `retry_chain_siblings` from `retry_of_timestamp`.
- Uses step-output `meta_*` fields to surface generated ChangeSpecs/projects in headers and in the
  CL agent-log modal.

What is **missing** is a service that exposes the full bidirectional graph as a first-class query
API. Today, each tab re-derives slices: the CLs tab queries `load_all_agents()` filtered by
`cl_name`; the Agents tab sorts the same list by tag/timestamp; notifications have their own
navigation helpers. An artifacts panel that needs to walk agent → CL → siblings → artifacts in both
directions will benefit from a small relationship layer (or at least a shared accessor) rather than
ad-hoc joins.

### 4.4 Generated-ChangeSpec linking

The CL agent-log modal does not only match `agent.cl_name`. It also includes project agents that
created the selected ChangeSpec by inspecting `meta_changespec`, `meta_new_cl`, and `meta_new_pr`
via `actions/agents/_notification_actions.py:get_meta_changespec_name()`. This is an important edge
case for the artifact graph: a project-level workflow can produce a ChangeSpec whose artifacts
should be reachable from that ChangeSpec even though the original agent's `cl_name` is the project.

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
| Jump agent → CL | configured key | `action_jump_to_agent_changespec()` / `navigate_to_changespec_tab()` style helpers |
| Agent-log row → Agents tab | `Enter` | `AgentRunLogModal.action_jump_to_agent_tab()` revives dismissed agents if needed |
| Notifications → agent/CL | modal action | `actions/agents/_notification_handlers.py` + `_notification_navigation.py` |
| Modal commands | command palette | `commands/catalog.py` + `commands/availability.py` + `commands/execute.py` |
| Keybindings | configurable | `keymaps/loader.py`; defaults in `bindings.py`; user override at `~/.sase/keybindings.json` |

There is **no URI / scheme handler** today — cross-entity navigation happens by setting
`current_tab` + `current_idx` directly (see `watch_current_tab()` for the swap dance) or by
dedicated helper functions. An artifact-link affordance ("jump to the agent that produced this
diff", "jump to the ChangeSpec this plan is for") would need either a small URI scheme or a typed
action verb. The notification navigation helpers are the closest existing typed-action precedent.

---

## 6. Reusable widgets and infrastructure

### 6.1 Lists & containers
- `OptionList` extensions: `AgentList`, `ChangeSpecList`, `BgCmdList` (group-aware, multi-level)
- `VerticalScroll` is the canonical detail-panel wrapper
- `section_builders.py` — reusable renderers for Commits, Hooks, Comments, Mentors, Deltas

### 6.2 Rendering
- `prompt_panel/__init__.py` — Rich text + markdown + model/provider badges
- `file_panel/_display.py` — Pygments syntax highlighting + Kitty image protocol + diff coloring
- `graphics/images.py` — capability probing, Kitty renderables, and fallback image previews
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
- `agent_artifacts_cache.get_global_cache()` — per-file text/JSON/reply-chunk/live-tail cache
- `models/agent_content_search.py:AgentContentSearchCache` — lowercased prompt/reply/attempt
  content cache for Agents-tab filtering
- `models/_loaders/_json_cache.py` — JSON loader cache and thread-pool executor shared by loaders

### 6.6 Async loading pattern
- Textual `Worker` for non-blocking fetches (used by file & thinking panels)
- `call_after_refresh()` for batched UI updates
- Generation counters to discard stale completions when the user moves on
- `util/fs_watcher.py:ArtifactWatcher` — Linux inotify watcher used as a refresh wakeup source,
  with polling as a safety net. It is non-recursive; startup watches each project dir and each
  project `artifacts/` dir, so deep marker writes sometimes need a visible parent-level pulse
  (`main/plan_command_handler.py` writes `.ace_refresh_pulse` for this reason).

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

- Centralising artifact-discovery behind a single `ArtifactsService` should start from
  `AgentArtifactScanWire`, not from `agent_artifacts_cache`. The scan wire already provides a
  stable project/workflow/timestamp record plus parsed marker projections; `agent_artifacts_cache`
  is better treated as a content-read cache under that service.
- The service probably needs two concepts:
  - **Artifact directory record**: one `AgentArtifactRecordWire`, keyed by
    `(project, workflow_dir_name, timestamp)`.
  - **Logical artifact item**: a typed item such as `chat`, `live_reply`, `diff`, `plan`,
    `image`, `markdown_pdf`, `thinking`, `attempt_reply`, `workflow_step`, or `marker`.
- Live updates: the file panel uses generation counters + workers; the thinking panel uses TTL
  caching; the app also has an inotify wakeup + polling safety net. The new panel needs to compose
  all three patterns. If it wants deep per-file freshness, the current watcher is not enough by
  itself because it is non-recursive and coarse-grained.
- Malformed artifact JSON should not break the panel. The Rust scan facade treats bad marker JSON
  as a soft error and increments scan stats; a panel should preserve that tolerance and expose
  diagnostics only when useful.

### 7.6 Rendering

- Rich already covers markdown/diff/syntax/Kitty images, so the rendering primitives exist. The
  bigger question is _embedding_ — do you render the artifact inline in the panel, or open it in a
  dedicated viewer modal (the way `plan_approval_modal` does)? A two-pane "list + preview" inside
  the artifacts panel is the natural compromise but adds layout complexity.
- PDF support is only produced as attachment files today; the file panel's static renderer does not
  appear to have a PDF preview path equivalent to Kitty images. A unified panel should decide
  whether PDFs are "open externally" artifacts, text-extracted previews, or rendered previews.
- `usage.json`, `interrupt_log.jsonl`, `retry_state.json`, `plan_feedback.jsonl`, and `qa_log.jsonl`
  need small purpose-built renderers if they should be more useful than raw JSON/JSONL.

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
- `src/sase/ace/tui/widgets/prompt_panel/` — already renders prompt/reply/workflow artifacts; a
  new panel must either integrate with it or intentionally leave it as metadata/reply-only
- `src/sase/ace/tui/modals/agent_run_log_modal.py` — replace
- `src/sase/ace/tui/widgets/agent_detail.py` + `_agent_detail_panels.py` — recompose
- `src/sase/ace/tui/app.py` — possibly a new view container
- `src/sase/ace/tui/actions/navigation/` — new cross-entity verbs
- `src/sase/ace/tui/commands/catalog.py` + `availability.py` — register new commands
- `src/sase/ace/tui/keymaps/` + `bindings.py` — bind keys
- `src/sase/ace/tui/models/agent_artifacts.py` + `src/sase/agent/agent_artifacts_cache.py` —
  current per-agent path/content helpers
- `src/sase/core/agent_scan_wire.py` + `agent_scan_facade.py` — extend only if the service needs
  additional marker fields from the Rust scan boundary
- `src/sase/ace/tui/models/agent_loader.py` + `models/_loaders/` — current snapshot-to-Agent
  adapters and relationship assembly
- `src/sase/ace/tui/models/agent_content_search.py` — if artifact content search grows beyond
  prompt/reply/attempt text
- `src/sase/ace/tui/util/fs_watcher.py` + `actions/event_handlers.py` — if artifacts panel needs
  finer-grained live update semantics
- `src/sase/ace/tui/models/_loaders/` — possibly a new "all artifacts for entity" loader
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
7. **Prompt/reply ownership**: should the unified artifacts panel absorb the prompt panel's reply
   rendering, or should prompt/reply remain in `AgentPromptPanel` while the new panel handles
   secondary artifacts?
8. **Deep live updates**: is the existing coarse inotify + polling refresh enough, or does this
   panel need recursive/deep watches or producer-side pulse files for every artifact write?
9. **Structured marker rendering**: should marker files (`usage.json`, `retry_state.json`,
   `plan_feedback.jsonl`, `qa_log.jsonl`, `commit_result.json`) be first-class typed views or just
   raw JSON/JSONL artifacts initially?
