# `sase ace` Responsiveness Profile Review (2026-05-15)

## Source

- Profile artifact: `/home/bryan/tmp/sase/ace_profile_20260515_004214.txt`
- Command: `sase ace --profile`
- Tool: pyinstrument v5.1.2
- Recorded: 2026-05-15 00:41:22
- Duration: 51.864s wall, 58.924s CPU, 7,463 samples
- Profile root: `src/sase/main/ace_handler.py:74`

This capture is a live interactive session, not only startup. The largest bucket
is event-loop wait (`epoll.poll`, 41.95s), but the actionable CPU samples point
to repeated detail-pane rendering and a few main-thread discovery paths that can
make the TUI feel unresponsive while the app is otherwise "running".

## TL;DR

The May 2 startup profile found hidden cold-load time in off-thread agent
loading. This May 15 profile shows a different problem: **the selected agent
detail pane is expensive to render repeatedly**, especially when the prompt pane
is expanded and Textual rerenders Rich `Syntax` renderables through Pygments.

Highest-value fixes:

1. Cache prompt-panel renderables/strips by selected-agent content identity and
   width, or render large prompt/reply bodies as plain `Text` earlier. The hot
   path is `AgentPromptPanel.render_lines` -> Rich `Syntax` -> Pygments
   Markdown lexer.
2. Stop recomputing artifact and delta sections synchronously inside
   `build_header_text()`. The footer already has an off-thread artifact cache,
   but the header path calls `list_agent_artifacts()` again and can also call
   live VCS diff discovery.
3. Cache LLM provider lookup for the top-bar model indicator. One refresh spent
   0.655s on `importlib.metadata.entry_points()` and provider construction on
   the UI thread.
4. Avoid firing a full detail refresh as the continuation of background
   artifact discovery. Patch only the footer/artifact state, or feed the
   discovered artifacts into the header renderer rather than re-entering the
   synchronous header path.

## Captured Hot Paths

### 1. Prompt Panel Render Cost

Main render branch:

```text
5.091 Timer._run_timer
└─ 4.343 Screen._on_timer_update
   └─ 4.088 Screen._refresh_layout
      └─ 2.696 Compositor.render_partial_update
         └─ 2.685 Compositor._render_chops
            └─ 2.385 Compositor._get_renders
               └─ 1.763 AgentPromptPanel.render_lines
                  └─ RichVisual.render_strips
                     └─ Segment.split_and_crop_lines
                        └─ Console.render
                           └─ Syntax.__rich_console__
                              └─ Syntax._get_syntax
                                 └─ MarkdownLexer.get_tokens_unprocessed
```

The prompt panel builds `Syntax` objects via `lazy_renderable()` for prompt,
reply, response, attempt, bash/python, and JSON step output content
(`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py:137-245`).
`lazy_renderable()` only skips syntax highlighting above 64 KiB or 1,500 lines
(`src/sase/ace/tui/util/lazy_syntax.py:17-69`), so medium-sized markdown can
still be re-tokenized during Textual render/layout.

The capture also shows `AgentPromptPanel.get_content_height` at ~1.02s, which
means the same heavy visual may be paid for both sizing and painting.

**Interpretation:** this is not one slow function call. It is repeated work
during periodic Textual refreshes and detail updates. A user perceives this as
sluggish navigation or delayed repaint after row selection.

### 2. Header Detail Rebuild Does Main-Thread I/O

The debounced full detail update calls:

```text
AgentDetail.update_display
└─ AgentPromptPanel.update_display
   └─ build_header_text
      ├─ append_agent_artifacts_section
      ├─ append_agent_deltas_section
      ├─ append_model_field
      └─ format_agent_bead_display
```

In this profile, a post-artifact-discovery refresh spent 0.290s on the UI
thread:

```text
0.290 AceApp._run_agent_artifact_discovery
└─ 0.290 AceApp._fire_debounced_detail_update
   └─ 0.289 AgentDetail.update_display
      └─ 0.285 AgentPromptPanel.update_display
         └─ 0.282 build_header_text
            ├─ 0.179 append_agent_artifacts_section
            │  └─ list_agent_artifacts
            ├─ 0.050 append_agent_deltas_section
            │  └─ get_agent_diff
            ├─ 0.027 append_model_field
            └─ 0.025 format_agent_bead_display
```

The issue is not that artifact discovery lacks a background path. It has one:
`_run_agent_artifact_discovery()` calls `asyncio.to_thread(...)` and stores a
per-row cache (`src/sase/ace/tui/actions/agents/_panel_artifacts.py:300-317`).
The problem is that the continuation calls `_fire_debounced_detail_update()`
(`src/sase/ace/tui/actions/agents/_panel_artifacts.py:328-331`), and the prompt
header path ignores that cache:

