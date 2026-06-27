# TUI Freeze and Xprompt LSP Research - 2026-06-27

## Question

The TUI has been freezing frequently, sometimes for about 60 seconds, and xprompt LSP completion is not working. The goal of this research is to identify the most likely causes and recommend a fix path.

## Short Answer

These look like two related-in-time but technically separate failures:

1. The TUI has had real event-loop stalls from artifact-index work and also many stall reports from intentional terminal handoffs to an editor or viewer. Recent code already fixed the most visible apply-time artifact-index stall path, but several direct artifact-index mutation calls remain and should be moved through the same off-thread/coalesced mechanism.
2. The xprompt LSP binary and catalogs are present, but the local Neovim config sets `native_completion = false`. In the current `sase-nvim` code that makes `require("sase.lsp").complete()` return `false`, so the `<C-t>` completion path falls back to the legacy completion picker instead of using the LSP.

The 60-second shape can come from multiple places. Historical TUI logs include 55s+ event-loop recoveries, mostly around external editor/viewer handoffs and older artifact-index work. The LSP also has a possible 30s xprompt refresh plus 30s snippet refresh startup path, but direct helper checks completed in under a second, so the local Neovim config is a stronger current explanation for "the LSP is not working."

## Material Reviewed

- Required TUI performance memory: `memory/tui_perf.md`.
- Prior research:
  - `sdd/research/202606/tui_slowdown_consolidated_20260625.md`
  - `sdd/research/202606/tui_startup_freeze_consolidated_20260626.md`
  - `sdd/research/202606/tui_snippet_xprompt_auto_loading_consolidated_20260627.md`
  - `sdd/tales/202606/tui_freeze_artifact_scan.md`
- Current TUI code around agent loading, artifact-index maintenance, dismiss/revive/kill/mark persistence, and detail rendering.
- Current xprompt LSP launcher and Rust LSP cache code.
- Current `sase-nvim` LSP/completion integration and local Neovim config.
- Runtime artifacts:
  - `~/.sase/logs/tui.log`
  - `~/.sase/logs/tui_stalls.jsonl`
  - `~/.sase/perf/tui_trace.jsonl`
  - `py-spy` sample of the live `sase ace` process
  - `~/.sase/xprompt_lsp/*.json`

## TUI Findings

### Historical stalls are real, but not all are accidental freezes

`~/.sase/logs/tui.log` contains 18 recoveries of at least 55 seconds between 2026-06-20 and 2026-06-26. Examples include:

- 2026-06-20 18:02:09: 58.555s
- 2026-06-20 19:01:09: 101.645s
- 2026-06-23 08:06:22: 328.079s
- 2026-06-23 11:52:31: 65.053s
- 2026-06-25 06:26:17: 59.516s
- 2026-06-25 21:15:23: 64.528s
- 2026-06-26 10:19:10: 73.020s

`~/.sase/logs/tui_stalls.jsonl` has 58 watchdog records. Categorizing by the captured `main_thread_stack` gives:

- 35 external editor subprocess waits, max captured watchdog sample 5.482s.
- 11 artifact-index maintenance stalls on the UI thread, max captured watchdog sample 5.499s.
- 7 artifact viewer key waits, max captured watchdog sample 5.002s.
- 2 external artifact viewer subprocess waits, max captured watchdog sample 5.001s.
- 3 uncategorized selector/wait samples.

The JSON watchdog samples are threshold snapshots, so they generally show the first 5 seconds of a longer blocked interval. The human log records the full recovery duration.

This matters because the "solid 60 seconds" symptom can be at least two things:

- An intentional terminal handoff where the TUI is waiting for `$EDITOR` or a viewer subprocess to exit.
- An accidental UI-loop block from synchronous work such as artifact-index maintenance.

The first should be classified and excluded from "TUI froze" alerts where possible; the second should be fixed.

### The old apply-time artifact-index stall path is already fixed in this checkout

Several watchdog stacks point to the old path:

`_apply_loaded_agents_prepared_inner -> sync_dismissed_agent_artifact_index -> _run_active_tier_maintenance -> terminalize_stale_active_agent_artifact_index_rows`.

Current code has moved that apply-time maintenance into `AgentIndexMaintenanceMixin`:

- `src/sase/ace/tui/actions/agents/_loading_apply.py` now calls `_schedule_artifact_index_maintenance(...)` after saving dismissed-agent state.
- `src/sase/ace/tui/actions/agents/_index_maintenance.py` coalesces requests and runs `sync_dismissed_agent_artifact_index_report(...)` via `asyncio.to_thread(...)`.
- Git history shows `49986114d perf(tui): defer artifact index maintenance off the event loop`.

