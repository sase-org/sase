# GPT-5.5 DEEP RESEARCH

---

# Question 1
I'm dealing with performance issues with sase's TUI. Namely, user interaction (e.g. keymaps) is often blocked and the user needs to wait a few seconds for the `j`/`k` keys to trigger navigation, for example. Can you do some research to help me decide on the best way to debug this issue? Ideally, it would be great if an agent could actively inspect a running `sase ace` process and tell me why things are running slow in realtime.

---

# Answer 1

## Bottom line

I would debug this as **Textual event-loop starvation**, not as a generic “TUI is slow” problem. The most useful setup is a hybrid:

1. **Use SASE’s built-in semantic tracing first** (`SASE_TUI_TRACE=1 SASE_TUI_PERF=1`) to identify which SASE span is blocking `j`/`k`.
2. **Attach a sampler to the live PID** (`py-spy dump/top/record` or `austin -w`) when the UI is frozen, to see the actual Python stack.
3. **Add a small in-process “stall monitor”** that dumps stacks automatically when the event loop is delayed beyond a threshold. That is the missing piece that would let an agent inspect a running `sase ace` process and explain the slowdown in realtime.

There is already a very relevant SASE tale: `diagnose_slow_tui.md` says the likely regression was synchronous disk I/O on the Textual event loop during Agents-tab navigation. Specifically, it points to `AgentToolsPanel._update_display_impl` calling an mtime probe that walks sibling artifact directories, opens/parses `agent_meta.json` and `done.json`, and stats `tool_calls.jsonl` on every navigation refresh; Claude tool-call hooks then keep mutating those files, causing repeated invalidation while agents are active. 

Current `master` appears to have the intended mitigation: `tools_panel.py` now paints from the cache immediately, enforces a `_MIN_REREAD_INTERVAL_S = 0.5`, and runs the freshness/read task via `self.run_worker(fetch_task, thread=True)` rather than doing the mtime walk synchronously in `_update_display_impl`.  The background path also uses `discover_related_tool_artifact_dirs_cached`, and `reader.py` reuses previously discovered directories when the parent directory mtime has not changed.  

So the first decision point is: **are you seeing this on a checkout that includes that tools-panel fix?** If not, pull/port that fix. If yes, the next step is to run traces and find the next blocking span.

## Immediate workflow

