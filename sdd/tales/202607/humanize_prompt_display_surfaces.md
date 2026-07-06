---
create_time: 2026-07-06 13:31:50
status: done
---
# Plan: Show Configured PROJECT_NAME in All User-Facing Prompt Displays

## Problem

Canonical project directory keys (e.g. `gh_sase_org__sase`) still leak into user-facing prompt displays instead of the
configured `PROJECT_NAME` from the project spec (e.g. `sase`). Example (screenshot 20260706_125758): the Revive Agents
modal shows `[agent] gh_sase_org__sase` in list rows and the preview header, and the response preview renders the
recorded prompt as `#gh:gh_sase_org__sase @sdd/tales/...`.

### Root cause

Prompts are deliberately canonicalized at the launch boundary (`canonicalize_project_aliases_in_prompt` — e.g.
`src/sase/llm_provider/preprocessing.py:96`, `src/sase/ace/tui/actions/agent_workflow/_launch_body_impl.py:89`), so
every stored artifact (prompt-history entries, chat-history markdown written by
`src/sase/history/chat.py:save_chat_history`, agent prompt/response files) contains the directory key. That is correct —
the directory key is the storage identity.

Commit `285600348` established the fix philosophy ("humanize only at display boundaries; the directory key stays the
storage identity everywhere") and added the helpers, but only covered _prefill_ surfaces (ctrl+space replay, `,.`
prompt-history prefill, MRU cycling, launch toasts). The _display_ surfaces below were missed.

Two distinct gaps:

1. **Missing `project_display_name` on dismissed/revive agents.** `Agent.display_name`
   (`src/sase/ace/tui/models/agent.py:391`) already prefers `project_display_name` for project agents, but that field
   is:
   - intentionally excluded from bundle serialization (`src/sase/ace/tui/models/agent_bundle.py:26`), and
   - only attached by `_attach_project_display_names()` to the _visible_ Agents-tab list
     (`src/sase/ace/tui/actions/agents/_loading_compute.py:302`). Neither the loader's dismissed list nor any
     dismissed-bundle loader (`src/sase/ace/dismissed_agents_bundles.py`) attaches it, so revive/run-log surfaces fall
     back to the raw `cl_name`.

2. **Prompt/chat text rendered without humanization.** Several surfaces render stored prompt or chat-markdown text
   verbatim, without passing it through `humanize_vcs_refs_in_text()` (`src/sase/project_display_names.py`).

### Affected surfaces (verified, with leak sites)

| Surface                                                                    | Leak                                                                                                                                                                                                                                                                                         |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prompt-history modal (`src/sase/ace/tui/modals/prompt_history_modal.py`)   | Preview pane renders `item.entry.text` raw (`:443`); list-row project column + clean preview come from `summarize_prompt_for_list(item.entry.text)` on raw text (`_prompt_history_rows.py:127`); preview metadata `vcs_tag` raw; Ctrl+I load-to-input / Ctrl+Y copy return raw text (`:267`) |
| Revive Agents modal (`revive_agent_modal.py`, `revive_agent_rendering.py`) | Row label `agent.display_name` (`revive_agent_rendering.py:79`) and metadata header (`:128`) show raw `cl_name` (gap 1); response preview renders `get_response_content()` raw (`:193-204`); `_chat_contents` filter corpus built from raw content (`revive_agent_modal.py:121,191`)         |
| Agent Run Log modal (`agent_run_log_modal.py`)                             | AGENT XPROMPT (`:436-445`) and AGENT CHAT (`:448-460`) sections render raw content                                                                                                                                                                                                           |
| Main agent prompt panel (`widgets/prompt_panel/_agent_display_render.py`)  | AGENT XPROMPT _is_ humanized (`:122-124`), but AGENT PROMPT (`get_prompt_content`, `:137-139`) and the AGENT CHAT/response paths (`:189`, reply chunks, live reply) are not — and for ace-run agents the response file is chat markdown that embeds the `## Prompt` section                  |
| Saved-group revival modal (`saved_agent_group_revival_rendering.py`)       | `ref.prompt_preview` rendered raw (`:246-248`); `ref.display_name` (`:233`) captured at save time from a possibly display-name-less agent                                                                                                                                                    |
| CLI `sase prompt list` (`src/sase/prompt/cli_list.py:59-60,109`)           | Project ref column and preview rendered raw                                                                                                                                                                                                                                                  |

