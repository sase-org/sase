---
create_time: 2026-05-16
updated_time: 2026-05-16
status: research
---

# `sase repro` Command Overview

## Question

How does the `sase repro` command work, why is it useful, and how should users and agents invoke it?

## Summary

`sase repro` is the top-level CLI surface for capturing and replaying **Agents-tab reproduction bundles** in the
`sase ace` TUI. It is the operational counterpart to the harness designed in
`sdd/research/202605/agents_tab_reproduction_harness.md`. The command is wired into the main parser at
`src/sase/main/parser.py:101` and dispatched at `src/sase/main/entry.py:252`. Subcommands live under
`src/sase/main/parser_repro.py` and the handlers live in `src/sase/ace/tui/repro/cli.py`.

Two subcommands exist today:

```bash
sase repro capture agents-tab --output <dir> [--no-commit-safe] [--size WxH] [--json]
sase repro replay <bundle-path> [--assert-stable] [--size WxH] [--write-artifacts <dir>] [--json]
```

There is also an in-TUI capture path (no CLI required) bound to leader-mode keys.

Additional source review found four details worth making explicit:

- replay checks the **observed state produced by current code**, not just the captured JSON as-is;
- committed fixtures can intentionally contain a broken captured projection plus `assertions` describing the expected
  fixed projection;
- in-TUI auto-capture does not disable continuous checking after the first failure, but suppresses duplicate writes
  until the violation burst clears;
- commit-safe redaction is useful but not a privacy proof; raw suffixes, status values, PIDs, workspace numbers, tags,
  and other non-path scalar metadata can remain.

## What The Command Does

### `sase repro capture agents-tab`

Defined at `src/sase/main/parser_repro.py:19` and handled by `handle_repro_capture_agents_tab` in
`src/sase/ace/tui/repro/cli.py:71`.

This is an **out-of-band** capture: it does not attach to a running TUI. Instead, it reads the same filesystem state
the Agents tab would load on startup and writes a `ReproBundle` (schema in `src/sase/ace/tui/repro/schema.py`) to
`<output>/agents_tab_repro.json`.

The capture runs the loader twice — once with `full_history=False` (Tier 1, artifact-index path) and once with
`full_history=True` (Tier 2, source-scan path) — and serializes each pass into a `ReproLoadStep`. Each step records:

- `load_state` — tier, `complete_history`, `artifact_source`, `used_artifact_index`, `index_error` from
  `AgentLoadState`. Verbatim of the runtime dataclass.
- `agent_rows` — minimal per-agent rows (identity, status, parent linkage, workflow, pid, workspace, tag, metadata).
- `app_state` — visible identities, selected identity, dismissed identities, and the
  `agents_seen_complete_history` watermark.
- `metadata` — capture mode (`out_of_band`), terminal size, loaded row count, dismissed identity count.

Flags:

- `--output <dir>` (required) — destination directory; the bundle is written as `agents_tab_repro.json` inside it.
- `--commit-safe` (default) / `--no-commit-safe` — when on, `redact_bundle` in `src/sase/ace/tui/repro/redact.py`
  hashes `cl_name` values to stable `cl_<digest>` aliases, removes `agent_name`, drops metadata keys such as
  `prompt_body`, `chat_body`, `response_body`, and `diff_body`, and shortens path-like strings to
  `<path:last/two-parts>`. Bodies of prompts, chats, and diffs are also excluded by construction from the normal row
  serializer. Use `--no-commit-safe` only for local debugging.
- `--size WIDTHxHEIGHT` — terminal size label stored in step metadata (default `120x40`). Does not actually render
  a TUI for out-of-band capture; size matters for the *replay* harness.
- `--json` — emit a machine-readable payload (`schema_version`, `bundle_path`, `result`, `capture_mode`) on stdout.

Out-of-band capture is best understood as a loader baseline. It is valuable when a clean agent wants to inspect the
current filesystem-derived Agents tab inputs, but it produces exactly two synthetic steps (`out_of_band_01` and
`out_of_band_02`) and cannot recover the stale-refresh interleaving that already happened inside a long-running TUI.

