---
create_time: 2026-05-13 11:40:55
status: done
prompt: sdd/prompts/202605/agents_tab_repro_mvp.md
bead_id: sase-3d
tier: epic
---
# Plan: Agents Tab Reproduction Testing Framework MVP

## Goal

Implement a highly capable MVP of the Agents-tab reproduction framework recommended by
`sdd/research/202605/agents_tab_reproduction_harness.md`.

The MVP must do two things:

1. make the long-lived `sase ace` Agents-tab disappearance/reappearance/duplicate-parent bug class reproducible by
   future agents; and
2. determine whether the currently checked-out code fixes the known bug class, using a replay that exercises the TUI
   path rather than only loader unit tests.

This should be completed in phases. Each phase is designed for a distinct agent instance and should leave the repo in a
working state. Later phases may depend on artifacts or APIs from earlier phases, but file ownership should stay narrow
to reduce merge conflicts.

## Current Context

Relevant facts verified in this workspace:

- The root symptom is a tiered loader/UI-state interaction: Tier 1 incomplete artifact-index loads can temporarily
  shrink the visible Agents-tab row universe after a Tier 2 complete-history source scan has populated it.
- Existing fixes live mainly in `src/sase/ace/tui/actions/agents/_loading_apply.py`.
  `_merge_incomplete_load_after_complete_history()` now uses `_agents_seen_complete_history` and reuses cached
  `_agents_with_children` for incomplete post-history loads.
- The loader state type is `AgentLoadState` in `src/sase/ace/tui/models/agent_loader.py`, with fields `tier`,
  `complete_history`, `artifact_source`, `used_artifact_index`, and `index_error`.
- The disk-load wrapper is `_AgentDiskLoadResult` in `src/sase/ace/tui/actions/agents/_loading_helpers.py`.
- Row identity is `Agent.identity == (agent_type, cl_name, raw_suffix)` in `src/sase/ace/tui/models/agent.py`.
- Existing focused unit coverage is in `tests/test_agent_loader_self_heal.py`; it proves important merge invariants but
  does not provide an agent-facing replay bundle or a headless TUI replay path.
- `src/sase/ace/testing/__init__.py` exposes `AcePage`, which wraps `AceApp.run_test()`, keyboard input, structured
  state, screen text, and SVG screenshot export.
- `sase ace` cannot safely gain `repro` subcommands because `parser_ace.py` uses a positional `query`. Use a top-level
  `sase repro ...` namespace.
- The repo requires `just install` before validation in fresh workspaces and `just check` before responding after file
  changes. Current prior runs reported a pre-existing `pyvision` failure in `src/sase/axe/...`; agents should still run
  the check and capture the exact result.

Do not modify memory files without explicit user approval.

## Architectural Shape

Build the framework around a small, reusable library first, then expose it through tests, TUI capture, and CLI:

- `src/sase/ace/tui/repro/` for bundle schema, redaction, row serialization, invariant checking, and replay helpers.
- Minimal hooks from the existing agent loading path to record loader/apply snapshots into a bounded in-memory ring
  buffer.
- `tests/ace/tui/repro/` for deterministic fixtures and replay tests.
- Top-level `sase repro capture agents-tab ...` and `sase repro replay ...` commands for agent-facing usage.

Keep the MVP explicitly scoped:

- Capture structured Agents-tab state, text screen output, and SVG screenshots; defer PNG unless existing visual helpers
  make it cheap.
- Use synthetic deterministic bundles for CI and real bundles for local debugging.
- Redact by default; support `--commit-safe` bundles suitable for sharing in repo tests.
- Make replay assert structured invariants first and visual/text stability second.

## Phase 1: Repro Schema, Invariants, and Deterministic Bug Fixture

Owner: Agent 1.

Primary files:

- `src/sase/ace/tui/repro/__init__.py`
- `src/sase/ace/tui/repro/schema.py`
- `src/sase/ace/tui/repro/serialize.py`
- `src/sase/ace/tui/repro/invariants.py`
- `tests/ace/tui/repro/test_invariants.py`
- `tests/ace/tui/repro/fixtures/agents_tab_disappear_reappear_v1.json`