## Design

Keep the established philosophy: **storage stays canonical; humanize at display boundaries only.** No changes to launch
canonicalization, prompt-store contents, chat files, bundle files, or identity/grouping keys. The display-name map
already comes from the Rust core (`project_lifecycle_wire.project_display_name_map`); everything here is
presentation-only Python glue, so no `sase-core` changes are needed.

### Part 1 — Attach `project_display_name` to dismissed/revive agents

Create one shared, public attach helper (promote the logic of `_attach_project_display_names` out of
`_loading_compute.py`, e.g. into `src/sase/project_display_names.py` as `attach_project_display_names(agents)`), built
on the existing mtime-keyed cached map (`_project_display_name_map_cached`) instead of a fresh `list_project_records`
read per call (also a small win for the main loader). It should duck-type on `project_file`/`project_display_name`
attributes so the top-level module does not import the TUI `Agent` type.

Call it from:

- `src/sase/ace/dismissed_agents_bundles.py` — after rehydration in `load_dismissed_bundles()` and
  `load_dismissed_bundles_page()`. This covers every consumer: revive modal paging, saved-group resolution
  (`_revive_flow.py`), the snapshot cache (`_snapshot_cache.py:155`), and the run-log modal's dismissed bundles.
- `src/sase/ace/tui/actions/agents/_loading_compute.py` — attach to the loader-sourced dismissed list as well as
  `result_agents` (today only the visible list gets it), so `_dismissed_agent_objects` is covered regardless of source.

This alone fixes the revive-modal row labels, the metadata preview header, and any other `display_name` consumer (e.g.
agent-neighbor modal) for dismissed agents. `is_project_agent` and all identity/dedup keys keep using canonical
`cl_name`.

### Part 2 — Humanize prompt/chat text at the remaining display boundaries

Use `humanize_vcs_refs_in_text()` (fence-protected, VCS-tag-only rewriting, mtime-cached map, safe no-op when no display
name differs) at these call sites:

1. **Prompt-history modal**: humanize the _display_ text once per entry when building display items, and use it for:
   list-row summary input (`summarize_prompt_for_list`), preview pane, preview metadata (`summarize_prompt_for_preview`
   input), and the filter match in `_get_filtered_items` (users type what they see; keep matching the canonical text too
   so old muscle memory still works). Also return the humanized text from `_get_selected_prompt_text()` (Ctrl+I load /
   Ctrl+Y copy) — this matches the already-humanized `,.` prefill behavior, and launch re-canonicalizes on submit.
   `entry.text` itself and all store identity/dedup stays canonical: humanize into a separate per-item display field
   (the `_PromptDisplayItem`/summary cache is the natural place), never by mutating the entry.
2. **Revive Agents modal**: humanize `build_response_preview()` output (content is already truncated to 5000 chars —
   cheap) and the `_chat_contents` filter corpus so filtering matches the displayed text.
3. **Agent Run Log modal**: humanize the AGENT XPROMPT and AGENT CHAT section text (both already truncated: 50 / 200
   lines).
4. **Main agent prompt panel** (`_agent_display_render.py`): humanize the AGENT PROMPT content and the
   response/chat/reply-chunk content before handing to `_render_markdown`/`lazy_renderable`. Prefer the global
   cached-map helper over the single-key map used by `_display_raw_xprompt` (prompts can reference other projects);
   `_display_raw_xprompt` can then be simplified to the same helper.
