---
create_time: 2026-05-15 01:06:54
status: done
prompt: sdd/prompts/202605/ace_responsiveness.md
bead_id: sase-3l
tier: epic
---
# `sase ace` Responsiveness Implementation Plan

## Context

This plan turns the findings in `sdd/research/202605/ace_profile_20260515_responsiveness.md` into an implementation
sequence. The captured profile was an interactive `sase ace --profile` run, not just startup. The main responsiveness
problems were:

- a 1.079s ChangeSpec query-corpus rebuild on the Textual event loop after the disk load had already been moved to
  `asyncio.to_thread`;
- expensive selected-agent detail refreshes, especially synchronous artifact listing, delta diff discovery, and LLM
  metadata resolution inside `build_header_text`;
- repeated Rich/Pygments markdown rendering in `AgentPromptPanel`, including layout height calculation and paint both
  re-tokenizing the same content;
- one cold LLM provider discovery hit in the top-bar indicator;
- a residual ~0.5s UI-thread apply step after agent disk loading completes.

The work should be split because each phase can be completed by a distinct agent instance (`claude`, `gemini`, `codex`,
`qwen`, `opencode`, etc.) with a clear write surface and verification gate. Phases are ordered to remove the largest
UI-thread stalls first while keeping behavioral risk manageable.

## Global Constraints

- Do not modify memory files.
- Follow `src/sase/ace/AGENTS.md`; this plan does not change keybindings, help text, or ChangeSpec suffix styling.
- Run `just install` before repo checks in a fresh `sase_<N>` workspace.
- Run focused tests for the phase, then `just check` before handing off.
- Preserve user-visible ACE behavior unless a phase explicitly stages or defers previously synchronous information. When
  information is deferred, the first paint should be useful and subsequent completion should not interrupt j/k
  navigation.
- Prefer Python/TUI changes in this repo for presentation and scheduling. Changes that alter shared backend query
  semantics belong in `../sase-core` per the Rust core boundary policy.

## Phase 1 - Low-Risk Provider Metadata Caching and Cold Indicator Deferral

### Goal

Remove provider entry-point scans from hot UI rendering paths and keep the top-bar LLM indicator from blocking
startup/first paint on a cold provider scan.

### Primary Files

- `src/sase/llm_provider/registry.py`
- `src/sase/ace/tui/widgets/llm_override_indicator.py`
- `tests/test_llm_override_indicator.py`
- Add/extend tests under `tests/test_llm_provider_registry.py` or a nearby existing registry test module if present.

### Work

1. Add process-lifetime memoization to `_llm_metadata_payload()`, matching the existing `_build_llm_pm()` pattern.
2. Provide an explicit cache-clear helper or document/use `_llm_metadata_payload.cache_clear()` so tests that
   monkeypatch entry points can reset both `_build_llm_pm` and metadata payload caches.
3. Ensure `model_to_provider_map()`, `provider_short_name_map()`, `model_short_alias_map()`,
   `provider_cli_status_color_map()`, `_provider_names()`, and `get_default_provider_name()` all continue to use the
   cached payload.
4. Change `LLMOverrideIndicator` so `__init__` and `on_mount()` do not perform cold default-provider resolution
   synchronously when no active override exists. Render a placeholder/fallback first, schedule a background task or
   Textual worker to resolve `resolve_effective_default_provider_model()`, then update the widget when the result
   returns.
5. Preserve immediate rendering for active temporary overrides, because that path is cheap and time-sensitive.

### Acceptance Criteria

- Repeated `append_model_field()` calls no longer call `importlib.metadata.entry_points(group="sase_llm")` after the
  first payload fill.
- Instantiating/mounting `LLMOverrideIndicator` does not call `resolve_effective_default_provider_model()` synchronously
  when no active override is present.
- Existing override display behavior and expiry cleanup behavior remain intact.

### Suggested Tests

- Registry unit test: monkeypatch `_direct_llm_metadata_payload()` or entry points, call `model_to_provider_map()`
  multiple times, assert the expensive payload build happens once until cache clear.
- Indicator unit test: monkeypatch default resolver to raise if called during `__init__`; assert placeholder content is
  rendered and the async resolver path updates content.
- Run:
  - `just install`
  - `uv run pytest tests/test_llm_override_indicator.py`
  - `uv run pytest <new-or-existing-registry-tests>`
  - `just check`