### `sase repro replay`

Defined at `src/sase/main/parser_repro.py:59` and handled by `handle_repro_replay` in
`src/sase/ace/tui/repro/cli.py:33`.

Replay runs the captured tier sequence through a headless `AceApp.run_test()` session
(`src/sase/ace/tui/repro/replay.py:87`). Key behaviors:

1. Patches `load_agents_from_disk_with_state` with a `_FixtureLoader` that returns the captured
   `_AgentDiskLoadResult` for each step in order. The replay asserts that the live code requests the same
   `full_history` flag the bundle recorded — drift fails fast.
2. Patches dismissed-agent state to empty, neutralizes notifications and `tui_activity` writes, and skips
   background post-mount loads so timing is deterministic.
3. For each step: expands fold-collapsed parents whose children should be visible, calls `_load_agents`,
   pauses for Textual to drain its message queue, then captures the live `_agents`, `_agents_with_children`,
   selected identity, load state, screen text, and an SVG.
4. Runs `check_bundle_invariants` (`src/sase/ace/tui/repro/invariants.py`) against the *observed* bundle.

That fourth point is the important mental model: a captured bundle is a fixture input, not the final verdict. The
fixture loader rebuilds synthetic `Agent` objects from serialized `ReproAgentRow` fields, current code applies the real
Agents-tab merge/fold/finalize path, and only then does the invariant checker inspect the projection. This is why a
fixture may fail `check_bundle_invariants(load_bundle(path))` directly but pass `sase repro replay path --assert-stable`
after the product code is fixed.

The verdict string is one of:

- `current code fixed for the captured Agents-tab bug class` — all invariants passed.
- `current code is not fixed for the captured Agents-tab bug class: <codes>` — one or more failures.
- `legacy control …` variants when called with `merge_mode="legacy_replace"` (test-only entry point; the CLI
  always runs in `current` mode).

Flags:

- `<path>` — bundle JSON file or the directory containing `agents_tab_repro.json` (resolved via
  `_resolve_bundle_path`).
- `--assert-stable` — return a non-zero exit code when invariants fail. Without it, the process exits 0 even on
  failure (`return 0 if result.ok or not assert_stable else 1` at `cli.py:58`). Agents that want CI-grade
  behavior must pass this flag.
- `--write-artifacts <dir>` — write per-step screen text (`<step_id>.txt`) and SVG (`<step_id>.svg`) for human
  review or diffing. Filenames are sanitized via `_safe_filename`.
- `--size WIDTHxHEIGHT` — headless terminal size for the Textual app (default `120x40`). Visible-row count
  depends on this, so use the size the bundle was originally captured with when possible.
- `--json` — emit the stable JSON verdict (`result`, `verdict`, `failed_invariants[]`, `state_steps[]`,
  `screen_paths`, `screenshot_paths`).

The directory form is intentionally simple: if `<path>` is a directory, replay reads `<path>/agents_tab_repro.json`;
otherwise it treats `<path>` as the JSON file itself. `--write-artifacts` writes one text screen dump and one SVG per
replayed step, with sanitized filenames derived from `step_id`.

### Assertions In Bundles

`ReproAssertions` currently has two fields:

- `expected_visible_identities_by_step` — optional fixed projections keyed by `step_id`. These let a fixture preserve
  the originally captured broken projection while still defining what current code should produce after replay.
- `stable_step_ids` — a sequence of steps that should converge to the same visible identities and selected identity.

The committed fixture at `tests/ace/tui/repro/fixtures/agents_tab_disappear_reappear_v1.json` demonstrates this model.
Its raw captured `step_c_tier1_post_complete_broken` and repeat step contain only the current Tier 1 row, so direct
invariant checking reports `post_complete_incomplete_shrink` and `expected_visible_mismatch`. Replay against current
code preserves the Tier 2 historical workflow rows, matches the expected projection, and passes.