So the exact `_loading_apply.py` stall stack in old logs is likely fixed in the current source.

### Direct artifact-index mutation calls remain

The safer scheduler is not yet used everywhere. Current direct calls include:

- `src/sase/ace/tui/actions/agents/_revive_execution.py`
  - `sync_dismissed_agent_artifact_index(...)`
  - `upsert_agent_artifact_index_artifacts(...)`
- `src/sase/ace/tui/actions/agents/_dismissing.py`
  - `sync_dismissed_agent_artifact_index(dismissed_snapshot, added=added)`
- `src/sase/ace/tui/actions/agents/_marking.py`
  - `sync_dismissed_agent_artifact_index(dismissed_snapshot, added=added)`
- `src/sase/ace/tui/actions/agents/_kill_persistence.py`
  - `sync_dismissed_agent_artifact_index(dismissed_snapshot)`
- `src/sase/ace/tui/actions/agents/_dismiss_memory.py`
  - `sync_dismissed_agent_artifact_index(...)`
- `src/sase/ace/tui/actions/agents/_revive_archive.py`
  - `sync_dismissed_agent_artifact_index(...)`

Some of these may currently run inside worker/tracked persistence tasks, but `_revive_execution.py` is the highest-risk path because revive is a direct user action path and it performs both dismissed projection sync and artifact upsert.

### Artifact scale is large enough to make synchronous fallbacks expensive

The local artifact tree is large:

- `~/.sase/projects/sase/artifacts/ace-run` has 15,204 immediate run directories.
- `~/.sase/agent_artifact_index.sqlite` is about 157 MB.
- `~/.sase/run/sase-host/projections/projection.sqlite` is about 1.59 GB.

This is enough that scans, JSON/index reads, and conversion work can visibly compete with rendering or block the UI if routed through the event loop.

### Live sampling shows rendering pressure and artifact-index work

A 10-second `py-spy` sample of the live `sase ace` process showed substantial time in Textual/Rich rendering and artifact-index related work. Simple term counts from the raw sample included:

- `textual/_compositor`: 215 samples.
- `rich/`: 152 samples.
- `agent_artifact`: 147 samples.
- `artifact_index`: 120 samples.
- `load_agents_from_disk`: 134 samples.

Representative stacks included:

- Main thread repaint: `textual/_compositor.py -> textual/widget.py -> rich/syntax.py -> rich/text.py -> rich/cells.py:cell_len`.
- Artifact detail enrichment worker: `build_detail_header_summary -> agent_artifact_paths -> list_agent_artifacts -> read_explicit_agent_artifact_index`.
- Agent loader worker: `load_agents_from_disk_with_state -> load_tiered_agents`.

This did not catch a single 60-second block, but it does show the current steady-state pressure points: rendering, agent refresh, and artifact-index reads.

### Perf trace shows repeated broad refresh churn

`~/.sase/perf/tui_trace.jsonl` contains repeated patterns like:

- `fallback_reason: "unknown_watcher_path"`
- `data_cost: "tier1_broad_load"`
- `agents.load_from_disk` durations around 1.1s to 1.8s
- `display_fallback` with `display_cost: "display_full_rebuild"`
- `fallback_reason: "unsupported_grouping"`

These are probably not the whole 60-second freeze by themselves, but they create repeated 1-2 second jank and raise the chance that background workers, index reads, and repaint work overlap badly.

## Xprompt LSP Findings

### The LSP binary and generated catalogs exist

`sase lsp --version` succeeds:

```text
sase-xprompt-lsp 0.2.0
```

The server binary resolves to `~/.cargo/bin/sase-xprompt-lsp`.

`~/.sase/xprompt_lsp/` contains generated catalogs:

- `vcs_project_catalog.json`: 716 bytes, 3 entries.
- `model_catalog.json`: 4,100 bytes, 28 entries.

The Python launcher in `src/sase/integrations/xprompt_lsp.py` materializes these paths before `os.execvp(...)`, so startup is not failing because the wrapper cannot find the binary or because the project/model catalog files are missing.

### Helper catalog loading is not currently slow in isolation

Direct helper bridge checks with an empty request completed quickly:

- `sase mobile helper-bridge xprompt-catalog`: 0.706s, 91,660 stdout bytes.
- `sase editor helper-bridge snippet-catalog`: 0.559s, 9,703 stdout bytes.