## Phase 2 - Move ChangeSpec Query Corpus Build Off the UI Thread

### Goal

Remove the 1.079s `compile_query_corpus()` continuation from the Textual event loop during ChangeSpec reloads.

### Primary Files

- `src/sase/ace/tui/actions/changespec/_loading.py`
- `src/sase/core/query_corpus_facade.py` if a small helper is useful
- `tests/ace/tui/test_changespec_query_corpus_routing.py`
- Any async ChangeSpec reload tests under `tests/ace/tui/`

### Work

1. Introduce a small prepared-load structure for ChangeSpecs, for example:
   `PreparedChangeSpecLoad(all_changespecs: list[ChangeSpec], query_corpus: QueryCorpus | None)`.
2. In `_reload_and_reposition_async()`, run both `find_all_changespecs_cached()` and
   `compile_query_corpus(all_changespecs)` inside the same `asyncio.to_thread` worker.
3. Apply the prepared corpus on the UI thread before calling `_filter_changespecs()` so
   `_get_query_corpus_for_changespecs()` hits the id-based cache for the freshly loaded list.
4. Preserve the synchronous `_reload_and_reposition()` and `_load_changespecs()` paths, either by compiling
   synchronously there or by routing through a shared helper. These paths are less important, but tests should still see
   correct cache state.
5. Keep validation strict: corpus source list id and expected length must match the list being filtered.
6. Do not attempt the deeper Rust wire-layer optimization in this phase. It is a later backend phase if profiling still
   shows serialization cost matters after moving it off the event loop.

### Acceptance Criteria

- `_reload_and_reposition_async()` does not call `compile_query_corpus()` on the event loop after the `await`.
- The first filter after async reload reuses the worker-built corpus.
- Saved-query fallback and hide-submitted/hide-reverted behavior continue to work.

### Suggested Tests

- Add an async test that monkeypatches `asyncio.to_thread` or `compile_query_corpus()` to record that corpus compilation
  happens inside the worker function, not during `_apply_reloaded_changespecs()`.
- Extend `test_reload_replaces_corpus_for_new_list_identity` to cover the prepared async path.
- Run:
  - `just install`
  - `uv run pytest tests/ace/tui/test_changespec_query_corpus_routing.py`
  - Relevant async ChangeSpec reload tests found with `rg "_reload_and_reposition_async|changespec" tests/ace/tui`
  - `just check`

## Phase 3 - Make Agent Detail Header Pure or Cached

### Goal

Stop ordinary j/k navigation and artifact-discovery completion from doing synchronous artifact listing, VCS diff
discovery, bead description lookup, or provider metadata work inside `build_header_text()`.

### Primary Files

