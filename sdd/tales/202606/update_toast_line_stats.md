---
create_time: 2026-06-30 13:49:03
status: done
prompt: sdd/prompts/202606/update_toast_line_stats.md
---
# Plan: Per-Repo Line-Change Stats in the Post-Update Toast

## Goal

When the ACE TUI restarts after a SASE self-update (e.g. via `,U`), it shows a one-shot "post-update" toast that
currently lists per-repo **version transitions** (`name  old → new`). This plan adds **how many lines changed in each
repo** to that toast — rendered so it is _intuitive_, _reliable_, and _beautiful_.

The numbers come from a real `git diff` of what was actually fast-forward-merged, attached per repository, threaded
across the restart handoff, and rendered inline beside each repo's version transition.

## Product context & key design decisions

### What "lines added/modified/removed" means here (and why)

Git does not track a "modified line" count — a changed line is recorded as one deletion plus one insertion. The
reliable, git-native triple is **files changed**, **insertions (`+`)**, **deletions (`−`)**. We will present
**`+insertions −deletions` per repo** (the honest representation of "added/removed"), with a **files-changed** total
surfaced compactly in the toast's footer. We will not fabricate a separate "modified" number that git cannot produce —
this is core to the _reliable_ requirement.

### Which update path gets line stats (and which can't)

There are two self-update paths:

- **Dev path** (editable git checkouts): `,U` → confirm → `execute_dev_update` → `DevUpdateResult`. Each repo (host
  `sase` + linked repos such as `sase-core`, `sase-github`, `sase-telegram`, `sase-nvim`) is a local git checkout that
  is fast-forwarded. **This path has real commits to diff — line stats apply here.** This is the path used in an
  editable/dev install.
- **Managed path** (uv tool upgrade from a package index): `UpdateSummary`. Packages come from wheels; there is no local
  git history to diff. **Line stats are not computable and are simply omitted** — the toast renders exactly as it does
  today. This is intuitive: a managed update genuinely has no local diff, so showing nothing is correct rather than
  misleading.

So this feature lights up on the dev path and gracefully no-ops on the managed path.

### Where the new logic lives — Rust core boundary decision

Per the repo's `rust_core_backend_boundary` rule, shared backend/domain behavior belongs in `../sase-core`. **This
change stays in Python**, deliberately:

- The entire self-update subsystem (`src/sase/dev_update/**`, `src/sase/version/_git.py`) is already
  Python-via-subprocess git, with **no** counterpart in `sase-core`. The "shared backend" for dev updates _is_ this
  Python layer; both the CLI `sase update` renderer and the TUI consume the same `DevUpdateResult`/`DevUpdateOutcome`
  models.
- The cross-restart toast handoff (`src/sase/ace/update_receipt.py`) is explicitly documented in its own module
  docstring as TUI-restart presentation state that no CLI/web/editor/Rust API needs to share.
- A new `git diff --numstat` helper sits naturally beside the existing `fetch_git_upstream` / `merge_git_ff_only`
  helpers; reimplementing it in Rust would be an inconsistent one-off.

This decision is called out explicitly so it can be revisited if desired before implementation.

### Reliability principles

- **Stats never block or fail an update.** Every new git invocation (capture SHAs, compute diff) is best-effort: any
  non-zero exit, timeout, or parse failure yields "no stats for this repo" and the update proceeds and restarts exactly
  as today.
- **Backward/forward-compatible handoff.** The persisted receipt JSON keeps its current `format` version; the new
  diff-stat data is an _optional_ nested field. The new reader tolerates an old receipt with no stats (important: the
  very first post-feature update is _written_ by the old code and _read_ by the new code, so the new reader must degrade
  cleanly — it will, showing version transitions only). An older reader likewise ignores the new optional field. No
  format bump, no "missing toast" regression.
- **Accuracy = what actually merged.** Stats are computed from the real pre-merge HEAD vs. post-merge HEAD of each
  successfully merged root, so the numbers reflect exactly the code that was loaded on restart — not a speculative plan.

### Beautiful rendering

The toast already uses Textual `notify(markup=True)` with the Updates-tab accent, `[dim]` secondary text, a `→` glyph,
and `[bold green]` for new versions. We extend that vocabulary:

- Each repo line gains a trailing churn segment: **`+1,234`** in green and **`−567`** in a measured red, with thousands
  separators, e.g. `sase  0.5.0 → 0.6.0   +1,234 −567`.
- **Column alignment:** repo names are padded to a common width (capped, with truncation for pathological names) so the
  `→` arrows and the churn segments line up into a tidy mini-table rather than a ragged list.
- **Binary/mode-only changes:** when a repo changed files but recorded zero line insertions and deletions, show a
  compact `N files` instead of a misleading `+0 −0`.
