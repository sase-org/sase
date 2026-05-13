---
create_time: 2026-05-13
updated_time: 2026-05-13
status: research
---

# Agents Tab Reproduction Harness Research

## Question

How can SASE make "agents disappeared, reappeared, duplicated, or rendered without parents" bugs reproducible for
future coding agents, especially when the failure only appears in Bryan's long-lived local `sase ace` session?

## Summary Recommendation

Build an agent-facing repro bundle for the ACE Agents tab with three coordinated entry points:

1. an **in-TUI capture keybinding** that dumps a bundle from the live session where the failure is actually visible,
2. an **out-of-band CLI** (`sase repro capture agents-tab …`) for non-interactive captures, and
3. a **replay path** that drives `AceApp.run_test()` against the captured loader sequence.

```bash
# In the running TUI:
#   <leader>R c   → capture bundle of current Agents tab state
#   <leader>R t   → toggle continuous invariant checking + auto-capture on violation

# Out-of-band CLI (top-level, not under `sase ace`, see CLI Surface section):
sase repro capture agents-tab --output ~/.sase/repros/<id>
sase repro replay ~/.sase/repros/<id> --assert-stable --json
```

The previous fix attempts failed for a recognizable reason: the bug class lives in the **interaction** between an
incomplete artifact index, a long-lived TUI state, and a refresh schedule. None of those are reproduced by a screenshot,
a unit fixture, or a fresh agent workspace. Capturing them as a bundle and replaying them in-process closes that gap.

The capture command should save the exact data that makes Bryan's session different from a clean agent workspace:

- agent artifact-index rows and a bounded source-scan snapshot;
- dismissed-agent state, unread state, grouping/filter/fold state, current query, selected identity, and refresh flags;
- the current in-memory Agents-tab row projection before and after two or three refresh cycles;
- `SASE_TUI_TRACE=1` JSONL events around load/apply/finalize/render;
- a text screen capture and PNG/SVG visual snapshot;
- environment facts that affect rendering or scan behavior.

The replay command should run in-process through `AceApp.run_test()`, patch the loader to replay the captured tier
sequence, drive the same refresh/key sequence, and assert invariants that match the user-visible failure mode:

- row suffixes do not disappear between Tier 1 and Tier 2 refreshes after full history has loaded;
- a root suffix has at most one visible root representation;
- visible child rows have a visible parent unless intentionally flattened;
- selected identity remains valid after refresh;
- the screen text and structured state remain stable across repeated refresh cycles.

This is the missing layer between unit tests and live manual screenshots. The recent issue was not simply "the UI looks
wrong"; it depended on a local artifact corpus, an incomplete index load, a complete source scan, and subsequent
incomplete refresh patches. Clean agent workspaces did not naturally have that state.

## Local Evidence

Recent SASE chats describe the same family of failures:

- `~/.sase/chats/202605/sase-ace_run-s5_cdx_plan-260512_230832.md`: diagnosed Tier 1/Tier 2 loader oscillation. Tier 1
  returned a small active/recent row set while Tier 2 returned thousands of historical rows, so ordinary refreshes
  could shrink and regrow the Agents tab.
- `~/.sase/chats/202605/sase-ace_run-t7_cdx_plan-260513_095827.md`: diagnosed duplicate roots for one live launch. A
  Tier 1 `RUNNING` row and a Tier 2 `WORKFLOW` parent represented the same raw suffix but did not merge cleanly.
- `~/.sase/chats/202605/sase_org-gh-main-260512_213827.md`: diagnosed an empty Agents tab until manual `y` refresh,
  pointing at startup Tier 1 load plus missing or delayed Tier 2 reconcile.

The current code already contains fixes and primitives around this area (verified 2026-05-13):

- `src/sase/ace/tui/actions/agents/_loading_apply.py` has `_merge_incomplete_load_after_complete_history()`, which
  treats post-reconcile incomplete loads as patches over the cached complete-history list. The watermark flag is
  `self._agents_seen_complete_history` (see `_loading_apply.py:175`).