Tasks:

1. Define dataclasses or typed dicts for the MVP bundle schema: `manifest`, `load_steps`, `agent_rows`, `app_state`,
   `screen`, `assertions`.
2. Serialize only fields needed for replay and invariants: `agent_type`, `cl_name`, `raw_suffix`, `status`,
   `parent_timestamp`, `parent_workflow`, `workflow`, `appears_as_agent`, `step_type`, `pid`, `workspace_num`,
   `agent_name`, `tag`, and selected metadata donation fields.
3. Implement invariant checks:
   - no post-complete-history incomplete load may shrink away historical row identities unless dismissed;
   - one visible non-child root per `(cl_name, raw_suffix)`/suffix-equivalent root;
   - every visible child with `parent_timestamp` has a visible parent unless explicitly flattened;
   - selected identity is either preserved or intentionally replaced by the selection fallback;
   - repeated replay refreshes converge to stable structured state.
4. Create a deterministic fixture representing the actual bug sequence:
   - Step A: Tier 1 incomplete snapshot with current rows only.
   - Step B: Tier 2 complete snapshot with current plus historical parent/child rows.
   - Step C: repeated Tier 1 incomplete snapshot that would have dropped historical rows under the pre-watermark logic.
   - Optional Step D: duplicate `RUNNING` root shadowing cached `WORKFLOW` parent.
5. Add tests that prove the invariant checker flags the fixture when the Step C post-complete-history visible list
   shrinks, and passes when the expected merged visible list preserves cached rows.

Acceptance:

- Running `pytest tests/ace/tui/repro/test_invariants.py -q` passes.
- The fixture is `--commit-safe`: no absolute home paths, chat bodies, prompt bodies, or diff bodies.
- The fixture captures the disappearance/reappearance sequence clearly enough that a future agent can inspect it without
  Bryan's `~/.sase`.

## Phase 2: TUI Replay Harness and Red/Green Bug Determination

Owner: Agent 2.

Primary files:

- `src/sase/ace/tui/repro/replay.py`
- `src/sase/ace/tui/repro/agent_factory.py`
- `tests/ace/tui/repro/test_agents_tab_replay.py`
- possible small additions to `src/sase/ace/testing/__init__.py`

Tasks:

1. Convert serialized fixture rows back into `Agent` objects and `AgentLoadState` objects.
2. Add a replay helper that runs `AceApp.run_test()` or `AcePage` and patches
   `sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state` to emit the captured sequence.
3. Drive the real load/apply/finalize/render path by switching to the Agents tab and applying the same refresh cadence:
   Tier 1, Tier 2, repeated Tier 1.
4. Capture structured state after every replay step: visible identities, `_agents_with_children`, selected identity,
   load state, `_agents_seen_complete_history`, screen text, and SVG screenshot.
5. Add a legacy-control test that deliberately simulates the old broken behavior, either by monkeypatching the merge
   helper to a replace-only implementation or by disabling `_agents_seen_complete_history`. This control must fail the
   disappearance invariant against the same fixture.
6. Add the current-code test against the same fixture. This test should pass if the current fix is real.

Acceptance:

- The replay test demonstrates red/green:
  - legacy-control path reproduces the historical disappearance or duplicate-root failure;
  - current code preserves rows and passes invariants.
- The final test output or assertion message states the verdict: current code fixed for the captured bug class, or not
  fixed with exact failed invariant.
- Run `pytest tests/ace/tui/repro/test_agents_tab_replay.py -q`.

## Phase 3: Passive In-TUI Capture Ring Buffer

Owner: Agent 3.

Primary files:

- `src/sase/ace/tui/repro/capture.py`
- `src/sase/ace/tui/repro/redact.py`
- small hooks in:
  - `src/sase/ace/tui/actions/agents/_loading_disk.py`
  - `src/sase/ace/tui/actions/agents/_loading_apply.py`
  - `src/sase/ace/tui/actions/agents/_loading_state.py`
  - app startup/state initialization files, as needed