- `src/sase/ace/tui/actions/agents/_panel_artifacts.py`
- `src/sase/ace/tui/actions/agents/_display_detail.py`
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`
- `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py`
- `src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py`
- `src/sase/ace/tui/widgets/prompt_panel/_helpers.py`
- `src/sase/ace/tui/models/agent_bead.py` if bead display needs a cheap summary
- Tests under:
  - `tests/ace/tui/actions/test_agent_artifact_async_discovery.py`
  - `tests/ace/tui/widgets/test_agent_display_header_only.py`
  - `tests/ace/tui/widgets/test_prompt_panel_persisted_artifacts.py`

### Work

1. Remove `_fire_debounced_detail_update()` from `_run_agent_artifact_discovery()` completion unless the completion can
   update the currently visible header using already cached data without disk I/O. At minimum, completion should update
   only the artifact cache and footer binding state.
2. Add a `DetailHeaderSummary` or similar data object containing optional, precomputed/cached values for:
   - artifact path display entries;
   - delta entries or a delta summary;
   - bead display text when description lookup is expensive;
   - resolved provider/model display text if not already cheap after Phase 1.
3. Change `build_header_text()` so the full render path consumes the optional summary and never falls back to disk, VCS
   provider resolution, or artifact listing on the UI thread during row selection.
4. Keep `update_header_only(... cheap=True)` disk-free. Its tests should remain the guardrail.
5. Decide the staged UX:
   - preferred: render cheap header immediately, then append cached ARTIFACTS/DELTAS when the summary worker finishes
     for the same selected agent;
   - acceptable first implementation: omit ARTIFACTS/DELTAS from the prompt header and rely on the footer/artifact
     viewer plus file panel.
6. Ensure stale worker results are discarded when the selected agent changes.

### Acceptance Criteria

- Full detail update for selection does not call `list_agent_artifacts()` or `get_agent_diff()` synchronously on the UI
  thread.
- Artifact discovery completion does not trigger a full prompt body/header rebuild just because cache population
  finished.
- Footer artifact availability still becomes correct after background discovery.
- Existing ARTIFACTS display tests are either preserved through cached summary inputs or intentionally updated if the
  header no longer owns that section.

### Suggested Tests

- Update artifact async discovery test: completion populates cache but does not call full detail refresh; add a separate
  assertion for footer/binding refresh if implemented.
- Add prompt header tests that monkeypatch `list_agent_artifacts()` and `get_agent_diff()` to raise during
  `AgentPromptPanel.update_display()` unless a precomputed summary is supplied.
- Add stale-selection test for async summary completion.
- Run:
  - `just install`
  - `uv run pytest tests/ace/tui/actions/test_agent_artifact_async_discovery.py`
  - `uv run pytest tests/ace/tui/widgets/test_agent_display_header_only.py tests/ace/tui/widgets/test_prompt_panel_persisted_artifacts.py`
  - `just check`

## Phase 4 - Cache or Cap Prompt Body Syntax Rendering

### Goal

Cut repeated markdown tokenization in `AgentPromptPanel` and prevent Textual height calculation plus paint from redoing
the same Pygments work for medium prompt/reply bodies.

### Primary Files

- `src/sase/ace/tui/util/lazy_syntax.py`
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`
- `tests/ace/tui/util/test_lazy_syntax.py`
- Prompt-panel rendering tests under `tests/ace/tui/widgets/`

### Work

1. Add markdown-specific syntax caps lower than the global caps used by diffs and source files. Keep the current 64 KiB
   / 1,500 line defaults for diff and source code unless tests show they should change.
2. Add an opt-in renderable cache for prompt-panel markdown content. The first implementation can be conservative:
   - key by content hash or object identity plus lexer, theme, word-wrap, line range, line numbers, and width;
   - bound the cache size and clear it on selected-agent/content changes;
   - fall back to plain `Text` on oversized markdown.
3. Prefer a local prompt-panel cache over a global Rich monkeypatch. If the renderable wrapper becomes too invasive,
   ship the markdown cap first and leave the wrapper as Phase 4B.
4. Keep visual behavior stable for small markdown prompts and for syntax-highlighted diffs/source snippets.

### Acceptance Criteria

- Medium and large markdown prompt/reply content no longer repeatedly invokes Pygments during both `get_content_height`
  and `render_lines`.
- Oversized prompt markdown renders as plain text with the existing large-output notice style.
- Existing file-panel and diff highlighting behavior is unchanged.

### Suggested Tests

- Extend `tests/ace/tui/util/test_lazy_syntax.py` with markdown-specific caps.
- Add a cache test using a fake renderable/lexer hook to assert repeated render/measure calls reuse the prepared result
  for the same content and width.
- Run:
  - `just install`
  - `uv run pytest tests/ace/tui/util/test_lazy_syntax.py`
  - Relevant prompt panel tests found with
    `rg "AgentPromptPanel|lazy_renderable" tests/ace/tui/widgets tests/test_ace_tui_widgets.py`
  - `just test-visual` if rendered prompt output changes
  - `just check`

## Phase 5 - Reduce Agent List Post-Load Apply Hitch

### Goal

Reduce the residual ~0.5s UI-thread stall after agent disk load completes, without destabilizing selection restoration,
grouping, fold state, unread state, or multi-panel display.

### Primary Files

- `src/sase/ace/tui/actions/agents/_loading_apply.py`
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
- `src/sase/ace/tui/actions/agents/_display.py`
- `src/sase/ace/tui/widgets/agent_list.py`
- `src/sase/ace/tui/widgets/_agent_list_build.py`
- `src/sase/ace/tui/widgets/_agent_list_rendering.py`
- Agent list tests under `tests/ace/tui/widgets/`
- Agent panel/display tests under `tests/ace/tui/`

### Work