- `build_header_text()` appends deltas and artifacts whenever `cheap=False`
  (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py:385-390`).
- `append_agent_artifacts_section()` calls `_agent_artifact_paths()`, which
  calls `list_agent_artifacts(artifacts_dir)` synchronously
  (`src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py:34-67`).
- `append_agent_deltas_section()` calls `get_agent_diff()`, which can read a
  diff file, resolve a VCS provider, and run `provider.diff_with_untracked(...)`
  for active agents (`src/sase/ace/tui/widgets/file_panel/_diff.py:95-159`).

**Interpretation:** the detail header has become a second artifact/diff
discovery surface. Even when the footer probes artifacts safely, the header
re-enters expensive synchronous work.

### 3. Top-Bar LLM Indicator Blocks Once

The profile captured one `LLMOverrideIndicator.refresh()` costing 0.655s:

```text
0.655 LLMOverrideIndicator.refresh
└─ _build_default_content
   └─ resolve_effective_default_provider_model
      └─ get_provider
         └─ _create_provider_for
            └─ _find_plugin_class
               └─ importlib.metadata.entry_points
```

The widget calls `_build_content()` in `__init__`, again in `on_mount()`, and
then every 30 seconds (`src/sase/ace/tui/widgets/llm_override_indicator.py:45-57`).
`get_provider()` always creates a provider through `_create_provider_for()`,
which scans entry points via `_find_plugin_class()` each time
(`src/sase/llm_provider/registry.py:157-210`). Separately, metadata helpers
also call `_llm_metadata_payload()`, which is not cached despite `_build_llm_pm()`
itself being cached (`src/sase/llm_provider/registry.py:38-116`).

**Interpretation:** the cost is probably first-call/cold-cache sensitive, but it
happens on the Textual event loop. It is easy to move out of the render path.

### 4. Startup Costs Are Present But Not Dominant Here

`AceApp.__init__` was only 0.182s:

- `load_merged_config`: 0.071s, mostly PyYAML default config parsing.
- `load_dismissed_agents`: 0.055s.
- `load_keymap_registry`: 0.042s, again PyYAML.

Post-first-paint watcher setup was 0.088s, mostly artifact watch path scans and
`ctypes.util.find_library("c")`. These remain worth improving, but this profile
does not support treating them as the main responsiveness problem.

## Recommended Fix Plan

### P0 - Remove Full Detail Refresh From Artifact Discovery Completion

Change `_run_agent_artifact_discovery()` so completion updates only the
artifact cache and footer binding state. Do not call
`_fire_debounced_detail_update()` unless the prompt header is explicitly able to
consume the cached artifact list without touching disk.

Concrete options:

- Add an `artifacts` parameter to prompt header rendering and pass the cached
  result through the detail update.
- Split the header into cheap metadata plus async append-only "artifact/delta"
  sections.
- For a minimal first fix, keep ARTIFACTS out of the prompt header and rely on
  the footer/artifact viewer affordance.

Expected impact: removes the 0.290s UI-thread continuation seen in this
profile and prevents background artifact work from causing a visible hitch when
it finishes.

### P1 - Make Prompt Body Rendering Cacheable

Today the detail update constructs Rich renderables, but Textual/Rich still
turn those renderables into strips repeatedly during layout and paint. Add a
cache at the prompt-panel level keyed by:

- selected agent identity;
- prompt/reply/response file path + mtime/size, or content hash if content is
  already loaded;
- attempt view mode / pinned attempt;
- render width.

The cached value can be a rendered plain `Text`/`Group` for the current width,
or a custom renderable that memoizes generated strips. If strip caching is too
deep into Textual internals, lower the syntax cap for markdown prompt/reply
content and use plain `Text` for bodies by default, keeping syntax for code,
diff, JSON, and tracebacks.

Expected impact: attacks the largest CPU hot path (1.763s prompt-panel
render_lines plus ~1.02s content-height work).

### P1 - Use Header Summary Fields Loaded With the Agent

Move header-only fields that require I/O into the agent load/prep path or an
async detail-summary worker:

- artifact availability/list;
- parsed delta summary;
- bead display text;
- provider/model display text.

`build_header_text()` should become pure over the `Agent` plus optional cached
summary. The current `cheap=True` path proves the UI already tolerates a staged
header; make the full path staged too.

Expected impact: prevents row selection from synchronously opening artifact
indexes, resolving paths, running VCS provider detection, running git commands,
or opening bead DBs.

### P2 - Cache LLM Provider Resolution

Add process-level caching for:

- `_find_plugin_class(name)` or `_create_provider_for(name)`;
- `_llm_metadata_payload()`;
- `resolve_effective_default_provider_model()` for the top-bar indicator,
  invalidated by config token and temporary-override state mtime.

Alternatively, make `LLMOverrideIndicator` resolve the default model in a
worker and render a cheap placeholder until it completes.

Expected impact: removes the observed 0.655s UI-thread stall and reduces later
model-label lookups in `append_model_field()`.

### P2 - Keep Delta Diff Work Out of the Prompt Header

`get_agent_diff()` is appropriate for the file panel worker, but it is too
expensive for prompt-header rendering. Use one of:

- a cached diff summary populated by the file panel worker;
- a loader-computed persisted diff summary for completed agents;
- a "Deltas loading..." placeholder with an async summary update.

Expected impact: avoids `get_vcs_provider()`, entry-point scans, workspace
detection, and `diff_with_untracked()` on the UI thread during agent selection.

## Verification Strategy

Use two measurement tracks:

1. Re-run `sase ace --profile` and repeat the interaction that produced this
   trace. Success criteria: `AgentPromptPanel.render_lines` and
   `build_header_text` no longer dominate CPU samples during idle/selection.
2. Add a targeted Textual harness or `SASE_TUI_PERF=1` scenario for selecting an
   agent with artifacts, deltas, bead metadata, and a medium markdown reply.
   Track time to first cheap header paint, full detail paint, and frame gaps
   over 50-100 `j/k` movements.

Also keep the earlier startup trace work from
`sdd/research/202605/ace_startup_profile_20260502.md`; this note is about
interactive responsiveness after the TUI is open, not a replacement for
shell-to-first-use startup profiling.

## Open Questions

- Was the prompt panel expanded during most of the profile? The render hot path
  strongly suggests yes; collapsed/file-priority layout should be profiled
  separately.
- Was the selected row an agent with many explicit artifacts? The
  `read_explicit_agent_artifact_index()` branch consumed 0.107s inside the
  0.179s artifact header cost.
- Should ARTIFACTS/DELTAS live in the prompt header at all? They are useful, but
  the file panel and footer already own related interactions. Moving these to a
  separate async summary line would simplify the hot path.