- tests under `tests/ace/tui/repro/test_capture_ring.py`

Tasks:

1. Add a disabled-by-default bounded ring buffer for Agents-tab repro events.
2. Record each loader result before apply and each app projection after apply: `AgentLoadState`, row summaries,
   dismissed set summary, selected identity, complete-history watermark, refresh flags, grouping/filter/fold state,
   current tab, and row counts.
3. Keep recording cheap and defensive. Capture failures must never break normal TUI refresh.
4. Add redaction helpers:
   - hash or shorten `cl_name` and raw path-like fields when `commit_safe=True`;
   - omit prompt, response, chat, and diff body content;
   - preserve raw suffixes or stable synthetic aliases needed for parent/child matching.
5. Add an API such as `capture_agents_tab_repro_bundle(app, output_dir, commit_safe=True)` that flushes the ring buffer
   plus current screen/SVG when called from the TUI.
6. Emit existing `tui_trace`/`trace_event` fields with a `repro_id` where available rather than inventing a parallel
   trace stack.

Acceptance:

- The ring buffer can be enabled in tests and captures at least the last three load/apply cycles.
- Redacted bundle output validates against Phase 1 schema.
- `pytest tests/ace/tui/repro/test_capture_ring.py -q` passes.

## Phase 4: Agent-Facing CLI

Owner: Agent 4.

Primary files:

- `src/sase/main/parser_repro.py`
- `src/sase/main/repro_handler.py`
- `src/sase/main/parser.py`
- `src/sase/main/entry.py`
- `src/sase/ace/tui/repro/cli.py`
- tests under `tests/main/` or `tests/ace/tui/repro/test_repro_cli.py`

Tasks:

1. Add top-level parser namespace:
   - `sase repro capture agents-tab --output PATH --commit-safe --size 120x40`
   - `sase repro replay PATH --assert-stable --json --write-artifacts PATH`
2. Keep this out of `sase ace` to avoid the existing positional query conflict.
3. Implement `replay` first using the Phase 2 replay library and print JSON with: `schema_version`, `bundle_path`,
   `result`, `failed_invariants`, `state_steps`, `screen_paths`, `screenshot_paths`.
4. Implement out-of-band `capture agents-tab` as a source-of-truth filesystem capture using the real loader. It should
   not require a live TUI process, but it should label itself as `capture_mode=out_of_band` so users know it may miss
   transient prior refreshes.
5. If in-process live TUI capture is not externally invokable yet, expose the library surface and document that live
   hotkey capture arrives in Phase 5.

Acceptance:

- `sase repro replay tests/ace/tui/repro/fixtures/agents_tab_disappear_reappear_v1.json --assert-stable --json` exits 0
  on current fixed code and prints a machine-readable verdict.
- The same command can optionally write screen/SVG artifacts to a temp dir.
- Parser and handler tests cover help/dispatch and JSON error output.

## Phase 5: In-TUI Hotkey Capture and Auto-Capture on Violation

Owner: Agent 5.

Primary files:

- keymap/config files:
  - `src/sase/default_config.yml`
  - `src/sase/ace/tui/keymaps/*`
  - `src/sase/ace/tui/bindings.py` if applicable
- TUI action files under `src/sase/ace/tui/actions/`
- `src/sase/ace/tui/repro/capture.py`
- tests under `tests/ace/tui/repro/`

Tasks:

1. Add an in-TUI action for manual capture from the running session.
2. Use the configured keymap pattern rather than hardcoding runtime-specific behavior. Update `default_config.yml` if a
   new default binding is added.
3. Add an optional continuous invariant-check toggle for the Agents tab. When enabled, after each load/apply cycle run
   cheap invariants and auto-flush a bundle on violation.
