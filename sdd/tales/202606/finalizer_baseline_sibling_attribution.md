---
create_time: 2026-06-20 14:48:01
status: wip
prompt: sdd/prompts/202606/finalizer_baseline_sibling_attribution.md
---
# Plan: Attribute sibling commits by run-start baseline, not just the "opened" marker

## Summary

The commit finalizer **again** silently left an agent's real work uncommitted. Agent `02g` (`02g`, codex / `gpt-5.5`,
run `~/.sase/projects/bob-cli/artifacts/ace-run/202606/20/20260620142413`) edited three files in the `bob-plugins`
sibling repo (`plugins/bob-vim-surround/main.js`, `.../manifest.json`, `README.md`) inside
`…/workspaces/bobs-org/bob-plugins/bob-plugins_11`, but the finalizer reported `status: clean / reason: no_changes` and
committed nothing. The user had to commit the work by hand (`ddbc33e "chore: Fix vim-surround issues"`).

**Root cause (proven below): the agent never ran `sase workspace open`.** It located `bob-plugins_11` by listing the
workspace directory and edited it directly. Because the finalizer decides _which_ sibling repos are committable purely
by the **opened-sibling marker** (`opened_siblings.json`, written only by `sase workspace open`), and that marker was
never created, the finalizer treated the run as having touched no siblings. This is a **different** failure from the one
the prior fix (`7d9f0036f`) addressed — that fix made the _recorded path_ authoritative for **config drift**, but it
still fundamentally requires a marker to exist. `02g` created no marker, so the prior fix could not help.

The opened-marker is a **proxy** for "did this run touch the sibling," and the proxy's core assumption — codified in the
original `finalizer_opened_siblings.md` plan: _"agents MUST run `sase workspace open` … so 'opened' is, by construction,
the set of siblings an agent could have modified"_ — is **false in practice**. Agents (especially codex) routinely edit
a pre-existing numbered sibling checkout directly.

**The fix:** attribute sibling changes to a run by a signal that does **not** depend on the agent calling
`sase workspace open` or on its runtime's tool-logging fidelity: a **run-start baseline** of each suffix sibling's dirty
state. At finalize, a suffix sibling is committable if it has dirty files that were **not** dirty at run start (i.e.
changes this run introduced). This is robust to (a) agents that skip `sase workspace open`, (b) edits applied by any
mechanism (Edit tool, codex `apply_patch`, shell `sed`/`npm` build output), and (c) org renames / config drift — while
**preserving** the `db79196c8` guarantee that leftover dirt from a _different_ run never fails or hijacks this run.

## Evidence / reproduction (verified during investigation)

Subject: agent `02g`, project `bob-cli`, run `20260620142413`.

1. **Finalizer result** (`commit_finalizer_result.json`): `{"status":"clean","reason":"no_changes","changed_files":[]}`.
2. **`agent_meta.json` shows config resolved the sibling correctly** this time:
   `bob-plugins → …/bob-plugins/bob-plugins_11`, `workspace_strategy: "suffix"`. So this is **not** the config-drift
   scenario the prior fix targeted — config was healthy and the finalizer still missed the work.
3. **The agent never opened the sibling**: `grep 'sase workspace' tool_calls.jsonl` → 0 matches. There is **no
   `opened_siblings.json`** in the run's artifacts dir. The agent's own `live_reply.md` narration: _"This workspace set
   has multiple `bob-plugins__`checkouts. Since you're in`bob-cli_11`, I'm using the matching `bob-plugins_11`
   checkout"\* — i.e. it found the path by directory listing and edited it directly.