### Invariants Replay Checks

`check_bundle_invariants` in `src/sase/ace/tui/repro/invariants.py` emits failures with stable `code` strings.
These are the named bug classes the harness exists to gate:

- `duplicate_visible_identity` — the same `(agent_type, cl_name, raw_suffix)` appears twice in `_agents`.
- `unknown_visible_identity` — a visible row has no row summary in any captured step.
- `post_complete_incomplete_shrink` — once full history loaded, a later incomplete (Tier 1) load hid rows that
  were not dismissed. This is the original Tier 1/Tier 2 oscillation bug.
- `duplicate_visible_root` — two root rows share `(cl_name, raw_suffix)` after merge.
- `visible_child_without_parent` — a workflow/child row is visible without a visible parent and is not in
  `flattened_parent_timestamps`.
- `selected_identity_not_visible` — the selected identity is not in the visible set.
- `selected_identity_not_preserved` — selection moved off a still-visible identity without a documented
  `selection_fallback` record.
- `selection_fallback_target_mismatch` / `selection_fallback_source_mismatch` — fallback markers disagree
  with the actual selection transition.
- `replay_refresh_not_stable` — across `stable_step_ids`, the visible set or selection drifted.
- `expected_visible_unknown_step` / `expected_visible_mismatch` — bundle assertions reference a step or
  visible projection that the replay did not produce.
- `stable_unknown_step` — a stability assertion references a missing step id.

## The In-TUI Capture Path (No CLI Needed)

The CLI is one of two coordinated entry points. The other lives inside a running `sase ace` session and is the
one that actually catches the bug class the harness exists for, because the failure depends on long-lived TUI
state that out-of-band capture cannot reconstruct.

Keys (Agents tab only; see `src/sase/default_config.yml:172` leader prefix `comma`, and
`src/sase/default_config.yml:198-199`):

- `<leader>R` (i.e. `,R`) — `action_capture_agents_repro` in `src/sase/ace/tui/actions/repro.py:14`. Flushes the
  capture ring buffer to a unique directory under `~/.sase/repros/` (or `$SASE_HOME/repros/` if set, or the
  `repro_output_dir` config value). The directory name encodes timestamp, reason (`manual`), the ring's
  `repro_id`, and a per-capture uuid. Commit-safe redaction is on by default.
- `<leader>T` — `action_toggle_agents_repro_checks`. Enables continuous invariant checking on every loader
  apply. On the first violation in a burst, the ring auto-flushes a bundle and marks the burst active, so subsequent
  failing applies do not overwrite or spam captures. When a later clean projection has no latest-step failures, the
  burst flag clears and the next violation can auto-capture again (see
  `maybe_auto_capture_agents_tab_violation` in `src/sase/ace/tui/repro/capture.py:268`).

Both actions only run while the TUI is focused on the Agents tab and surface a toast (`self.notify(...)`) with
the bundle path or an error reason.

In-TUI captures include richer data than the out-of-band path: the live screen text + SVG screenshot
(`_capture_screen` in `capture.py:450`), the actual `_dismissed_agents` set the app is using, fold-manager
state, grouping mode, search query length, refresh flags, and the rolling sequence of loader/apply pairs from
the ring buffer (default capacity 120 steps).

If manual capture is invoked before a ring has recorded any loader cycle, `capture_agents_tab_repro_bundle` creates a
ring and records a `manual_flush` projection from the current app state. That makes `,R` useful even when capture was
not pre-enabled, although the richest bundles come from a ring that has already observed the preceding refreshes.

## Why It Is Useful

The Agents-tab bug class — agents that disappear, reappear, render duplicate roots, lose their parents, or
shift selection unexpectedly — is genuinely hard to reproduce because it requires the **interaction** between:

- a large local `~/.sase` artifact corpus that no clean agent workspace has;
- an artifact-index file whose freshness diverges from source-scan truth;
- a long-lived `AceApp` with `_agents_seen_complete_history=True`, dismissed/revived state, scheduled refresh
  flags, and an existing selection;