4. Store bundles under a predictable user directory such as `~/.sase/repros/<id>/` unless an override is configured.
5. Show a concise toast or status message with the bundle path.

Acceptance:

- In a headless `AcePage` test, pressing the configured capture action writes a valid bundle.
- The auto-capture path writes exactly one bundle per continuous violation burst, not one per refresh forever.
- Existing keymap tests pass.

## Phase 6: Documentation, Operator Workflow, and Visual Artifacts

Owner: Agent 6.

Primary files:

- `sdd/research/202605/agents_tab_reproduction_harness.md` only if needed to update status/outcome
- a user-facing docs location already used by the repo, if one exists
- `tests/ace/tui/repro/README.md` or inline fixture documentation

Tasks:

1. Document the workflow future agents should use:
   - when Bryan sees the bug: trigger in-TUI capture;
   - when an agent investigates: run `sase repro replay ... --json`;
   - when creating regression tests: start from a redacted bundle fixture.
2. Document the red/green result from Phase 2 for the current codebase.
3. Include examples of expected JSON output and where artifacts land.
4. Explain limitations: out-of-band capture cannot reconstruct already-passed transient refreshes; replay covers this
   bug class but not arbitrary rendering races.

Acceptance:

- A future agent can reproduce the known fixture with one command from the docs.
- Docs state whether the current code is fixed for the known disappearing/reappearing Agents-tab bug class.

## Phase 7: Final Integration and Full Validation

Owner: Final integration agent.

Tasks:

1. Review the combined diffs for phase overlap, especially in parser dispatch, keymaps, and loading hooks.
2. Run focused tests:
   - `pytest tests/test_agent_loader_self_heal.py -q`
   - `pytest tests/ace/tui/repro -q`
   - any parser/keymap tests touched by Phase 4/5
3. Run required repo validation:
   - `just install`
   - `just check`
4. If `just check` fails due to the known unrelated `pyvision` private-import gate, record the exact failure and run the
   focused suites plus `just test` if practical.
5. Produce the final verdict:
   - fixed for the replayed disappearance/reappearance sequence;
   - fixed for duplicate root shadow sequence;
   - not fixed, with failed invariant and artifact path.

Acceptance:

- Working tree contains only intended framework/test/docs changes.
- Current-code replay verdict is explicit and backed by a passing or failing command.
- No phase leaves a hidden dependency on Bryan's private `~/.sase` corpus.

## Suggested Agent Prompts

Phase 1 prompt:

```text
Implement Phase 1 from sase_plan_agents_tab_repro_mvp.md: schema, serialization, invariants, and deterministic
commit-safe fixture. Do not implement CLI or TUI hooks. Run the focused invariant tests and report results.
```

Phase 2 prompt:

```text
Implement Phase 2 from sase_plan_agents_tab_repro_mvp.md: headless AceApp replay of the deterministic fixture,
including a legacy-control failing path and a current-code verdict. Keep changes scoped to replay helpers and tests.
```

Phase 3 prompt:

```text
Implement Phase 3 from sase_plan_agents_tab_repro_mvp.md: passive Agents-tab capture ring buffer and redacted bundle
flush API. Do not add CLI or keybindings yet.
```

Phase 4 prompt:

```text
Implement Phase 4 from sase_plan_agents_tab_repro_mvp.md: top-level sase repro capture/replay CLI using the existing
repro library. Keep it out of sase ace.
```

Phase 5 prompt:

```text
Implement Phase 5 from sase_plan_agents_tab_repro_mvp.md: in-TUI manual capture action and optional auto-capture on
Agents-tab invariant violation. Update default keymap config if adding a binding.
```

Phase 6 prompt:

```text
Implement Phase 6 from sase_plan_agents_tab_repro_mvp.md: docs and operator workflow updates, including the current
red/green verdict from replay.
```

Phase 7 prompt:

```text
Perform Phase 7 from sase_plan_agents_tab_repro_mvp.md: integration review, focused tests, just install, just check,
and final verdict on whether the known Agents-tab bug is fixed.
```