Run:

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace
```

Then reproduce the problem: go to the Agents tab, keep active agents running if that is when the problem occurs, press `j`/`k` 20–50 times, and quit.

SASE’s perf runbook says `SASE_TUI_TRACE=1` writes span records to `~/.sase/perf/tui_trace.jsonl`; `SASE_TUI_PERF=1` writes key-to-paint samples to `~/.sase/perf/tui_jk.jsonl`. The runbook also gives target thresholds: `j/k` highlight p95 below 16 ms and key-to-paint p95 below 33 ms.  The `JKPerfTimer` records `t_keypress`, `t_model_updated`, and `t_painted`, then emits `model_ms` and `paint_ms` for each `j`/`k` action. 

Useful quick inspection:

```bash
jq -r '
  select(.span) |
  [.duration_ms, .span, (.current_tab // ""), (.current_idx // "")] |
  @tsv
' ~/.sase/perf/tui_trace.jsonl \
| sort -nr \
| head -40
```

And for key latency:

```bash
jq -r '
  [.paint_ms, .model_ms, .action, .tab] | @tsv
' ~/.sase/perf/tui_jk.jsonl \
| sort -nr \
| head -40
```

Interpretation:

```text
paint_ms high, model_ms low
=> model changed quickly, but render/refresh or queued UI work was slow.

model_ms high
=> action handler / navigation / state mutation path is blocked.

slow span is widget.tools_panel.update_display
=> likely artifact/tool-call read path.

slow span is widget.agent_list.update_highlight or agents.refresh_panel_highlights
=> list navigation / grouping / row patching.

slow span is agents.load_from_disk
=> loader or filesystem scan.

slow spans appear every second
=> inspect _on_countdown_tick / runtime-row patching.
```

The 1 Hz tick is worth keeping in the suspicion set because `_on_countdown_tick` updates info panels and, on the Agents tab, calls `_patch_agent_runtime_rows()`. 

## Live attach options

For the “agent inspects a running process” goal, `py-spy` is the best first external tool. It can take a PID, does not require restarting or modifying the program, has `record`, `top`, and `dump`, and `dump --pid` prints current call stacks for Python threads; the project notes that attaching to an existing Linux process often needs `sudo` or ptrace permissions. ([GitHub][1])

```bash
PID=<pid from the TUI title or pgrep>

# One-shot: what is it doing right now?
sudo py-spy dump --pid "$PID" --locals --idle

# Live top-like view.
sudo py-spy top --pid "$PID" --idle --gil

# Capture 20 seconds around the freeze.
sudo py-spy record \
  --pid "$PID" \
  --duration 20 \
  --format speedscope \
  --output /tmp/sase-ace.speedscope.json \
  --idle
```

Austin is also a good fit for “where is this Python process right now?” Its `-w/--where` mode dumps stacks for all threads in a PID, and its docs describe PID attach mode plus the need for `CAP_SYS_PTRACE`/`sudo` on Linux. ([GitHub][2])

```bash
sudo austin -w "$PID"
sudo austin -p "$PID" -x 10 -o /tmp/sase-ace.austin
```

Use `py-spy` first because it is easier to read interactively. Use Austin if you want very lightweight repeated stack snapshots or if it behaves better on a particular host.

`pyinstrument` is still useful, but I would not make it the live-inspection tool. Its docs show launching a script/CLI under `pyinstrument` or adding API instrumentation to a code block, and it is excellent for wall-clock/async profiling, but that is a planned-run workflow rather than “attach to an already frozen TUI.” ([PyInstrument][3])

## Make it agent-friendly

The external tools alone are not enough for a helpful agent, because `py-spy` can tell you “the stack is in `Path.stat()` / JSON parsing / Textual refresh,” but it does not know which `j`/`k` event or SASE span caused it. The SASE trace knows the semantic span, but not necessarily the stack at the moment of a freeze. Combine them.

I would add a command shaped like:

```bash
sase ace doctor --pid <PID> --watch
```

It should read:

```text
~/.sase/perf/tui_trace.jsonl
~/.sase/perf/tui_jk.jsonl
periodic py-spy dump or Austin where output
optional event-loop stall stack dumps
```

And report something like:

```text
Last 30s:
  j/k paint p95: 1840 ms
  worst key: next, agents tab, paint_ms=3122 ms, model_ms=11 ms

Slowest spans:
  widget.tools_panel.update_display  p95=920 ms max=2800 ms
  agents.refresh_panel_widgets       p95=1050 ms max=3100 ms

Current stack during stall:
  AgentToolsPanel._fetch_tools_in_background
  read_tool_calls_for_agent
  discover_related_tool_artifact_dirs
  Path.iterdir / json.load / stat

Likely cause:
  tool-call artifact discovery/read path is starving the UI refresh path.
```

Current `master` already puts the TUI PID in the title with `self.title = f"sase ace (PID: {os.getpid()})"`, which makes this workflow much easier when multiple ACE windows are open. 

## Add an event-loop stall monitor

For realtime diagnosis, I would add one more SASE-native debug mode:

```bash
SASE_TUI_STALL_TRACE=1 sase ace
```

Behavior:

```text
Every 100 ms:
  check how late the next scheduled callback is.

If lag > 250 ms:
  emit trace_event("event_loop.stall", lag_ms=...)
  dump all Python thread stacks to ~/.sase/perf/tui_stacks/<pid>-<timestamp>.txt
  optionally run/record a short py-spy sample if available
```

This is directly aligned with Python’s asyncio guidance: debug mode logs callbacks taking longer than 100 ms, and blocking CPU-bound code should not run directly on the event loop because it delays other tasks and I/O. ([Python documentation][4]) Python’s `faulthandler` can dump tracebacks for all threads explicitly, after a timeout, or on a user signal; `faulthandler.register(signum, all_threads=True)` is a good low-level mechanism for “dump stacks now” on Unix-like systems. ([Python documentation][5])

Textual’s own worker docs support the architectural direction: background work should be moved into workers so input remains responsive; for blocking/non-async APIs, Textual supports thread workers via `thread=True`, but UI updates from worker threads must go back through main-thread mechanisms like `call_from_thread`. ([Textual Documentation][6])

## Decision matrix

| Option                             | Best use                        | Pros                                                   | Cons                                                                |
| ---------------------------------- | ------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------- |
| `SASE_TUI_TRACE` + `SASE_TUI_PERF` | First-line diagnosis            | Semantic SASE spans, key-to-paint timing, low friction | Only shows instrumented spans                                       |
| `py-spy dump/top/record`           | Live attach to frozen process   | No code changes; easy stack/flamegraph output          | Needs ptrace/sudo in many setups; stack lacks SASE semantic context |
| Austin `-w` / `-p`                 | Lightweight stack snapshots     | Good “where is it now?” mode                           | Less turnkey than py-spy for most people                            |
| Pyinstrument                       | Planned reproduction run        | Wall-clock and async-aware profiling                   | Not ideal for already-running process inspection                    |
| New SASE stall monitor             | Best long-term agent input      | Correlates event-loop lag, SASE spans, and stacks      | Requires a small code change                                        |
| `sase ace doctor --watch`          | Agent-facing realtime diagnosis | Can summarize cause, not just data                     | Depends on trace/stall monitor and optional profiler availability   |

## My recommended path

First, verify whether your checkout includes the current tools-panel changes that moved freshness checks and reads into a thread worker. If not, port that fix.

Then run `SASE_TUI_TRACE=1 SASE_TUI_PERF=1` and sort by slowest spans. If the slow span is still `widget.tools_panel.update_display`, inspect whether the worker result handling or cache invalidation is still causing UI-thread work. If the slow span moved, follow the trace.

For the “agent actively inspects the running process” goal, build `sase ace doctor --watch` around three data streams: SASE trace JSONL, key-to-paint JSONL, and stack snapshots triggered by event-loop stalls. That gives the agent enough evidence to say “`j` was received, model update was fast, paint was delayed 2.8 s, the event loop was in X stack, and the slow SASE span was Y,” which is much more actionable than a raw profiler alone.

[1]: https://github.com/benfred/py-spy "GitHub - benfred/py-spy: Sampling profiler for Python programs · GitHub"
[2]: https://github.com/P403n1x87/austin "GitHub - P403n1x87/austin: Python frame stack sampler for CPython · GitHub"
[3]: https://pyinstrument.readthedocs.io/en/latest/guide.html "User guide - pyinstrument 5.1.2 documentation"
[4]: https://docs.python.org/3/library/asyncio-dev.html "Developing with asyncio — Python 3.14.5 documentation"
[5]: https://docs.python.org/3/library/faulthandler.html "faulthandler — Dump the Python traceback — Python 3.14.5 documentation"
[6]: https://textual.textualize.io/guide/workers/ "Workers - Textual"

---

# Question 2

Here is the output of that `jq` command you recommended. How can I speed up the way agents are loaded from disk? I think we are reading WAY too much from disk. The TUI only needs to know about agents that are running or done but not yet dismissed. If we are smart about how we manage data on disk, this should be very fast. Can you help me reason about the best solution for this?

```
❯ jq -r '
  select(.span) |
  [.duration_ms, .span, (.current_tab // ""), (.current_idx // "")] |
  @tsv
' ~/.sase/perf/tui_trace.jsonl \
| sort -nr \
| head -40
3616.0459800157696 agents.load_from_disk 7
3528.6993379704654 agents.load_from_disk
3432.762473996263 agents.load_from_disk 4
3428.7517740158364 agents.load_from_disk 4
3424.5089050382376 agents.load_from_disk 7
3420.6507820053957 agents.load_from_disk 4
3403.3513279864565 agents.load_from_disk 4
3378.8479390204884 agents.load_from_disk 4
3356.006747984793 agents.load_from_disk 4
3351.96720197564 agents.load_from_disk 7
3351.4500409946777 agents.load_from_disk 4
3350.5836579715833 agents.load_from_disk 4
3322.227079013828 agents.load_from_disk 4
3313.512072956655 agents.load_from_disk 6
3311.9911960093305 agents.load_from_disk 4
3299.6564820059575 agents.load_from_disk 4
3295.0111610116437 agents.load_from_disk 4
3291.907520033419 agents.load_from_disk 4
3288.727098959498 agents.load_from_disk 7
3282.597318000626 agents.load_from_disk 7
3280.328291992191 agents.load_from_disk 4
3273.8414970226586 agents.load_from_disk 4
3245.7457309938036 agents.load_from_disk 4
3245.1429709908552 agents.load_from_disk 4
3240.0790710235015 agents.load_from_disk 4
3237.825416959822 agents.load_from_disk 4
3237.4317279900424 agents.load_from_disk 4
3226.691312971525 agents.load_from_disk
3226.6623670002446 agents.load_from_disk 4
3225.474439037498 agents.load_from_disk 7
3225.383242999669 agents.load_from_disk 6
3208.8050640304573 agents.load_from_disk 7
3205.7476460468024 agents.load_from_disk 4
3201.381171005778 agents.load_from_disk 4
3188.804697012529 agents.load_from_disk 4
3178.830632008612 agents.load_from_disk 4
3173.727404035162 agents.load_from_disk 4
3168.292101996485 agents.load_from_disk 4
3152.5643300265074 agents.load_from_disk 4
3146.820725989528 agents.load_from_disk 4
```

---

# Answer 2

Yes. Your intuition is right: this should be designed as an **“active/visible agent inbox”** read, not as a repeated historical artifact-tree scan.

Your trace shows `agents.load_from_disk` taking ~3.1–3.6 seconds over and over. That means the remaining problem is not `j`/`k` itself; it is that refreshes are repeatedly doing too much loader work. The current loader goes through `load_agents_from_disk_with_state()`, then `load_tiered_agents()`, then applies tags, attempt history, and retry state across loaded agents. 

## The core issue

The current “tier 1” path is close to the right idea, but it is still not the right abstraction.

Today, the TUI loader tries to load:

```text
active agents
+ recent completed agents
+ ChangeSpec-derived agents
+ workflow rows / workflow steps
+ home running markers
+ done markers
+ retry / attempt / tag metadata
```

The artifact snapshot path already has a persistent SQLite index hook: when `~/.sase/agent_artifact_index.sqlite` exists, the loader queries it for active rows plus a bounded window of recent completed rows. If the index is missing or invalid, it falls back to a bounded source scan. 

The dangerous detail is that the fallback scan is bounded only in completed records returned/parsing, not in directory discovery. The Rust scanner first collects artifact candidates from the whole `~/.sase/projects/*/artifacts/<workflow>/<timestamp>/` tree, sorts them, and only then applies `max_records` while parsing. So a large historical artifact tree can still cost seconds even if only ~200 completed records are returned. 

The better target is:

```text
TUI Agents tab load = O(number of visible rows)
not O(number of historical artifact directories)
```

## Best solution: a materialized “agent inbox” index

Use the existing `agent_artifact_index.sqlite` idea, but make it the actual source for the Agents tab fast path and extend it to model visibility.

The TUI’s default read should be:

```sql
SELECT record_json
FROM agent_artifacts
WHERE
  hidden = 0
  AND (
    active = 1
    OR (done = 1 AND dismissed = 0)
    OR needs_attention = 1
  )
ORDER BY sort_key DESC;
```

In words:

```text
show agents that are running / waiting / starting / retrying / plan-question-visible
plus completed agents that have not been dismissed
do not read dismissed completed history
do not read arbitrary old archive rows
```

The existing Rust index already stores one row per artifact directory with denormalized columns plus canonical `record_json`, and it has query functions for active and recent-completed rows.  The missing piece is that “recent completed” is the wrong proxy for “visible completed.” It can include dismissed rows that you immediately throw away, and it can exclude an old completed row that is still not dismissed.

So I would change the model from:

```text
active + recent completed limit 200, then filter dismissed in Python
```

to:

```text
active + not-dismissed completed, filtered inside the index query
```

## Why this is better than just optimizing the scanner

Optimizing the source scan helps, but it is the wrong primary path. A source scan answers:

```text
What exists in the entire artifact filesystem?
```

The TUI normally needs:

```text
What rows should I display right now?
```

Those are different questions. The first is archival/reconciliation work. The second should be a tiny indexed query.

The source artifact tree should remain the source of truth, but it should be used for:

```text
initial/recovery rebuild
periodic verification
revive/archive search
debugging
repair after missed events
```

It should not be used on every Agents-tab refresh.

## Concrete design

Keep full agent artifacts where they are, but maintain a small materialized projection:

```text
~/.sase/agent_artifact_index.sqlite
```

Add or ensure columns like:

```text
identity_type
cl_name
raw_suffix
artifact_dir
project_name
workflow_dir_name
timestamp
status
active
done
dismissed
hidden
needs_attention
pid
started_at
finished_at
last_marker_mtime_ns
record_json
```

You already have much of this in the Rust index table: `artifact_dir`, `project_name`, `workflow_dir_name`, `timestamp`, `status`, `agent_type`, `cl_name`, `has_done_marker`, `has_running_marker`, `has_waiting_marker`, `has_workflow_state`, `workflow_status`, `hidden`, and `record_json`. 

The key additions are:

```text
dismissed / dismissed_at
needs_attention
possibly unread/manual-unread state
```

Then update this row incrementally whenever the agent lifecycle changes:

```text
agent launch        -> upsert active row
running.json write  -> upsert active row
waiting.json write  -> upsert waiting row
pending question    -> upsert needs_attention row
done.json write     -> upsert completed row
dismiss             -> mark dismissed or delete from visible projection
revive              -> clear dismissed + upsert/restored row
cleanup/delete      -> delete index row
```

The TUI read becomes a cheap SQLite query plus hydration of a small list of rows.

## The current fallback should not be the normal fallback

Right now, if the index is missing, `_artifact_snapshot_for_tui_load()` falls back to a source scan.  That is fine for tests or one-shot CLIs, but it is bad for an interactive TUI with a huge historical artifact tree.

For `sase ace`, I would make the behavior stricter:

```text
If index exists:
  query it.

If index missing:
  show empty/cached/loading state immediately.
  schedule index rebuild in a worker/daemon.
  do not repeatedly source-scan the whole artifact tree from the TUI.

If index stale:
  use stale index for first paint.
  schedule background repair.
  surface “agent index rebuilding…” somewhere subtle.
```

This gives you responsiveness even during recovery.

## Important hidden culprit: search forces full history

One thing I would check immediately: whether you have an Agents-tab search query active.

In `_load_agents_async()`, the call passes:

```python
full_history=full_history or bool(getattr(self, "_agent_search_query", ""))
```

That means any non-empty agent search query forces the full-history path.  If a search query is left active, every refresh can become an archive-scale load.

I would change this behavior:

```text
Normal search:
  search only the current visible/inbox working set.

Explicit archive search:
  user opts into “search all historical/dismissed agents”.
  run asynchronously from the index/archive.
```

Do not let a normal filter box turn every auto-refresh into a full historical scan.

## Another likely over-read: attempt history

The loader currently populates `attempt_history` for every loaded agent with an artifacts directory. The snapshot cache avoids reparsing unchanged `attempt_meta.json`, but it still has to list/stat attempt metadata for each agent to build signatures. 

For a fast Agents tab, attempt history should be lazy:

```text
List row load:
  status, name, model, timestamps, workspace, visible flags.

Selected detail panel:
  load attempt history for the selected agent only.

Expanded workflow/attempt view:
  load children/attempts on demand or from pre-indexed summaries.
```

That keeps the list refresh cheap.

## What I would implement first

### 1. Add better trace counters

Right now your trace says only:

```text
agents.load_from_disk 3200ms
```

Add enough fields to identify the path:

```text
tier
artifact_source
used_artifact_index
index_error
full_history
agent_search_active
snapshot_records
projects_visited
artifact_dirs_visited
marker_files_parsed
prompt_step_markers_parsed
loaded_agents
dismissed_from_loader
```

The Rust scan already returns stats like `projects_visited`, `artifact_dirs_visited`, `marker_files_parsed`, and `prompt_step_markers_parsed`.  This will quickly tell you whether the 3.5 seconds is index fallback, full-history mode, ChangeSpec loading, attempt-history statting, or something else.

### 2. Verify whether the index exists and is being used

Run:

```bash
ls -lh ~/.sase/agent_artifact_index.sqlite
```

Then:

```bash
python - <<'PY'
from pathlib import Path
from time import perf_counter

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)

index = default_agent_artifact_index_path()
projects = Path.home() / ".sase" / "projects"
print("index:", index)
print("exists:", index.is_file())
if index.is_file():
    t0 = perf_counter()
    snapshot = query_agent_artifact_index(
        index,
        projects,
        query=AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=True,
            include_full_history=False,
            recent_completed_limit=200,
            include_hidden=False,
        ),
        options=AgentArtifactScanOptionsWire(
            include_prompt_step_markers=True,
            include_raw_prompt_snippets=False,
        ),
    )
    dt = (perf_counter() - t0) * 1000
    print("query_ms:", round(dt, 2))
    print("records:", len(snapshot.records))
    print("stats:", snapshot.stats)
PY
```

If that query is fast, the TUI is probably not using the index, is forcing `full_history`, or is spending time after the index query. If it is slow, inspect SQLite locking or row size.

### 3. Make the index query visibility-aware

Add a dismissed/visible state to the index. Do not load recent completed and then discard dismissed rows in Python.

Target behavior:

```text
TUI default query returns:
  all active rows
  all completed-but-not-dismissed rows
  all attention rows
  no dismissed archive rows
```

The current loader computes `dismissed_from_loader` after loading all agents, excluding running aliases from dismissed matching.  Preserve that safety rule, but push the completed-row visibility decision into the index.

### 4. Stop full-history loads from normal auto-refresh

Reserve `full_history=True` for explicit actions:

```text
revive
archive search
manual repair/reconcile
doctor/debug command
```

Do not trigger it from a normal Agents-tab query. The default search should filter the current inbox.

### 5. Lazy-load detail-only data

Move these out of the default list load:

```text
attempt history
large prompt/response snippets
tool-call timelines
full workflow step payloads
artifact file panels
```

Load them only for the selected agent or an expanded row. The list refresh should be mostly SQLite rows plus process-liveness checks for active PIDs.

## The architecture I would aim for

```text
Agent artifacts:
  Full source of truth, append/update marker files as today.

Agent artifact index:
  SQLite materialized projection, maintained incrementally.

TUI Agents tab:
  Reads only visible projection.
  Never scans all artifact dirs on ordinary refresh.
  Lazy-loads detail panel fields.

Daemon / watcher / lifecycle hooks:
  Keep index up to date.
  Coalesce filesystem events.
  Repair rows on missed events.

Source scan:
  Background rebuild / verify / repair only.
```

This matches the direction already present in the codebase. The Rust backend docs list `scan_agent_artifacts`, `rebuild_agent_artifact_index`, `upsert_agent_artifact_index_row`, `delete_agent_artifact_index_row`, and `query_agent_artifact_index` as shipped Rust-backed operations.  The missing piece is making that index the maintained, load-bearing projection for ACE’s Agents tab.

## Expected performance

With the above design, a normal refresh should look like:

```text
SQLite query visible rows:        ~1–20 ms
hydrate Agent objects:            ~1–20 ms
PID liveness for active rows:      O(active agents), usually tiny
detail lazy-load for selection:    separate worker
```

The trace target should be:

```text
agents.load_from_disk p95 < 50 ms for normal refresh
agents.load_from_disk max < 150 ms unless index rebuild/full-history was explicitly requested
j/k key-to-paint p95 < 33 ms
```

A 3.5 second `agents.load_from_disk` should only happen in explicit archive/rebuild/doctor paths, never during regular TUI interaction.
