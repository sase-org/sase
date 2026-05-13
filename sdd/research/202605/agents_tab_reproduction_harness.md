---
create_time: 2026-05-13
status: research
---

# Agents Tab Reproduction Harness Research

## Question

How can SASE make "agents disappeared, reappeared, duplicated, or rendered without parents" bugs reproducible for
future coding agents, especially when the failure only appears in Bryan's long-lived local `sase ace` session?

## Summary Recommendation

Build an agent-facing repro bundle and replay command for the ACE Agents tab.

The immediate product shape should be:

```bash
sase ace repro capture agents-tab --output ~/.sase/repros/<id>
sase ace repro replay ~/.sase/repros/<id> --assert-stable --json
```

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

The current code already contains fixes and tests around this area:

- `src/sase/ace/tui/actions/agents/_loading_apply.py` now has
  `_merge_incomplete_load_after_complete_history()`, which treats post-reconcile incomplete loads as patches over the
  cached complete-history list.
- `tests/test_agent_loader_self_heal.py` has focused unit coverage for post-history incomplete loads, duplicate
  RUNNING/WORKFLOW roots, metadata donation, PID dedup, and child reattachment.
- `src/sase/ace/testing/__init__.py` exposes `AcePage`, a Playwright-like wrapper around `AceApp.run_test()`,
  `Pilot.press()`, text capture, structured state extraction, and SVG export.
- `tests/ace/tui/visual/` already has PNG visual snapshots with pinned fonts and explicit update mechanics.
- `src/sase/ace/tui/util/trace.py` already supports `SASE_TUI_TRACE=1` JSONL spans and events.
- `tests/ace/tui/terminal_smoke/test_ace_terminal_smoke.py` gives optional real-PTY coverage through `pexpect` and
  `pyte`.

Those pieces are useful but incomplete. What is missing is a way to preserve a real failing local Agents-tab state and
make another agent replay that state without access to Bryan's exact `~/.sase` runtime.

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

`tier_sequence.json` is the key file for this bug class. It should preserve the order and summary of loader refreshes,
for example:

```json
[
  {
    "step": 1,
    "source": "artifact_index",
    "complete_history": false,
    "row_count": 15,
    "needs_full_history_reconcile": true
  },
  {
    "step": 2,
    "source": "source_scan",
    "complete_history": true,
    "row_count": 4213,
    "needs_full_history_reconcile": false
  },
  {
    "step": 3,
    "source": "artifact_index",
    "complete_history": false,
    "row_count": 16,
    "needs_full_history_reconcile": true
  }
]
```

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
sase ace repro replay ~/.sase/repros/agents-tab-20260513-101530 \
  --cycles 3 \
  --assert-stable \
  --save-artifacts \
  --json
```

Implementation sketch:

1. Load `manifest.json`, state files, and loader snapshots.
2. Construct `AceApp(query=..., refresh_interval=0, auto_start_axe=False)` through `AcePage` or a production
   automation helper.
3. Monkeypatch `load_agents_from_disk_with_state()` to return step 1, step 2, step 3, then repeat step 3.
4. Set grouping/fold/filter state from the bundle.
5. Press `tab` to agents, optionally press captured keys, then trigger refreshes.
6. After each refresh, collect structured state, row identities, screen text, and SVG/PNG.
7. Assert invariants and write a replay report.

This should live next to current TUI tests, but the captured bundles should not all be committed. Commit only small
minimal fixtures derived from bundles; keep full local bundles under `~/.sase/repros`.

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

The existing `SASE_TUI_TRACE` mechanism should gain focused events around the loader and row projection:

- `agents.load.start`: source, requested full-history flag, search query present, previous complete-history watermark.
- `agents.load.result`: tier, artifact source, complete-history flag, row count, root count, child count.
- `agents.apply.merge`: cached count, incoming count, merged count, dropped duplicate roots, preserved cached rows.
- `agents.apply.finalize`: visible count, hidden count, group mode, selected identity, selected index.
- `agents.invariant.violation`: machine-readable violation type plus affected identities.

Trace rows should include a `repro_id` when capture mode is active. This follows the OpenTelemetry principle that
events for one investigation need shared context, without requiring a full telemetry stack.

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

1. Add a private capture helper that serializes current Agents-tab row projection and TUI state from a running
   `AceApp`.
2. Add trace events in `_load_agents_async()`, `_merge_incomplete_load_after_complete_history()`, and finalization.
3. Add a replay pytest helper that feeds captured `LoadAgentsResult` objects through `AgentLoadingApplyMixin`.
4. Add `sase ace repro capture agents-tab` and `sase ace repro replay <dir>` wrappers after the helper is useful in
   tests.
5. Convert one real local repro bundle into a small committed fixture that reproduces the Tier 1/Tier 2 oscillation.
6. Add an invariant checker that can run both during replay and against live capture output.

## Risks And Tradeoffs

Do not commit full `~/.sase` captures by default. Agent prompts, replies, artifact paths, branch names, and local
machine paths may contain private information. The capture command needs redaction and a `--commit-safe-fixture`
conversion path.

Do not make terminal/PTY replay the default. The repo already has a real-PTY smoke test, and that is useful, but this
bug class lives mostly in loader state and Textual app state. In-process `AceApp.run_test()` gives better observability
and fewer environmental variables.

Do not rely only on screenshots. Screenshots are evidence, not a complete reproduction. Every capture should include
structured row identities, loader state, and trace events.

## Bottom Line

The durable answer is not more ad hoc manual screenshots. SASE needs a first-class "capture my broken Agents tab and
replay it in a clean workspace" path. The repo already has most of the primitives; the missing work is packaging loader
snapshots, TUI state, trace events, and visual artifacts into one reproducible bundle with invariant checks.
