---
create_time: 2026-07-06 06:36:41
status: done
prompt: sdd/prompts/202607/mode_switch_sync_dev_checkouts.md
---
# Sync Existing Dev Checkouts With Upstream During PyPI → Dev Mode Switch

## Problem

When the `m` (switch) keymap on the "Updates" tab of the SASE Admin Center is used to switch from PyPI (managed)
installs to Dev (editable) installs, existing dev checkouts are reused **as-is** — they are never fast-forwarded to the
upstream branch (i.e. no `git pull` equivalent runs). The user ends up with editable installs built from whatever stale
commit each repo happened to be sitting on.

### Confirmed diagnosis

The suspicion is correct. The full chain:

1. The `m` keymap (`plugins_browser_pane.py`, binding `("m", "switch_mode", ...)`) invokes
   `ModeSwitchActionsMixin.action_switch_mode` in `src/sase/ace/tui/modals/plugins_browser_mode_switch.py`, which plans
   via `sase.mode_switch.plan.plan_mode_switch` and executes via `sase.mode_switch.execute.execute_mode_switch`.
2. In `plan_mode_switch` → `_plan_to_dev` → `_dev_package_row` (`src/sase/mode_switch/plan.py`), an **existing**
   checkout gets `repo_action="reuse"` and the only repo command planned is `git fetch --quiet --tags` (kind
   `git_fetch`). A **missing** checkout gets a fresh `git clone` (which _is_ current — this is why the bug only bites
   reused checkouts).
3. `execute_mode_switch` (`src/sase/mode_switch/execute.py`) runs exactly the planned commands: fetch/clone per repo,
   then the `uv tool install --force --reinstall -e ...` editable set, then `just rust-install-uv-tool`. Nothing ever
   moves the working tree forward, so the editable installs and the Rust core rebuild are all built from the stale HEAD.
4. Compounding the confusion, `_target_dev_version` probes the **existing checkout's HEAD** to compute the plan's
   "target version", so the confirm modal faithfully advertises the stale version as the switch target.

The same gap affects the CLI path (`sase update --to dev` in `src/sase/main/update_handler.py`), which shares
`plan_mode_switch`/`execute_mode_switch`, so fixing the shared planner/executor fixes both frontends at once.

### Root cause

The mode-switch planner was written to _fetch_ (update refs for accurate version display) but never adopted the sync
semantics of the sibling dev-update flow. The dev-update flow (`src/sase/dev_update/plan.py` + `execute.py`, used when
you're already in dev mode) already does this correctly and safely: `fetch_git_upstream` → preflight (clean, has
upstream, not detached/diverged/ahead) → `merge_git_ff_only(root, upstream)` → reconcile (reinstall editables / rebuild
Rust core). The mode-switch flow simply never got the merge step.

Note: this is all Python-side self-update machinery in this repo (`sase.mode_switch`, `sase.dev_update`,
`sase.version._git`). No `sase-core` (Rust) changes are involved.

## Design

Mirror the dev-update flow's fast-forward semantics inside the mode-switch planner, keeping planning side-effect-free
and execution driven purely by planned commands.

### 1. Plan a fast-forward merge for reusable checkouts (`src/sase/mode_switch/plan.py`)

In `_dev_package_row`, when the checkout exists:

- Classify the checkout **once** with `classify_git_upstream` (today it is classified inside `_checkout_warning`;
  refactor so the row builder classifies once and derives both the warning and the sync decision from the same
  `GitUpstreamStatus`).
- **Safe to sync** (attached HEAD, has upstream, not dirty, not diverged, not ahead): plan the existing `git_fetch`
  command followed by a new command, kind `git_merge_ff`: `git merge --ff-only <upstream>` with `cwd=<checkout>`. Plan
  it even when the checkout looks up-to-date at plan time — the plan-time ahead/behind counts are pre-fetch and
  therefore stale; `merge --ff-only` after the fetch is an idempotent no-op when already current. Align the fetch
  arguments with `fetch_git_upstream` semantics (`--force`, scoped to the tracked remote/branch when known) so tag moves
  and the upstream ref are reliably updated before the merge.
- **Not safe to sync** (dirty, detached, diverged, ahead of upstream, or no upstream): keep today's behavior — fetch
  only, reuse as-is — and keep surfacing the existing warning (`"checkout has local changes; reused as-is"` etc.) so the
  user knows why no sync happened. This intentionally matches the dev-update flow's skip rules; we never rebase, stash,
  or switch branches on the user's behalf.

Note the branch semantics explicitly: we fast-forward the checkout's **current branch to its configured upstream**
(normally `origin/master` for these managed clones), exactly like the dev-update flow — we do not force a checkout of
master on repos deliberately left on another branch (those are "ahead/diverged/no upstream" cases and are warned
instead).

### 2. Honest target version in the preview

Update `_target_dev_version` so that when a sync is planned, the target version is probed at the **upstream ref**
(`probe_git_metadata_at_ref(checkout, upstream)`, as `dev_update.plan._latest_version` does) instead of stale HEAD.
Best-effort caveat: this is still the pre-fetch upstream ref, but it is strictly more honest than advertising the stale
working-tree version as the target.

### 3. Model + wiring updates

- `src/sase/mode_switch/models.py`: extend `CommandKind` with `"git_merge_ff"`.
- `src/sase/mode_switch/execute.py`: no structural change needed — non-`uv_tool_install` kinds already run through
  `_run_command`, and a failed merge already fails the switch with the restore hint. Verify command ordering stays:
  per-repo fetch → merge, all before `uv_tool_install` and the Rust rebuild.
- Rendering (`render.py`, TUI confirm modal `_mode_switch_details`) is generic over commands and needs no changes; the
  new merge commands will show up in the numbered command list / `run:` lines automatically. JSON output
  (`_command_json`) picks up the new kind for free.

### 4. Tests

Extend `tests/mode_switch/test_plan.py` (build tiny real git repos in `tmp_path`, or monkeypatch the classifier) to
cover:

- Existing clean checkout tracking an upstream → plan contains `git_fetch` then `git_merge_ff`
  (`git merge --ff-only <upstream>`, correct `cwd`), both ordered before `uv_tool_install`; row target version reflects
  the upstream ref.
- Dirty / detached / diverged / ahead / no-upstream checkout → no `git_merge_ff` command, existing "reused as-is"
  warning preserved.
- Fresh clone path → `git_clone` only, no merge (unchanged behavior).

Add execute-side coverage (currently there are **no** tests for `execute_mode_switch`): a new
`tests/mode_switch/test_execute.py` with an injected `run_command_fn`/`run_uv_fn` asserting the merge command is
executed in order, and that a failing `--ff-only` merge fails the switch with the restore-hint error.

### 5. Docs / help

Check the Updates-tab help popup and any `sase update --to dev` help text for wording that should mention existing
checkouts being fast-forwarded to upstream during the switch; update if present (per the ace help-popup maintenance
rule).

## Scope and non-goals

- No change to the PyPI-direction switch, the dev-update flow, or clone behavior.
- No rebase/stash/branch-switch automation for unclean checkouts — warn and reuse as-is, same as the dev-update flow.
- No `sase-core` (Rust) changes.

## Verification

- `just check` (lint, mypy, tests).
- Targeted: `pytest tests/mode_switch/ tests/dev_update/`.
- Manual sanity: with a dev checkout intentionally reset behind `origin/master`, run `sase update --to dev --dry-run`
  (plan shows the merge command and upstream target version), then the real switch, and confirm the checkout
  fast-forwarded and the installed editable version matches upstream. Repeat with a dirty checkout to confirm the
  warn-and-reuse path.