- `src/sase/ace/tui/actions/agents/_loading_helpers.py:87` defines `load_agents_from_disk(...)` and `:110`
  `load_agents_from_disk_with_state(...) -> _AgentDiskLoadResult` (`_AgentDiskLoadResult` is the private
  dataclass holding `all_agents`, `dismissed_from_loader`, and `load_state`).
- `src/sase/ace/tui/models/agent_loader.py:75` defines `AgentLoadState` with fields
  `tier: Literal["tier1", "tier2"]`, `complete_history: bool`, `artifact_source: Literal["artifact_index",
  "source_scan"]`, `used_artifact_index: bool`, `index_error: str | None`, and a derived
  `needs_full_history_reconcile` property. This is the canonical handle for the bug class; the bundle's tier
  sequence should serialize these fields verbatim.
- `src/sase/ace/tui/models/agent.py:441` defines `Agent.identity` as `(agent_type, cl_name, raw_suffix)`. This is
  the unit the invariant checker should index by.
- `tests/test_agent_loader_self_heal.py` has focused unit coverage for post-history incomplete loads, duplicate
  RUNNING/WORKFLOW roots, metadata donation, PID dedup, and child reattachment. It is the right neighbor for the
  replay test.
- `src/sase/ace/testing/__init__.py` exposes `AcePage` (`:122`) — a Playwright-like wrapper around
  `AceApp.run_test()`, `Pilot.press()`, `state` extraction (`:189`), `screen` text capture (`:195`), and
  `export_svg()` (`:200`).
- `tests/ace/tui/visual/snapshots/png/` holds PNG visual goldens with pinned fonts and explicit update mechanics
  (see `tests/ace/tui/visual/_ace_png_snapshot_helpers.py` and `just test-visual`).
- `src/sase/ace/tui/util/trace.py` already supports `SASE_TUI_TRACE=1` JSONL spans/events with
  `tui_trace(span, **counters)`, `trace_event(event, **fields)`, and `set_trace_context(**fields)`. Loader spans
  exist today (`agents.load_from_disk`, `agents.refresh_debounced`, etc.) so new repro events should compose with
  the existing schema, not replace it.
- `tests/ace/tui/terminal_smoke/test_ace_terminal_smoke.py` gives optional real-PTY coverage through `pexpect` and
  `pyte` (marked `slow` + `terminal_smoke`).

Those pieces are useful but incomplete. What is missing is a way to preserve a real failing local Agents-tab state and
make another agent replay that state without access to Bryan's exact `~/.sase` runtime.

## Cross-References

This research builds on, and should not duplicate, neighbors in the same month:

- `sdd/research/202605/tui_agent_screenshot_automation.md` — Textual-native automation via `AcePage` plus the
  `sase ace` CLI-conflict analysis (positional `query` already consumes the next argv slot).
- `sdd/research/202605/tui_pixel_snapshot_testing.md` — visual-regression layering (SVG → PNG → optional terminal
  raster) that the repro bundle should reuse rather than reinvent.
- `sdd/tales/202605/agent_tier_merge_watermark.md` and `agent_tier_merge_dedup_backstop.md` — the two tales the
  bug class spawned; their acceptance criteria are the most concrete invariant source today.
- `sdd/tales/202605/revive_empty_artifact_index.md` — the empty-Agents-tab-on-startup failure mode.

The repro bundle is the missing observability layer between those tales and any future regression.

## External Prior Art