- a refresh schedule that fires while the index is stale, producing a Tier 1 incomplete load *after* a Tier 2
  reconcile.

A screenshot proves the symptom but discards the loader inputs. A unit test proves one hypothesized cause but
may miss the actual interleaving. `sase repro` closes that gap by recording the loader sequence and the
post-apply projection in one structured artifact that another agent can replay headlessly, and by gating that
replay on named, stable invariant codes that map directly to the user-visible failure modes.

It is also the durable regression bed for the tales in `sdd/tales/202605/agent_tier_merge_watermark.md` and
`agent_tier_merge_dedup_backstop.md`: once a real failure is captured, the bundle becomes a fixture and the
replay test prevents the bug from returning.

## Usage Guide

### For Users (Bryan, in the running TUI)

1. When the Agents tab looks wrong (rows missing, duplicates, broken selection):
   - Press `,R` to flush a bundle to `~/.sase/repros/<timestamp>-manual-<repro_id>-<capture_id>/`.
   - The toast shows the bundle path. Share that path with an agent or attach to a bead.
2. For sessions where the failure is intermittent, press `,T` to turn on continuous invariant checking.
   The first time a violation fires, an auto-capture lands at the same directory and a warning-severity toast
   surfaces. After that, duplicate auto-captures are suppressed until a clean projection clears the current
   violation burst.
3. To inspect a bundle locally, run `sase repro replay <bundle-dir> --write-artifacts ./out` and open the
   per-step `.svg` files (or the `.txt` screen captures) to compare before/after refresh shapes.

### For Agents Investigating A Bug

When the user shares a bundle directory:

```bash
sase repro replay <bundle-dir> --assert-stable --json
```

Read the JSON `verdict` and `failed_invariants[]`. Each failure has a stable `code` (see the invariants list
above) and a `step_id` so the agent can correlate the failure with one specific tier sequence step. The
`state_steps` array carries the post-apply visible identities for each replayed step, which is the right
diagnostic input — not the screen text.

When investigating without a user-provided bundle (for example, on a fresh agent workspace where the bug is
not visible), capture a baseline:

```bash
sase repro capture agents-tab --output /tmp/agents-tab-baseline --json
sase repro replay /tmp/agents-tab-baseline --assert-stable
```

Out-of-band capture will not reproduce the long-lived-TUI bug class on its own, but it does verify the local
loader path is healthy on this machine before chasing the live failure.

### For Agents Authoring Fixes

1. Run replay before any change to capture the failure profile:
   `sase repro replay <bundle> --json > before.json`.
2. Make the change in `src/sase/ace/tui/actions/agents/` (the apply/merge layer) or
   `src/sase/ace/tui/models/agent_loader.py` (the loader contract).
3. Re-run `sase repro replay <bundle> --assert-stable`. The bug is fixed when every invariant code listed in
   `before.json` no longer appears and the exit code is zero.
4. Convert the bundle to a committed fixture only after redaction is verified: the bundle was captured with
   `commit_safe=True` by default (`manifest.commit_safe: true` in JSON), but inspect the file for any
   `cl_name` aliases that did not redact, residual absolute paths, and sensitive scalar metadata.

For a candidate committed fixture, also run the direct invariant check mentally or in a targeted test: it is acceptable
for the raw captured fixture to fail the bug-class invariants if its `assertions` encode the fixed projection and replay
passes against current code. The fixture README under `tests/ace/tui/repro/README.md` is the closest operational guide.

### Avoid

- Do **not** pass `--no-commit-safe` for bundles you intend to share or commit. The flag exists for local
  debugging only.
- Do **not** rely on out-of-band capture alone for the disappear/reappear class of bugs — the in-TUI ring
  buffer is the only path that captures the precipitating tier sequence in time.
- Do **not** add a `sase ace repro` subcommand. The `sase ace` parser consumes the next positional argv as
  the ACE query, so it would collide. `sase repro` is intentionally top-level.

