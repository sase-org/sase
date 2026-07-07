---
create_time: 2026-07-06 23:42:26
status: done
prompt: sdd/prompts/202607/telegram_launch_buttons_sharded_artifacts.md
---
# Fix Missing Fork/Wait/Kill/Retry Buttons on Telegram Launch Messages

## Problem

When agents are launched from Telegram, the "🚀 ... Launched" notification no longer includes the inline keyboard (🍴
Fork, ⏳ Wait, 🗡️ Kill, 🔄 Retry buttons) or the italic `@<agent-name>` line. The `kill-<agent>` pending action is also
never registered, so the agent cannot be terminated from Telegram at all. Launches that carry an explicit
`#name:`/planned name still get buttons, which made the breakage look intermittent.

## Root Cause (diagnosed, confirmed with logs + on-disk state)

The launch keyboard in `sase-telegram` (`src/sase_telegram/scripts/sase_tg_inbound.py`, `_send_launch_notification`) is
only built when an agent name is known. For auto-named launches, `AgentLaunchResult.agent_name` is intentionally unset
(naming is owned by the spawned child), so the plugin falls back to `_resolve_launch_result_agent_name`, which polls
`agent_meta.json` in the launch's artifacts directory for up to 8 seconds.

That poll path is derived by `_launch_result_artifacts_dir`:

1. It first tries `getattr(result, "artifacts_dir", None)` — but `AgentLaunchResult` (`sase` repo,
   `src/sase/agent/launch_types.py`) has **no `artifacts_dir` field**, so this never hits.
2. It then hand-builds the **legacy flat** path: `~/.sase/projects/<project>/artifacts/ace-run/<YYYYmmddHHMMSS>`.

Since sase commit `6cfa3b171` ("feat: add sharded agent artifact migration", 2026-06-13), ace-run artifacts live in a
**day-sharded layout** owned by the Rust core (`sase_core_rs` via `sase.core.agent_artifact_paths`,
`DAY_SHARDED_LAYOUT_VERSION = 2`): `~/.sase/projects/<project>/artifacts/ace-run/<YYYYMM>/<DD>/<YYYYmmddHHMMSS>`. All
projects on this machine are now fully sharded (only `202607/...` dirs exist under `ace-run/`), so the hand-built flat
path never exists, the poll always times out, `agent_name` resolves to `None`, and the notification is sent with
`reply_markup=None`.

Evidence:

- The telegram lumberjack log shows, for **every** recent launch (including the two in the user's screenshot, matched by
  pid): `Telegram launch fallback: result.agent_name unset and agent_meta.json poll timed out (pid=3485652, ...)`.
- The corresponding sharded artifact dirs (e.g. `ace-run/202607/06/20260706232107/agent_meta.json`) **do** contain
  claimed names (`"04"`, `"05"`, ...), written by the child within seconds of spawn — the poll was simply looking at a
  path that no longer exists.
- Existing plugin tests mask the bug: they build the launch result as a `MagicMock` and assign
  `mock_result.artifacts_dir = ...`, exercising a fast path the real dataclass can never take.

Why "all of a sudden": the layout flipped from flat to sharded on this machine when the deployed sase picked up the June
migration (the on-disk `ace-run/202607` shards appeared 2026-07-06), so every auto-named launch since then hits the dead
fallback.

Sweep result: `sase_tg_inbound.py` is the only place in any plugin repo (sase-telegram, sase-github, sase-nvim) that
hand-builds a flat `ace-run/<timestamp>` path. The core repo already has a sharded-aware helper,
`artifact_dir_for_launch(result)` in `src/sase/integrations/_mobile_agent_launch.py`, but it is private to the mobile
gateway.

## Fix Design

Two-repo fix, respecting the core-owns-paths boundary (path canonicalization stays behind the existing
`sase.core.agent_artifact_paths` wrappers over the Rust core; no `sase-core` changes needed).

### 1. sase repo — make the launch result self-describing

- **Promote a public helper** for "artifacts dir of a launch": add
  `launch_artifacts_dir(project_name, timestamp) -> str` next to `convert_timestamp_to_artifacts_format` in
  `src/sase/artifacts.py` (or a small `sase/agent/launch_artifacts.py`), implemented on
  `canonical_agent_artifact_path(project, "ace-run", converted_timestamp)`. Rewire
  `_mobile_agent_launch.artifact_dir_for_launch` to delegate to it so there is exactly one implementation.
- **Add `artifacts_dir: str = ""` to `AgentLaunchResult`** (`src/sase/agent/launch_types.py`) and populate it in
  `launch_spawn.py` when constructing the result (project name and timestamp are already in scope there). This makes
  every downstream consumer (Telegram, mobile gateway, future frontends) independent of layout details, and it lights up
  the plugin's existing `getattr(result, "artifacts_dir", ...)` fast path without any plugin-side coupling.
- Unit tests: the new helper returns the sharded canonical path; `launch_spawn` results carry an `artifacts_dir` that
  matches where the child actually creates its artifacts (same derivation as
  `create_artifacts_directory("ace-run", project_name=..., timestamp=...)`).

### 2. sase-telegram repo — sharded-aware fallback + diagnosability

- In `_launch_result_artifacts_dir`, keep the `result.artifacts_dir` fast path, but replace the hand-built flat path in
  the fallback with
  `sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path(project_name, "ace-run", artifacts_timestamp)`,
  which resolves whichever layout exists on disk (legacy flat or day-sharded) and falls back to the canonical path. This
  keeps the plugin correct against both an updated sase (field present) and an older sase (fallback still resolves), and
  against un-migrated flat trees.
- Include the polled path in the "poll timed out" warning so a future recurrence is diagnosable from the lumberjack log
  without spelunking.
- Tests (fix the masking blind spot):
  - Build the fake launch result from the **real** `AgentLaunchResult` dataclass (no `MagicMock` attribute inventions).
    One test with `artifacts_dir` populated; one _without_ it (older-sase shape) exercising the timestamp fallback.
  - Regression test: create a tmp projects root with a **day-sharded** `ace-run/<YYYYMM>/<DD>/<ts>/agent_meta.json`, run
    the launch-notification flow, and assert the Fork/Wait/Kill (and Retry) keyboard rows and the `kill-<agent>` pending
    action are produced.

### Explicitly out of scope

- Poll timeout tuning: the child writes `agent_meta.json` with its claimed name within a couple of seconds of spawn
  (before any workspace-heavy workflow steps), so the existing 8s window is fine once the path is correct.
- The mobile gateway (`_mobile_agent_launch.py`) already computes sharded paths correctly; it only gets the
  delegate-to-shared-helper refactor.

## Validation

- `just check` in both repos.
- Existing sase-telegram inbound tests (`tests/test_inbound.py` launch-keyboard tests) still pass after switching to
  real `AgentLaunchResult` instances.
- End-to-end after deploy: launch an auto-named agent from Telegram and confirm the launch message carries the `@<name>`
  line and the Fork/Wait/Kill/Retry keyboard, and that the lumberjack log shows no "launch fallback ... poll timed out"
  warning.

## Risks

- Low. The core change is an additive dataclass field plus a helper promotion; the plugin change swaps a dead path
  derivation for the canonical resolver already used everywhere else since the migration. The plugin keeps a working
  fallback for older sase versions, and `resolve_agent_artifact_timestamp_path` explicitly supports both layouts.