4. **The work was real**: `git -C …/bob-plugins_11 show --stat ddbc33e` (the user's manual commit, 2 min after the run)
   shows exactly the four dirty files, including a pre-existing orphan `plugins/task-status-cycler/main.js` left
   uncommitted by an _earlier_ run (`029`) — itself a prior victim of the same class of bug.
5. **Why the current finalizer misses it**: `collect_dirty_state` (`commit_finalizer_state.py`) builds the committable
   set by iterating the **opened-sibling records** (`opened_sibling_workspace_dirs(artifact_root)`); the configured
   `sibling_targets` are used only to _classify strategy_, never as an iteration source. With an empty opened set, the
   committable loop iterates nothing and returns `[]` — regardless of how dirty the configured suffix sibling is.

## Background: how committable siblings are decided today

- At launch, `sase workspace open -p <sibling> <N>` → `handle_open_clean` (`workspace_handler_list.py`) calls
  `record_opened_sibling(name, path)`, writing `opened_siblings.json` under `SASE_ARTIFACTS_DIR`.
- At finalize, `collect_dirty_state(project_dir, artifact_root)`:
  - `sibling_targets = _configured_sibling_targets(...)` (env `SASE_SIBLING_REPOS_JSON`, else config resolution),
  - `opened_workspace_dirs = opened_sibling_workspace_dirs(artifact_root)` (name → recorded path),
  - `_dirty_configured_sibling_repos(...)` iterates **opened_workspace_dirs**, skips `none`-strategy, runs
    `git_changed_files` on the recorded (or config-fallback) path, and emits `DirtyRepo(kind="sibling")` for dirty ones.
  - `_dirty_configured_advisory_sibling_repos(...)` handles `none`-strategy siblings (chezmoi), config-driven, **not**
    gated by opened markers.
- Net: **committable suffix siblings are gated entirely on the opened marker.** No marker ⇒ nothing committable.

The original gating (`db79196c8`) existed to fix a real **false positive**: the `research.u.image` agent _failed_
finalization because `sase-nvim_10` was dirty — but the dirt belonged to a **different**, abnormally-terminated run that
shared numbered slot 10. Gating by "opened" stopped leftover dirt in a reused slot from failing an unrelated run. That
guarantee must be preserved.

## The tension to resolve

Two real failure modes pull in opposite directions:

- **False positive (`db79196c8`):** committing/failing on leftover dirt from a _different_ run in a reused numbered
  slot. Symptom: an unrelated run fails finalization. **Safe** (no data loss), and an abnormal-termination edge case.
- **False negative (this bug):** silently dropping the changes _this_ run made, because no opened marker exists.
  Symptom: real work left uncommitted, then lost when the slot is reused/cleaned. **Dangerous** (silent data loss), and
  — as we now see across the `029` and `02g` runs — a **routine** occurrence with agents that skip
  `sase workspace open`.

The opened-marker resolves the tension only if agents always create it. They do not. We need an attribution signal that
is **per-run** (distinguishes this run from prior slot occupants) yet **automatic** (independent of the agent's
behavior). The git working tree, snapshotted at run start, is exactly that signal.

## Goal

The finalizer must commit uncommitted changes in any **suffix-strategy** sibling repo that **this run** modified — even
when the agent never ran `sase workspace open` — using a run-start baseline to tell _this run's_ changes apart from
leftover dirt. It must never silently report `clean / no_changes` while leaving changes this run made behind, and it
must **not** regress `db79196c8` (leftover dirt from another run must not fail or hijack this run).

## Design

### 1. Snapshot a per-run baseline of suffix-sibling dirty state (new)

At **run start**, before the agent does anything, record the dirty file set of each configured **suffix** sibling whose
checkout already exists. Add helpers in `src/sase/sibling_repos.py` (home of `record_opened_sibling` /
`opened_sibling_*`, so the marker filename/format live in one place):

- `record_sibling_baseline()` — best-effort, mirrors `record_opened_sibling`: no-op when `SASE_ARTIFACTS_DIR` is unset
  (covers non-agent/test contexts); otherwise read suffix siblings from env (`sibling_repo_metadata_from_env`), capture
  `git status --porcelain`-derived changed files for each existing suffix checkout, and atomically write
  `sibling_baseline.json`:
  ```json
  {
    "schema_version": 1,
    "siblings": [
      {
        "name": "bob-plugins",
        "workspace_dir": "/abs/.../bob-plugins_11",
        "dirty_files": ["plugins/task-status-cycler/main.js"]
      }
    ]
  }
  ```
  Skip `none`-strategy siblings (advisory, possibly huge — e.g. chezmoi). Swallow IO/subprocess errors like the other
  finalizer artifact writers.
- `sibling_baseline(artifact_root) -> dict[str, set[str]] | None` — return name → baseline dirty-file set, or **`None`
  when the file is absent** (the absent-vs-empty distinction is load-bearing; see step 3).

**Where to call it:** in the uniform agent-exec loop, `src/sase/axe/run_agent_exec.py` `run_execution_loop`, right after
`_publish_phase_env(...)` sets `SASE_ARTIFACTS_DIR` and before the first `execute_workflow(...)` invocation, captured
**once** per run. This is the single chokepoint all runtimes pass through, so the baseline is recorded uniformly (per
the "uniform agent runtimes" convention). At that point the sibling env (`SASE_SIBLING_REPOS_JSON`) is set and the
sibling working trees are still in their pre-run state.

(Layering note: snapshotting needs a `git status` helper. `git_changed_files` lives in
`llm_provider/commit_finalizer_git.py`; `sibling_repos.py` is a lower-level module. Implement the baseline's git read
with a minimal local `git status --porcelain` call (or a small shared helper) to avoid `sibling_repos` importing
`llm_provider`. Final placement is an implementation detail.)

### 2. Make "changed during this run" a committable signal in the finalizer

In `src/sase/llm_provider/commit_finalizer_state.py`, extend committable-suffix detection so a sibling is committable if
**either**:

- it is in the opened-marker / recorded-path set (existing behavior — unchanged), **or**
- the baseline shows it gained dirty files during the run: `current_dirty - baseline_dirty` is non-empty.

Concretely, build the committable candidate universe as `configured suffix targets ∪ opened records`, and for each
candidate resolve its workspace dir (recorded path preferred, else config path — keeps the prior config-drift fix) and
compute attribution:

- `opened` (marker present) ⇒ committable (as today).
- `baseline_present and (current_dirty - baseline_dirty)` non-empty ⇒ committable (the new signal).
- otherwise ⇒ not committable here (deferred to step 3 / advisory).

`none`-strategy siblings stay on the advisory path, untouched.

This is **purely additive**: it only _broadens_ what gets committed in the marker-less / drift case. Non-drift,
properly-opened runs resolve identically. Verified against the two failure modes:

- **This bug:** baseline `{task-status-cycler/main.js}` (the `029` orphan) → finalize
  `{task-status-cycler, main.js, manifest.json, README.md}` → diff `{main.js, manifest.json, README.md}` non-empty ⇒
  **committable**. (The whole dirty tree is committed, which also sweeps up the `029` orphan — reproducing the user's
  manual `ddbc33e`.)
- **`db79196c8`:** `sase-nvim_10` dirty at launch from a different run → baseline captures that dirt → finalize shows
  the same dirt, diff empty ⇒ **not** committable ⇒ the unrelated run is **not** failed. Guarantee preserved.

### 3. Fail-safe for a missing baseline + never silently drop

- **Missing baseline (`sibling_baseline(...) is None`):** the new signal is **disabled** — fall back to opened-marker
  behavior exactly as today. This matters for backward compatibility (in-flight/old runs predating this change) and
  guarantees the absent-baseline case can never over-commit (i.e. can't reintroduce `db79196c8`). The absent-vs-empty
  distinction in step 1 is what makes this safe.
- **Defense-in-depth (recommended, separable):** when a suffix sibling is dirty but **not** attributed to this run
  (leftover-only, e.g. the long-orphaned `029` change on a run that didn't also touch the repo), surface it as
  **advisory** (visible, non-blocking) rather than dropping it silently. This is compatible with `db79196c8`'s intent
  ("don't _block_ on leftover dirt") while closing the silent-loss hole that let the `029` change rot across runs. This
  is the only behavior change for the leftover case and can ship as a follow-up if we want to keep the first change
  minimal.

## Alternatives considered (and why rejected)

- **Derive "touched" from `tool_calls.jsonl` edit records.** Attractive (no launch-time snapshot) but **fragile**: codex
  records a multi-file `apply_patch` as a single `Edit`/`MultiEdit` keeping only `paths[0]` as `file_path`
  (`_tool_call_codex.py` `_normalize_codex_tool_input`), dropping the other edited paths; shell-applied edits (`sed`,
  build output) and `cwd` are frequently unrecorded for codex. In `02g`'s log only the `README.md` edit surfaced; the
  `main.js`/`manifest.json` edits were invisible. It happens to work here but cannot be relied on across runtimes/edit
  mechanisms. The git working tree (baseline-diff) sees every change regardless of how it was applied.
- **Pure slot ownership** (commit any dirty `<sibling>_<N>` because slot N is "mine"). Simplest, but directly
  reintroduces the `db79196c8` false positive (leftover dirt from a prior slot-N run).
- **Instruction-only** (strengthen the generated agent memory that says agents MUST run `sase workspace open`). Cannot
  reliably change LLM behavior (codex ignored it here); at best a complementary mitigation, not a fix.

## Files to change

- `src/sase/sibling_repos.py` — add `record_sibling_baseline()` and `sibling_baseline(artifact_root)` (+ marker
  filename/schema constant), alongside the existing opened-sibling helpers.
- `src/sase/axe/run_agent_exec.py` — call `record_sibling_baseline()` once at run start (after `_publish_phase_env`,
  before the first `execute_workflow`).
- `src/sase/llm_provider/commit_finalizer_state.py` — add the baseline-diff committable signal (additive), with the
  missing-baseline fail-safe; advisory and main-repo paths unchanged. (Optionally: route unattributed leftover dirt to
  advisory for the defense-in-depth in step 3.)
- (If a shared low-level `git status` helper is introduced to avoid layering issues, a small new/shared util.)

## Tests

- `tests/test_sibling_repos.py`: `record_sibling_baseline` / `sibling_baseline` round-trip (name→dirty-set), no-op when
  `SASE_ARTIFACTS_DIR` unset, missing-file returns `None` (not `{}`), `none`-strategy siblings excluded, malformed file
  tolerated.
- `tests/llm_provider/test_commit_finalizer_siblings.py`:
  - **Primary regression (this bug):** suffix sibling dirty at finalize, **no opened marker**, baseline recorded with a
    _smaller_ dirty set (or empty) at run start ⇒ finalizer detects it as a committable dirty sibling and runs a
    follow-up pass (not `clean`).
  - **`db79196c8` preserved:** suffix sibling dirty, no opened marker, baseline records **the same** dirty set (leftover
    from another run) ⇒ ignored (`clean`, no follow-up).
  - **Missing-baseline fail-safe:** suffix sibling dirty, no opened marker, **no baseline file** ⇒ ignored (current
    behavior), proving absent-baseline can't over-commit.
  - Keep green: `test_dirty_configured_sibling_without_open_marker_is_ignored` may need its setup adjusted so "no
    marker" also means "no baseline / unchanged-from-baseline" to keep asserting the leftover case;
    `test_opened_dirty_sibling_*` (recorded-path / config-drift), `test_dirty_primary_sibling_checkout_is_ignored_*`,
    and the `none`-strategy advisory tests must all still pass.
  - If step 3's advisory safety net is included: a test that leftover-only dirt (no marker, baseline==current) is
    reported **advisory**, not committed, and does not block finalization.
- Per repo policy, run `just install` then `just check` (lint + mypy + tests) before completing (ephemeral workspace).

## Out of scope / follow-ups

- **Recovering lost changes**: `02g`'s edits are already committed (user's `ddbc33e`); the older `029`
  `task-status-cycler/main.js` orphan was swept into the same commit. No recovery code needed.
- **`github_orgs` staleness** (`bbugyi200` vs `bobs-org` in global config): unrelated to this bug; noted, not addressed.
- **Replacing the opened-marker entirely** with baseline-diff (it subsumes the marker for committable detection): a
  tempting simplification but a larger, higher-churn change; this plan keeps the marker as a complementary signal and
  only _adds_ the robust baseline signal.

## Risk / compatibility

- Behavior change is confined to the **committable suffix-sibling** path. Advisory and main-repo logic are untouched
  (except the optional, additive advisory-for-leftover safety net).
- The committable change only **broadens** commits in the marker-less / drift case; properly-opened and non-drift runs
  resolve identically (the new signal is gated on a real baseline diff). The missing-baseline fail-safe guarantees no
  over-commit when the snapshot is absent, so `db79196c8` cannot regress.
- Cost: one extra `git status` per existing **suffix** sibling at run start (typically 0–2), negligible against spawning
  an LLM subprocess. Python-only, agent-run-lifecycle state (like `opened_siblings.json`); no `sase-core` change per the
  backend-boundary litmus test (no other frontend mirrors this).