## Limitations And Gaps Worth Knowing

- Only the `agents-tab` capture target is implemented today. Other TUI surfaces (Hooks, Comments, Mentors,
  axe) do not have a repro bundle path. Adding new capture targets means a new `capture_subparsers` entry in
  `parser_repro.py` and a parallel schema/invariant module.
- Out-of-band capture (`sase repro capture agents-tab`) is *not* the same data as in-TUI capture. It produces
  exactly two steps (Tier 1 then Tier 2 against the current filesystem) and tags itself
  `capture_mode=out_of_band`. The in-TUI ring buffer can produce dozens of steps spanning real refresh
  cycles. The replay code path is the same; the diagnostic signal is not.
- The CLI has no `snapshot-home` subcommand yet (the harness research recommended one). High-fidelity
  investigations that need the real loader to operate against a sanitized copy of `~/.sase` still require
  manual `SASE_HOME=…` redirection.
- The replay harness patches dismissed-agent loading to empty and the fixture loader returns an empty
  `dismissed_from_loader`. The bundle records `dismissed_identities`, but replay does not currently rehydrate them into
  the app before applying fixture steps. Bugs that depend on dismissed/revived state need additional replay support.
- `flattened_parent_timestamps` exists in the schema and invariant checker, but the current capture helpers populate it
  as an empty list. Parent/child flattening exceptions are therefore expressible in hand-built fixtures but not fully
  auto-captured from live fold state yet.
- `selection_fallback` is schema- and invariant-aware, and redaction handles it, but the current capture and replay
  snapshot paths do not populate fallback markers. Today, an intentional selection move can still look like
  `selected_identity_not_preserved` unless a fixture author adds the marker.
- Commit-safe redaction is defensive, not exhaustive. It hashes `cl_name` and shortens path-like metadata strings, but
  keeps operational fields such as `raw_suffix`, `status`, `pid`, `workspace_num`, `tag`, `workflow`, `step_type`, and
  provider metadata. Review before committing or sharing.
- The bundle format is currently a single JSON file plus optional screen artifacts (`screen.svg` for in-TUI capture,
  replay artifact SVG/TXT files when requested), not the multi-file directory layout proposed in the original harness
  research.

## Test And Fixture Surface

The repro command is covered by a focused test cluster under `tests/ace/tui/repro/`:

- `test_repro_cli.py` covers parser wiring, JSON output, artifact writing, error payloads, and out-of-band redaction.
- `test_agents_tab_replay.py` runs the committed fixture through both current replay and `legacy_replace` control mode.
- `test_invariants.py` locks down stable failure codes and assertion semantics.
- `test_capture_ring.py` and `test_in_tui_capture.py` cover the bounded ring, manual capture, and one-capture-per-burst
  auto-capture behavior.

The fixture README documents the intended operator loop:

```bash
sase repro replay tests/ace/tui/repro/fixtures/agents_tab_disappear_reappear_v1.json --assert-stable --json
sase repro replay <bundle> --assert-stable --json --write-artifacts <dir>
sase repro capture agents-tab --output /tmp/sase-agents-tab-capture --commit-safe --json
```

## References

- CLI parser: `src/sase/main/parser_repro.py`
- Dispatch: `src/sase/main/entry.py:251`, `src/sase/main/repro_handler.py`
- CLI handlers: `src/sase/ace/tui/repro/cli.py`
- Bundle schema: `src/sase/ace/tui/repro/schema.py`
- Capture (in-TUI + out-of-band): `src/sase/ace/tui/repro/capture.py`
- Replay harness: `src/sase/ace/tui/repro/replay.py`
- Invariants: `src/sase/ace/tui/repro/invariants.py`
- Redaction: `src/sase/ace/tui/repro/redact.py`
- TUI actions / keybindings: `src/sase/ace/tui/actions/repro.py`,
  `src/sase/default_config.yml:198-199`
- Original harness design: `sdd/research/202605/agents_tab_reproduction_harness.md`