The Rust LSP has a possible startup delay shape: `initialized()` awaits `refresh_catalog_explicit()`, which refreshes xprompts and then snippets. Each explicit refresh uses a 30-second timeout. If both helper paths hang, startup can look like roughly 60 seconds. But the direct helper timings above make this a lower-probability current cause than the Neovim config gate.

### Local Neovim config disables the manual LSP completion path

The local Neovim config has:

```lua
require("sase").setup({
  complete = {
    keymap = true,
    completion_backend = "auto",
  },
  lsp = {
    enabled = true,
    native_completion = false,
  },
})
```

In `sase-nvim`, `lua/sase/lsp.lua` implements:

```lua
function M._native_completion_enabled(native_completion, has_cmp)
  if native_completion == false then
    return false
  end
  if native_completion == true then
    return true
  end
  return not has_cmp
end
```

and `M.complete()` does:

```lua
M.start(bufnr)
if not M.is_attached(bufnr) then
  return false
end
if not native_completion_enabled() then
  return false
end
```

Then `lua/sase/complete.lua` handles `<C-t>` like this:

```lua
if config.completion_backend == "auto" and require("sase.lsp").complete() then
  return
end

legacy_trigger()
```

With `completion_backend = "auto"` and `native_completion = false`, the LSP may attach, but `require("sase.lsp").complete()` deliberately returns `false`, so `<C-t>` falls through to legacy completion. This is the clearest explanation for "xprompt LSP is not working" in the current local setup.

Headless checks matched this behavior: with `native_completion=false`, the LSP was attached but `complete=false`; with `native_completion=true`, `complete=true`.

### One smoke test appears stale, not diagnostic

The `sase-nvim` VCS project smoke test expects item detail text containing both provider and insertion text. Current Rust unit tests assert detail is just the insertion, such as `#gh:sase`. That smoke failure should be cleaned up, but it is not the likely cause of the user-visible LSP complaint.

## Working Hypothesis

There are two active problems:

1. **TUI responsiveness problem:** the largest known accidental stall source, apply-time artifact-index maintenance on the UI thread, has been fixed in the current checkout. However, remaining direct artifact-index sync/upsert calls can still block or contend with the UI in revive/dismiss/mark/kill paths. Separately, repeated broad refresh fallbacks and full display rebuilds create ongoing jank and render pressure.
2. **Xprompt LSP integration problem:** the LSP is installed and launchable, but local Neovim config disables the plugin's manual/native completion path. `completion_backend = "auto"` then silently falls back to legacy completion, making it look like LSP completion is unavailable.

The two symptoms may appear together because both are triggered during heavy SASE usage, but the evidence does not point to the xprompt LSP as the main cause of the TUI freeze.

## Recommended Solution

1. **Fix the xprompt LSP behavior first because it is low-risk and strongly evidenced.** Change the local Neovim setup to either remove `native_completion = false` or set `native_completion = true`. Then verify in an eligible xprompt markdown buffer that `require("sase.lsp").complete()` returns true and `<C-t>` uses LSP-backed completion. Longer term, update `sase-nvim` so `native_completion = false` only disables automatic/native autocompletion, not explicit manual LSP completion; `completion_backend = "lsp"` or `"auto"` should still be able to issue a manual LSP completion request.

2. **Finish deblocking artifact-index mutations in the TUI.** Route every remaining TUI-side `sync_dismissed_agent_artifact_index(...)` and `upsert_agent_artifact_index_artifacts(...)` path through an off-thread, coalesced scheduler or a tracked persistence worker. Prioritize `_revive_execution.py`, then dismiss/mark/kill/dismiss-memory/archive paths. Add watchdog tests or trace assertions proving those user actions do not call the heavy index functions on the Textual event loop.

3. **Separate intentional terminal handoffs from accidental stalls.** Wrap editor/viewer subprocess paths with explicit suspend/external-tool telemetry so 60s waits in an editor or pager are not reported as accidental TUI freezes. Keep watchdog reporting for real UI-loop blocks.

4. **Reduce ongoing refresh jank after the hard blocks are gone.** Fix `unknown_watcher_path` broad-load fallbacks and `unsupported_grouping` full display rebuilds so auto-refresh stays incremental. The trace evidence shows repeated 1.1s-1.8s loads and full rebuilds, which are likely compounding the perceived freezes even when no single blocking call lasts 60 seconds.
