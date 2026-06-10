---
create_time: 2026-06-09 20:11:53
status: done
---
# Fix: Live Diff not shown for running agents in the ACE TUI Agents tab

## Problem

In the `sase ace` TUI **Agents** tab, the **Live Diff** panel for a running agent is missing most of the time.
Occasionally it does appear (intermittent), which has made the bug confusing to pin down.

## Root cause (confirmed empirically)

The TUI computes the _wrong workspace directory_ for running agents, so it diffs an unrelated checkout (or nothing)
instead of the workspace the agent is actually editing.

Flow today (`src/sase/ace/tui/widgets/file_panel/_diff.py`):

1. `get_agent_diff(agent)` → `_compute_diff_cache_key` → `_resolve_workspace_dir(agent)`.
2. For numbered-workspace agents, `agent.workspace_dir` is **None** (it is only persisted for _home-mode_ `ace(run)`
   agents, not for agents running in numbered project workspaces — confirmed: the latest `sase` project
   `agent_meta.json` has `workspace_num: 11` but no `workspace_dir`).
3. So resolution falls back to `_derive_workspace_dir_from_primary(primary, num)`, which hardcodes `f"{primary}_{num}"`
   — e.g. `/home/bryan/projects/github/sase-org/sase_11`.
4. But the agent actually runs in `/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_11` (verified via the
   live agents' `/proc/<pid>/cwd`).

The naive `{primary}_{N}` heuristic only matches the **legacy `adjacent`** workspace-root policy. The current/default
policy is **`xdg-state`** (`DEFAULT_WORKSPACE_ROOT = "xdg-state"` in `src/sase/workspace_provider/store.py`), under
which the canonical resolver `WorkspaceStore.resolve(num).checkout_dir` returns
`<xdg-state>/<project_key>/<basename>_<N>/` — i.e. the real `.local/state/...` path.

The TUI re-implements workspace-path logic and has drifted from the canonical resolver. Worse: stale leftover
`projects/github/sase-org/sase_<N>` directories from the old `adjacent` layout still exist on disk, so
`_existing_workspace_dir()` accepts the wrong path instead of returning `None`. The TUI then runs `git diff HEAD` in
that stale checkout (often a different branch with no uncommitted changes) → empty diff → `get_agent_diff` returns
`None` → `FileVisibilityChanged(has_file=False)` → the Live Diff panel stays hidden. (The downstream display/visibility
plumbing in `file_panel/__init__.py` and `_agent_detail_panels.py` was audited and is correct; the failure is purely in
workspace resolution.)

**Why it is intermittent ("sometimes I see it working"):**

- _Home-mode_ `ace(run)` agents persist `workspace_dir` (in `running.json` / `agent_meta.json`), so resolution
  short-circuits on `agent.workspace_dir` and the diff shows correctly.
- _Primary `#0`_ agents resolve to the primary dir unchanged (correct under any policy).
- _Numbered-workspace project agents_ (the common case) hit the broken derivation → no diff. This is the majority,
  matching "most of the time it's missing."

This also aligns with `memory/short/rust_core_backend_boundary.md`: workspace path resolution is shared backend
behavior; the TUI should call the canonical resolver, not a private heuristic. The canonical resolver already lives in
Python (`WorkspaceStore`), so no Rust-core change is required.

## Goals

- Running numbered-workspace agents show their Live Diff reliably, updating as the agent edits files.
- No behavior change for home-mode agents, primary `#0` agents, or DONE/FAILED agents (which already use `diff_path`).
- The TUI resolves workspaces the same way the runner does, honoring the configured `workspace.root` policy (`xdg-state`
  default, `adjacent` legacy, absolute / env override) so the two can never drift again.
- No new latency on the j/k hot path and no filesystem side effects (must not clone / materialize a workspace just to
  render a diff).

## Approach

### 1. Primary fix — resolve via the canonical `WorkspaceStore` (consumer side)

In `src/sase/ace/tui/widgets/file_panel/_diff.py`, replace the hardcoded `_derive_workspace_dir_from_primary` heuristic
with a call to the canonical, **pure** resolver:

- Build a `WorkspaceStore(primary_workspace_dir, config=<loaded config>)` and return
  `store.resolve(workspace_num).checkout_dir`.
- `WorkspaceStore.resolve()` is documented as pure (creates no directories) and already handles primary `#0`, legacy
  `1`, `adjacent`, `xdg-state`, absolute, and the `SASE_WORKSPACE_ROOT` override — so all policies are covered for free.
- Pass the same merged config the runner/CLI uses (the CLI builds the store with `config=load_config()` /
  `load_merged_config()`), so `workspace.root` and `workspace.project_key` overrides are honored. The exact loader
  import will be pinned during implementation to match existing call sites.
- Keep the existing `_existing_workspace_dir()` guard so a not-yet-materialized managed workspace still degrades to
  `None` gracefully.
- Do **not** use `ensure_workspace_checkout` / `get_workspace_directory`, which can materialize (clone) and invoke
  provider plugins — too heavy and side-effecting for a diff render.

**Performance:** `WorkspaceStore.__init__` may shell out to `git remote` to derive the project key. Diff fetches already
run on a background worker (not the UI thread), but to avoid repeating that work every fetch, cache the constructed
`WorkspaceStore` (or the resolved checkout path) in a small module-level dict keyed by `primary_workspace_dir`, guarded
by a lock (mirroring the existing `_diff_cache` pattern in this file).

This single change fixes **currently-running** agents immediately (no relaunch needed), because resolution happens live
in the TUI.

### 2. Secondary hardening — persist `workspace_dir` for numbered-workspace agents (producer side)

Home-mode already writes `workspace_dir` into its run marker / `agent_meta.json`. Numbered-workspace agents do not,
which is what forces the fragile fallback. Have the agent runner persist its already-known `workspace_dir` (available as
`AgentExecContext.workspace_dir`) into `agent_meta.json` for all agents. The TUI's `enrich_agent_from_meta` already
reads `data.get("workspace_dir")`, so no consumer change is needed — `agent.workspace_dir` simply becomes populated,
letting `_resolve_workspace_dir` short-circuit with zero resolution cost and zero possibility of drift.

This is forward-looking (helps agents launched after the change) and makes the system robust even if the resolver and
runner config ever diverge again. It is complementary to fix #1, not a replacement: #1 is required to fix agents that
are already running and any agent whose meta lacks the field.

### 3. Tests

- Unit tests for the new resolver helper in `_diff.py`:
  - `xdg-state` policy → returns the `<state-root>/<key>/<basename>_<N>` path (the real location), given a fake primary
    dir + config; assert it is **not** `{primary}_{N}`.
  - `adjacent` policy → still returns `{primary}_{N}` (no regression for legacy setups).
  - `workspace_num` `None`/`0`/`1` → primary dir.
  - Non-existent resolved dir → `None` (via `_existing_workspace_dir`).
  - Caching: store constructed once per `primary_workspace_dir` (e.g. assert the `git remote`/constructor path runs once
    across repeated calls).
- A `get_agent_diff` integration-style test with a temp git repo at the _resolved_ path containing uncommitted changes →
  returns the diff; with changes only at the stale `{primary}_{N}` path → does **not** return the stale diff.
- If feasible, a regression test asserting `agent.workspace_dir=None` + `xdg-state` config resolves to the managed path
  rather than the adjacent one.

## Files in scope

- `src/sase/ace/tui/widgets/file_panel/_diff.py` — replace `_derive_workspace_dir_from_primary` with
  `WorkspaceStore`-based resolution; add store/path cache. (primary fix)
- Agent runner meta-writing path (where `agent_meta.json` is written for numbered-workspace agents) — add
  `workspace_dir`. (secondary hardening; exact module pinned during implementation — mirrors the home-mode
  `running.json` writer)
- Tests under `tests/` mirroring the file-panel diff tests.

## Out of scope / non-goals

- No change to the file-panel display, visibility, caching cadence, or trim logic (audited and correct).
- No change to DONE/FAILED diff handling (uses `diff_path`).
- No Rust-core change (the canonical resolver already exists in Python).
- Not changing the refresh interval / stale-threshold behavior (a separate latency concern, not the cause of the missing
  diff).

## Validation

- `just install` then `just check` (lint + mypy + tests) in this workspace.
- Manual: with multiple numbered-workspace agents running, open `sase ace`, select a running agent that is editing
  files, and confirm the Live Diff panel appears and updates.
- Confirm home-mode and primary-`#0` agents still show diffs (no regression).

## Risks & mitigations

- _Latency from `git remote` in `WorkspaceStore.__init__`_: mitigated by the per-primary store cache and by running on
  the background diff worker, not the UI thread.
- _Config drift between TUI and runner_: mitigated by loading the same merged config the CLI uses; secondary fix (#2)
  removes reliance on resolution entirely for new agents.
- _Wrong loader/config_: pin the import to an existing `WorkspaceStore(..., config=...)` call site during implementation
  to guarantee parity.