1. Measure which part of the current apply path remains hot after Phases 1-4. Do not prematurely rewrite `AgentList` if
   the previous phases remove the user-visible hitch.
2. If still needed, introduce a prepared row data path:
   - compute pure row formatting (`Text`, suffixes, option ids, widths, row maps) outside the UI critical section where
     safe;
   - keep Textual widget mutation (`clear_options`, `add_option`, highlight, message posting) on the UI thread.
3. Alternatively, chunk full list install with `call_after_refresh()` so large lists do not monopolize a frame.
4. Preserve the existing fast paths:
   - `patch_row()` for single-row updates;
   - `try_remove_rows()` for kill/dismiss;
   - detail-only refreshes that avoid `update_list()`.

### Acceptance Criteria

- First agent-load apply no longer blocks the event loop for hundreds of milliseconds on representative projects.
- Selection, grouping banners, row lookup maps, jump hints, unread markers, and panel widths remain correct.
- Existing fast-path tests still prove `update_list()` is skipped when it should be skipped.

### Suggested Tests

- Existing agent list suites:
  - `uv run pytest tests/ace/tui/widgets/test_agent_list_*.py`
  - `uv run pytest tests/ace/tui/test_agent_panels_display.py tests/ace/tui/test_agent_detail_two_phase.py`
- Add a unit test for any new prepared-row builder that verifies row maps and widths match the current `build_list()`
  output.
- Run:
  - `just install`
  - focused tests above
  - `just check`

## Phase 6 - Verification, Profiling, and Optional Backend Serialization Follow-Up

### Goal

Validate the combined impact with real ACE profile runs and decide whether a deeper Rust/wire optimization is warranted.

### Primary Files

- `sdd/research/202605/ace_profile_20260515_responsiveness.md` only if updating research with new measurements
- `tests/perf/bench_core_query.py`
- `tests/perf/baselines/` if baseline updates are intentional
- Potential backend repo: `../sase-core/crates/sase_core` only if the data says wire serialization remains a meaningful
  bottleneck

### Work

1. Re-run `sase ace --profile` with a repeatable selection sequence that includes:
   - ChangeSpec reload/filter;
   - j/k over agents with medium markdown prompt/reply;
   - agent with artifacts;
   - agent with deltas;
   - first top-bar LLM indicator render.
2. Compare the new profile against the May 15 profile. Success means `compile_query_corpus`, `build_header_text`, and
   `AgentPromptPanel.render_lines` no longer dominate UI-thread CPU during the same interaction.
3. Run or update the core query benchmark if ChangeSpec serialization remains expensive enough to justify a backend API
   change.
4. Only if needed, plan a separate Rust-core phase to reduce `dataclasses.asdict()`/wire dict allocation. That phase
   should update `../sase-core`, Python bindings, and Python callers together.

### Acceptance Criteria

- A new profile shows no single repeated UI-thread continuation above roughly 100ms for ordinary navigation/reload
  flows, or any remaining larger cost is documented with a next-step plan.
- `just check` passes in the final workspace.
- Any research update includes the exact profile command, timestamp, and high-level before/after comparison.

## Recommended Agent Assignment Order

1. Agent A: Phase 1. Low risk, independent, unlocks cheaper header rendering.
2. Agent B: Phase 2. High impact and mostly isolated to ChangeSpec loading.
3. Agent C: Phase 3. Largest behavioral design surface; should start after Phase 1 so provider metadata is already
   cheap.
4. Agent D: Phase 4. Mostly independent from Phase 3, but easier to verify once header I/O no longer dominates profiles.
5. Agent E: Phase 5. Should wait for earlier phases and remeasure first.
6. Agent F: Phase 6. Final integration/profile pass; may create a separate backend plan if serialization still matters.

## Cross-Phase Risks

- Detail-header staging can make ARTIFACTS/DELTAS appear later than before. Keep the initial header useful and make
  stale-result guards strict.
- Rich/Textual renderable caching can accidentally cache width-dependent output. Include width and render options in
  keys, or scope the cache to plain content caps first.
- ChangeSpec corpus handles are tied to list identity. Any prepared corpus must be installed with the exact list object
  it was compiled from.
- Agent list row preparation must not mutate Textual widgets off the UI thread. Keep widget calls on the event loop.
- Tests that monkeypatch provider entry points must clear both provider-manager and metadata caches.