Textual's official testing guide supports the core direction: `App.run_test()` runs an app headlessly and returns a
`Pilot` for simulated keyboard and mouse interaction. The guide also documents deterministic test sizes and waiting for
the message queue to drain. Source: [Textual testing guide](https://textual.textualize.io/guide/testing/).

Textual also provides screenshot APIs, which SASE already wraps through `AcePage.export_svg()`. This makes an
in-process screen artifact cheaper and more structured than terminal scraping. Source:
[Textual App API](https://textual.textualize.io/api/app/).

Playwright's trace model is the closest browser-world analogue. It records enough context to inspect actions,
screenshots, DOM snapshots, console output, and network activity after a failure, which is exactly the shape SASE needs
for a TUI: action sequence, screen state, structured state, and logs in one artifact. Source:
[Playwright trace viewer](https://playwright.dev/docs/trace-viewer).

The `rr` debugger is useful as a principle, even though it is not the right everyday TUI tool here: when a bug is
timing-sensitive, record the original execution and replay it repeatedly instead of asking every investigator to
rediscover the same interleaving. Source: [rr project](https://rr-project.org/).

OpenTelemetry trace context and baggage provide a useful vocabulary for correlation: every span/log/event related to
one user-visible issue needs a shared trace/repro id, and contextual fields should travel with the work. Source:
[OpenTelemetry baggage docs](https://opentelemetry.io/docs/concepts/signals/baggage/).

For flaky tests, pytest ecosystem tools such as `pytest-repeat` and `pytest-rerunfailures` show that repeat/amplify
loops are standard practice, but they should not be the only strategy. Repeating a test is helpful after the harness can
load the same state; it is weak when the original state was never captured. Sources:
[pytest-repeat](https://pypi.org/project/pytest-repeat/) and
[pytest-rerunfailures](https://pytest-rerunfailures.readthedocs.io/).

Hypothesis stateful testing is relevant for loader invariants. The Agents tab is a state machine: launch, dismiss,
revive, refresh Tier 1, reconcile Tier 2, group, fold, filter, and select. A small model can generate legal event
sequences and assert row-identity invariants. Source:
[Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html).

## Why Agents Could Not Reproduce This Reliably

The failing behavior depended on several pieces of ambient state that normal agents do not inherit:

- a large, old, real `~/.sase` artifact corpus with historical and active agents;
- artifact-index freshness relative to source-scan truth;
- dismissed and revived bundles;
- active running process metadata such as PID, workspace, provider, and workflow state;
- current TUI runtime state, including `_agents_seen_complete_history`, scheduled refresh flags, grouping, folds, and
  selected identity;
- timing of automatic refreshes while other disk scans are in flight;
- terminal dimensions and rendered visible rows.

A screenshot proves the symptom but discards most of that state. A unit test proves one hypothesized cause but may miss
the actual local interleaving. The right fix is to make the user's TUI session emit a repro artifact that contains both
the visible symptom and the underlying loader inputs.

There is also a **transience** problem: by the time Bryan notices the agents-tab glitch, he is several refresh cycles
past the precipitating tier-1 load. Out-of-band capture would miss it. The harness needs a small in-memory ring buffer
of recent loader results plus an in-TUI hotkey that flushes the buffer, so post-hoc capture still recovers the
preceding tier sequence.

## Proposed Repro Bundle

Use a directory, not a single JSON blob, so large artifacts and images stay inspectable:

```text
~/.sase/repros/agents-tab-20260513-101530/
  manifest.json
  env.json
  loader/
    artifact_index_snapshot.json
    source_scan_snapshot.json
    tier_sequence.json
    dismissed_agents.json
  tui/
    app_state_before.json
    app_state_after_refresh_1.json
    app_state_after_refresh_2.json
    screen_before.txt
    screen_after_refresh_1.txt
    screen_after_refresh_2.txt
    screenshot_before.svg
    screenshot_after_refresh_2.svg
  trace/
    tui_trace.jsonl
    agent_loader_events.jsonl
  assertions/
    observed_failure.json
```

`manifest.json` should include:

- schema version;
- repo commit;
- Python version and SASE version;
- capture timestamp and timezone;
- current project/workspace;
- command used to capture;
- current tab, group mode, panel mode, query, selected identity;
- paths to all files in the bundle.

`tier_sequence.json` is the key file for this bug class. Each step should serialize the live `AgentLoadState` fields
verbatim plus enough row metadata for replay; this keeps the bundle decoupled from the in-process dataclass:

```json
[
  {
    "step": 1,
    "load_state": {
      "tier": "tier1",
      "complete_history": false,
      "artifact_source": "artifact_index",
      "used_artifact_index": true,
      "index_error": null
    },
    "row_count": 15,
    "root_count": 12,
    "child_count": 3,
    "running_count": 4,
    "agents_seen_complete_history_before": false
  },
  {
    "step": 2,
    "load_state": {
      "tier": "tier2",
      "complete_history": true,
      "artifact_source": "source_scan",
      "used_artifact_index": false,
      "index_error": null
    },
    "row_count": 4213,
    "root_count": 4011,
    "child_count": 202,
    "running_count": 4,
    "agents_seen_complete_history_before": false
  },
  {
    "step": 3,
    "load_state": {
      "tier": "tier1",
      "complete_history": false,
      "artifact_source": "artifact_index",
      "used_artifact_index": true,
      "index_error": null
    },
    "row_count": 16,
    "root_count": 13,
    "child_count": 3,
    "running_count": 4,
    "agents_seen_complete_history_before": true
  }
]
```

Each step also references a sibling `loader/agents_step_<N>.jsonl` file with a **minimal** per-agent record (one JSON
object per line) so a replay does not need to reconstruct the entire `Agent` dataclass surface:

```text
identity        # tuple [agent_type, cl_name, raw_suffix] — the dedup key
status          # RUNNING | DONE | FAILED | ...
pid             # int | null
workflow        # str | null
parent_timestamp # str | null
parent_workflow # str | null
is_workflow_child
hidden
raw_suffix
artifact_mtime  # float (epoch) — preserves the sort order that drives recency
tag             # str | null
retry_attempt
retried_as_timestamp
```

The minimal schema matches what `_merge_incomplete_load_after_complete_history()` actually consults, and avoids
serializing private file paths, chat content, or diffs.

## In-TUI Capture Path

This is the part the previous draft underspecified. Bryan's failure is observed while ACE is running; he cannot exit
the TUI to capture without losing the state.

Concrete shape:

1. Bind two leader keys (proposal: `<leader>R c` capture, `<leader>R t` toggle continuous invariant checks). Add to
   `src/sase/default_config.yml` and to the help modal per `src/sase/ace/AGENTS.md`.
2. Implement a small `_repro_buffer` on `AceApp` that retains the last N (default 8) `_AgentDiskLoadResult` summaries
   plus their `AgentLoadState`, the merged-row projection, and the trace events emitted during that window. Buffer
   entries are bounded by count and total bytes (drop oldest); they are never persisted unless capture fires.
3. On capture-keypress, flush the ring buffer plus current TUI state to
   `~/.sase/repros/agents-tab-<utc-iso>/` (the layout in the next section), append a fresh SVG via the existing
   `export_svg()` path, and surface a toast: `repro captured: <path>`.
4. Continuous invariant mode: every loader apply runs the invariant checker; on first violation, the buffer is flushed
   automatically and continuous mode disables itself so the bundle is not stomped by subsequent applies.

The TUI hook is what makes the bug reproducible at all. Without it, Bryan has to predict when the glitch will appear.

## SASE_HOME Redirect (Sandboxed Real-Loader Replay)

Replay through `AceApp.run_test()` against monkeypatched loader results is the right *default*. But for high-fidelity
investigation, agents also need to be able to run the *real* loader against a sanitized copy of Bryan's `~/.sase`.

Two pieces are required:

1. **`SASE_HOME` (or equivalent) env override** in `src/sase/core/paths.py` so every code path that constructs
   `Path.home() / ".sase"` (search for usages in `agent_loader.py:112,117`) honors a redirect. This is a small,
   independently useful refactor.
2. **`sase repro snapshot-home`** — packages a redacted subset of `~/.sase/projects/<project>/` (artifact-index file,
   artifact-tree directory structure with empty/stubbed files, dismissed-agents state, workflow-state JSON) into a
   directory other agents can point `SASE_HOME` at.

The redacted snapshot trades fidelity for shareability: chat bodies are stripped, only filenames and mtimes are kept,
and a path manifest documents what was redacted. Agents can then run `SASE_HOME=/tmp/repro-home sase ace …` and see the
real loader operate against the real shape of the failure.

This complements the in-process replay rather than replacing it: replay is for invariant assertions in tests, snapshot
is for interactive investigation.

## Privacy and Redaction

A capture bundle must be safe to attach to a bead, paste into a chat, or commit as a fixture. The capture command must
apply these defaults and document any opt-out:

| Field | Default action |
| --- | --- |
| Agent prompt / reply file bodies | dropped; only filename + size kept |
| Diff bodies (`diff_path`) | dropped; only filename kept |
| `cl_name`, `raw_suffix`, project name | hashed to stable short tokens (HMAC with a per-bundle salt) |
| Absolute filesystem paths under `$HOME` | replaced with `<HOME>/...` |
| `pid`, retry timestamps, mtimes | kept (needed for sort order) |
| `~/.sase/chats/**/*.md` | excluded entirely |
| Provider tokens or env vars matching `*KEY*`, `*TOKEN*`, `*SECRET*` | excluded |

The same salt is written into `manifest.json` so a single bundle's identity tokens stay self-consistent, but cross-
bundle correlation requires the original local data. Add a `--commit-safe` flag for the stricter redaction needed when
the bundle will be checked in as a fixture.

## CLI Surface

The existing `sase ace` parser (`src/sase/main/parser_ace.py:14`) consumes the next positional argv as the ACE query,
so a `sase ace repro …` subcommand would collide. Two options:

- **Recommended**: introduce a top-level `sase repro` subcommand. This keeps `sase ace` argv stable and aligns with how
  prior research (`tui_agent_screenshot_automation.md`) recommended handling the same conflict for screenshots.
- Alternatively, reuse the in-TUI command palette (no CLI surface at all) plus a `sase axe` companion subcommand for
  non-interactive captures driven by hooks.

Either way, **do not** wedge a subcommand under `sase ace`.

## Replay Harness Shape

The replay should not launch real agents. It should patch the loader boundary and feed the captured tier sequence to
ACE.

Suggested pytest entry point:

```bash
pytest tests/ace/tui/repro/test_agents_tab_repro.py \
  --sase-repro ~/.sase/repros/agents-tab-20260513-101530 \
  -q
```

Suggested CLI wrapper for agents:

```bash
sase repro replay ~/.sase/repros/agents-tab-20260513-101530 \
  --cycles 3 \
  --assert-stable \
  --save-artifacts \
  --json
```

Implementation sketch:

1. Load `manifest.json`, state files, and loader snapshots.
2. Construct `AceApp(query=..., refresh_interval=0, auto_start_axe=False)` through `AcePage` or a production
   automation helper. Use the captured terminal size from `manifest.json` rather than the default 80×24, because the
   visible-row count affects which rows the renderer truncates.
3. Monkeypatch `load_agents_from_disk_with_state()` to return reconstructed `_AgentDiskLoadResult` objects (with the
   recorded `AgentLoadState`) for step 1, step 2, step 3, then repeat step 3. The agent records in each step are
   rehydrated from `loader/agents_step_<N>.jsonl` into the minimal `Agent` fields the apply layer actually reads.
4. Set the captured `_agents_seen_complete_history` watermark and `_dismissed_agents` set on the app instance before
   the first apply, so the merge logic in `_loading_apply.py:175` is exercised exactly as it was in production.
5. Set grouping/fold/filter state, query, and selected identity from the bundle.
6. Press `tab` to agents, optionally replay captured keys, then trigger refreshes.
7. After each refresh, collect structured state, row identities, screen text, and SVG/PNG.
8. Assert invariants and write a replay report.

The replay test should live alongside `tests/test_agent_loader_self_heal.py` (e.g.,
`tests/ace/tui/repro/test_agents_tab_repro.py`). Full local bundles stay under `~/.sase/repros`; only minimal redacted
fixtures are committed.

## Invariants To Assert

For the Agents tab, the highest-value invariant checks are simple and user-visible:

- `raw_suffix` uniqueness for visible root rows, unless two roots have an explicit, documented distinct identity.
- No `RUNNING` root and `WORKFLOW` root for the same raw suffix after complete history has ever loaded.
- Every visible workflow child has a visible parent row with matching `parent_timestamp`.
- A post-complete-history incomplete load may update active rows and add new rows, but may not shrink away historical
  rows solely because the artifact index is incomplete.
- Dismissed suffixes stay dismissed across replay cycles.
- Selection after refresh resolves by identity, not stale index.
- Repeating the same replay cycle twice produces the same visible row identities and group counts.

These checks would have caught the specific disappearance/reappearance and duplicate-root failures earlier than a
manual screenshot.

## Trace Events To Add

The existing `SASE_TUI_TRACE` mechanism already wraps `agents.load_from_disk`, `agents.refresh_debounced`, and several
display spans via `tui_trace(...)` (see `src/sase/ace/tui/util/trace.py:107`). The repro harness should compose with
that schema, not replace it. Concretely:

- Use `tui_trace("agents.apply.merge", ...)` around `_merge_incomplete_load_after_complete_history()` with counters
  `cached`, `incoming`, `merged`, `dropped_duplicate_roots`, `preserved_cached`.
- Emit `trace_event("agents.load.result", tier=..., artifact_source=..., complete_history=..., rows=..., roots=...,
  children=...)` at the tail of `load_agents_from_disk_with_state()` so the bundle has a single point-in-time row
  matching the JSONL entry it serialized.
- Emit `trace_event("agents.apply.finalize", visible=..., hidden=..., group_mode=..., selected_identity=...)` after
  every projection.
- Emit `trace_event("agents.invariant.violation", kind=..., identities=[...])` when the invariant checker fires.

Call `set_trace_context(repro_id=<id>)` from the in-TUI capture helper while the buffer is active, and clear it after
the flush. This follows the OpenTelemetry baggage principle — every record produced during one investigation gets a
shared correlation id — without requiring a telemetry stack.

## Flake Amplification

After replay exists, add repeat modes:

```bash
sase ace repro replay ~/.sase/repros/<id> --repeat 100 --shuffle-refresh-delays
pytest tests/ace/tui/repro/test_agents_tab_repro.py --sase-repro ~/.sase/repros/<id> --count=100
```

This is where `pytest-repeat`-style behavior helps. The repeat loop should randomize only controlled delays and event
ordering at SASE boundaries, not the captured loader data itself. The output should stop on first failure and save the
seed, trace, screen, and row projection for that iteration.

## Stateful Property Testing

Add a small model-based test for the loader/apply layer once the repro harness is in place.

Model events:

- `tier1_load(rows)`
- `tier2_load(rows)`
- `dismiss(identity)`
- `revive(raw_suffix)`
- `toggle_grouping(mode)`
- `fold(parent)`
- `refresh()`

Model invariants:

- no duplicate root suffix after complete history;
- no orphan children after filtering;
- dismissed rows are not resurrected;
- selected identity either remains present or moves to a documented fallback.

Hypothesis stateful tests are a good fit here because the bug class is not one fixed input. It is a sequence bug.

## Minimal Implementation Plan

1. Add `src/sase/ace/tui/actions/agents/_invariants.py` with a pure `check_agent_invariants(agents, *, dismissed,
   seen_complete_history) -> list[Violation]` function. No app dependency; usable from tests, capture, and replay.
2. Add a private capture helper (e.g., `src/sase/ace/tui/actions/agents/_repro_capture.py`) that serializes the current
   row projection, TUI state, and ring-buffer contents from a running `AceApp` into the bundle layout.
3. Add `SASE_HOME` env-override support in `src/sase/core/paths.py` and the two loader call sites in
   `src/sase/ace/tui/models/agent_loader.py:112,117`. Cover with one unit test that sets `SASE_HOME` to a fixture.
4. Wire `trace_event` calls per the section above and call `set_trace_context(repro_id=...)` from the capture helper.
5. Add a ring-buffer attribute on `AceApp` (default depth 8) that records `_AgentDiskLoadResult` summaries + the post-
   apply row projection on every apply, bounded by entries and total bytes.
6. Add an in-TUI capture keybinding and continuous-invariant toggle. Update `src/sase/default_config.yml` and the help
   modal (`src/sase/ace/AGENTS.md` mandates this).
7. Add a replay pytest helper (`tests/ace/tui/repro/test_agents_tab_repro.py`) that rehydrates captured per-step
   `_AgentDiskLoadResult` objects and drives the apply layer plus `AcePage` for end-to-end coverage.
8. Add top-level `sase repro {capture-agents-tab, replay, snapshot-home}` CLI wrappers once the helper is useful in
   tests. Do not nest under `sase ace` (positional `query` collides).
9. Convert one real local repro bundle into a small committed fixture that reproduces the Tier 1/Tier 2 oscillation,
   with the strict redaction profile.

The tales `agent_tier_merge_watermark.md` and `agent_tier_merge_dedup_backstop.md` can adopt this harness as their
durable regression bed.

## Risks And Tradeoffs

Do not commit full `~/.sase` captures by default. Agent prompts, replies, artifact paths, branch names, and local
machine paths may contain private information. The capture command needs redaction and a `--commit-safe-fixture`
conversion path.

Do not make terminal/PTY replay the default. The repo already has a real-PTY smoke test, and that is useful, but this
bug class lives mostly in loader state and Textual app state. In-process `AceApp.run_test()` gives better observability
and fewer environmental variables.

Do not rely only on screenshots. Screenshots are evidence, not a complete reproduction. Every capture should include
structured row identities, loader state, and trace events.

## Open Questions

These are worth resolving before the implementation plan is treated as final:

- **Bundle storage location**: `~/.sase/repros/` keeps bundles next to other sase state, but `$SASE_TMPDIR` is also
  reasonable for short-lived captures. Pick one and document.
- **Ring buffer scope**: should it live on `AceApp` only, or also wrap loader calls in `axe` so axe-driven loads
  contribute? The current bug is TUI-only, so app-scoped is fine, but axe could expose a different timing.
- **Fixture commit policy**: where do committed minimal fixtures live — under `tests/ace/tui/repro/fixtures/` or under
  `sdd/research/202605/fixtures/`? The former is closer to the test that uses them.
- **Interaction with the existing PNG visual suite**: should the replay assert against a committed PNG, or only emit
  one for human review? Recommendation: emit only; the loader-row invariant checks are stronger gates than pixel diffs.

## Bottom Line

The durable answer is not more ad hoc manual screenshots. SASE needs a first-class "capture my broken Agents tab and
replay it in a clean workspace" path with three coordinated entry points: in-TUI hotkey capture (so transient failures
survive long enough to record), in-process replay against the captured tier sequence (for fast invariant tests), and a
`SASE_HOME` redirect plus redacted home snapshot (for high-fidelity manual investigation). The repo already has most
of the primitives — `AcePage`, `AgentLoadState`, `tui_trace`, PNG goldens, `_merge_incomplete_load_after_complete_history`
— and the gap is the bundle format, the ring buffer, the invariant checker, the `SASE_HOME` seam, and the top-level
`sase repro` CLI that ties them together.