5. **Saved-group revival modal**: humanize `ref.prompt_preview` at render, and map `ref.display_name` through
   `project_display_name_for()` (falls back unchanged for non-project names, so CL names are unaffected).
6. **CLI `sase prompt list`**: humanize the project-ref column and preview text (display only;
   `sase prompt run`/`export` keep canonical text).

### Performance notes (per `memory/tui_perf.md`)

- The display-name map lookup is already mtime-cached (one `stat()` + dict lookup); no new disk reads on any
  per-keystroke or per-paint path.
- Humanization is a single fence-protect + regex pass, O(len(text)). All modal surfaces are bounded (truncated previews)
  — negligible. The main prompt panel can render large chat files on each (debounced) detail paint, so add a small
  content-keyed memo for the panel's humanize step (e.g. a tiny LRU keyed on the text object/hash + the display-name map
  signature), mirroring the existing `LazySyntaxRenderCache` pattern. Humanize _before_ the render cache so cache keys
  are the humanized content.
- Prompt-history rows already cache their summary per item (`item.summary`); computing the summary from humanized text
  keeps that one-time-per-item property.

### Explicitly out of scope

- No changes to stored formats (prompt store, chat markdown, bundles, artifacts).
- No changes to launch-boundary canonicalization or MRU recording.
- Agent reply _prose_ is only affected insofar as it flows through the same displayed chat text; we do not attempt to
  rewrite non-VCS-tag mentions of directory keys.
- No `sase-core` (Rust) changes.

## Tests

Follow the precedents from commit `285600348` and existing modal tests:

- `tests/ace/tui/modals/test_revive_agent_modal.py`: with a project whose spec `PROJECT_NAME` differs from its directory
  key, assert row label (`format_agent_label`), metadata header (`build_metadata_preview`), and response preview
  (`build_response_preview`) all show the configured name; assert filtering matches the displayed name.
- New/extended dismissed-loader tests (`tests/test_dismissed_agent_names.py` or sibling): `load_dismissed_bundles()` /
  `load_dismissed_bundles_page()` attach `project_display_name`; bundle files on disk remain unchanged.
- `tests/ace/tui/modals/test_prompt_history_modal.py`: row project column, preview pane, filter matching, and
  Ctrl+I/Ctrl+Y text are humanized; store entries stay canonical.
- `tests/ace/tui/modals/test_agent_run_log_contracts.py`: XPROMPT/CHAT sections humanized.
- `tests/ace/tui/widgets/test_agent_display_project_names.py` / `test_agent_display_xprompt.py`: AGENT PROMPT and
  response sections humanized; existing XPROMPT behavior preserved.
- `tests/ace/tui/modals/test_saved_agent_group_revival_rendering.py`: prompt preview and display-name mapping.
- `tests/test_project_display_names.py`: new `attach_project_display_names()` helper (cached-map reuse, duck-typing,
  missing/equal-name fallback to `None`).
- CLI: extend `sase prompt list` tests for the humanized column/preview.

Run `just install` then `just check` (lint + mypy + full test suite, including PNG visual snapshots — if any golden
legitimately shows a humanized name where the raw key appeared before, regenerate intentionally with
`--sase-update-visual-snapshots`).

## Risks / edge cases

- **Ambiguous or missing display names**: `humanize_project_refs_in_prompt` already no-ops when a key has no distinct
  display name; `project_display_name_for` falls back to the input. No behavior change for projects without
  `PROJECT_NAME`.
- **Filter mismatch regressions**: filtering must match the _displayed_ text (and, in the prompt-history modal, also the
  canonical text) so nothing becomes unfindable.
- **Identity safety**: revive/dismiss/dedup logic keys on canonical `cl_name`/`raw_suffix`/bundle paths — the plan never
  feeds humanized strings into those paths; tests should include one guard asserting a revive round-trip still resolves
  the same bundle.
- **Multi-project prompts**: the global cached map humanizes every known ref in one pass, so multi-segment prompts
  referencing several projects render consistently.