- **No silent truncation:** plugins beyond the display cap are already summarized as `…and N more`; that line gains the
  _aggregated_ churn of the hidden repos so their changes aren't invisible.
- **Footer:** the existing tail line (`+K dependencies · Reloaded into the new version.`) gains a total files-changed
  summary when stats are present (e.g. `+2 dependencies · 18 files changed · Reloaded into the new version.`). On the
  managed path (no stats) the footer is unchanged.
- Exact accent/red hex values will be chosen for legibility on the information-severity toast background and locked in
  with a PNG visual snapshot (see Testing).

The result reads top-to-bottom as: _what updated → from/to which version → how much changed_, which is the natural
mental model.

## High-level technical design

### 1. Compute per-repo diff stats during the dev update (`src/sase/dev_update/`)

- Introduce a small frozen value type `RepoDiffStat(files_changed, insertions, deletions)` in `dev_update/models.py`,
  with a helper to tell "truly empty" apart from "binary/mode-only".
- Add a pure `numstat` parser (its own tiny function/module) that turns `git diff --numstat` output into a
  `RepoDiffStat`, correctly handling binary rows (`-`/`-`), renames, and blank output. Keeping parsing pure makes it
  trivially unit-testable.
- In `execute.py`'s merge step, for each actionable root: best-effort capture pre-merge HEAD, perform the existing
  fast-forward merge, best-effort capture post-merge HEAD, then best-effort `git diff --numstat <old> <new>`. Collect
  results keyed by `git_root`. These go through the same injected command runner used by the rest of execution.
- Add an optional `diffstat: RepoDiffStat | None` field to `DevUpdateOutcome` and attach each root's stat to the
  outcomes for packages in that root (stats are inherently per-repo, which matches the request: "lines … from each
  repo").

### 2. Carry stats across the restart handoff (`src/sase/ace/update_receipt.py`)

- Add optional `diffstat: RepoDiffStat | None` to `UpdateVersionTransition`, populated from the dev outcome (managed
  transitions leave it `None`).
- Add an optional aggregate for the hidden-plugin overflow churn on `UpdateToastReceipt`.
- Extend JSON (de)serialization to round-trip the optional stats as a nested object, keeping the current `format`
  version and tolerating its absence on read.

### 3. Render the stats in the toast (`src/sase/ace/tui/actions/post_update_toast.py`)

- Extend the primary line, plugin line, overflow line, and footer per the "Beautiful rendering" section, including
  name-column alignment computed across the lines being shown.
- Number formatting (thousands separators), the green/red markup, and the empty/binary/ mode-only cases live in small
  helpers.

### 4. Optional config toggle (`src/sase/default_config.yml` + update-toast config)

- Add a `post_update_toast_diffstat: true` knob under `ace.updates` (alongside the existing `startup_toast` /
  `post_update_toast` / `indicator` flags), wired through the existing `_UpdateToastConfig` /
  `_load_update_toast_config` in `src/sase/ace/tui/actions/update_toast.py`. Defaults on; lets anyone who finds the
  churn numbers noisy keep version transitions only. (Per repo convention, config additions must be reflected in
  `default_config.yml`.)

## Testing & verification

- **Unit — numstat parser:** added/deleted sums, file count, binary `-` rows, renames, empty diff.
- **Unit — `execute_dev_update`:** with a fake runner returning numstat output, assert the outcome carries the expected
  `RepoDiffStat`; assert that a failing diff/`rev-parse` leaves stats `None` **without** failing the update. (The two
  existing exact-command-sequence tests in `tests/dev_update/test_execute.py` will be updated to include the new git
  calls.)
- **Unit — receipt round-trip:** stats survive JSON encode/decode; a legacy receipt with no stats decodes cleanly to
  `None` (backward-compat); managed receipts carry no stats.
- **Unit — renderer:** formatting (separators, green/red markup), alignment, the binary/mode-only `N files` case, the
  overflow churn aggregate, the footer files total, and the managed-path no-stats rendering is byte-for-byte unchanged
  from today.
- **Visual — PNG snapshot:** add a new golden alongside the existing
  `tests/ace/tui/visual/test_ace_png_snapshots_post_update_toast.py`, driven by a _dev_ receipt with diff stats, to lock
  in the beautiful layout. Regenerate the golden with `--sase-update-visual-snapshots` and commit it. Keep the existing
  managed-receipt snapshot to guard against regressions.
- **Gate:** `just check` (after `just install`).

## Out of scope

- Showing line stats for managed (uv-index) updates — not computable without local git history.
- Adding churn to the CLI `sase update` output or the startup "updates available" toast (the shared `DevUpdateOutcome`
  field makes this an easy future follow-up, but it is not part of this change).
