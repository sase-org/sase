---
create_time: 2026-07-07 16:31:14
status: done
prompt: sdd/prompts/202607/startup_toast_incoming_commits.md
---
# Plan: Show grouped incoming commits in the startup "Updates available" toast

## Goal

When `sase ace` starts and updates are available, the top-right toast should show **the actual commits that will be
added** if the user updates, **grouped per repository** (sase, sase-core, and each plugin), instead of only showing
version-bump lines.

The result must be **intuitive** (obvious what changes land where), **reliable** (never blocks or crashes startup,
degrades gracefully offline or on fetch failure), and **beautiful** (clean, grouped, color-tied to the Updates surface).

## Current behavior

The startup toast is built in `src/sase/ace/tui/actions/update_toast.py` (`UpdateToastMixin`). A worker thread reads a
cached `UpdateStatus` (`get_cached_update_status`) — a list of `OutdatedComponent` — and `_format_update_toast_message`
renders:

```
↑ Updates available                                  <- title
1 update available                                   <- count line
• sase  0.10.2+132.gcb7945a8b → 0.10.2+133.g687eb0556 <- up to 3 component lines
…and K more                                          <- overflow
Press ,U to update sase, core & plugins              <- shortcut / CTA
```

So today the toast conveys _which components_ bump _which versions_, but not _what is actually changing_.

## What already exists (reuse, don't rebuild)

`src/sase/updates/incoming_commits.py` is a complete incoming-commit engine:

- `CommitSourceSpec` — describes where to fetch commits (local `git` rev-range, or GitHub `compare`). `.cache_key` for
  dedupe.
- `fetch_incoming_commits(spec, *, limit, offline, run_fn, gh_fn)` → `IncomingCommits` (`total`, up to `limit`
  `CommitSummary(short_sha, subject)`, `source`, `error`). It **never raises** — failures return an `unavailable` value.
  Both git and GitHub paths already return commits **newest-first** and carry the true `total`.
- `RepoIncomingCommits(label, incoming)` and `fetch_incoming_commit_groups(...)` for the per-repo grouped preview
  already used by the Config Center plugin-update confirm modals.
- Spec builders: `core_package_commit_spec`, `plugin_entry_commit_spec`, `dev_update_root_commit_spec`.

`src/sase/plugins/render_common.py::build_incoming_commits_renderable` renders a grouped section
(`↑ <label> — N incoming commits` + indented `<sha>  <subject>` + `+K more…`) as a **Rich renderable**. The toast,
however, uses `App.notify(str, markup=True)`, which takes a **markup string**, so the toast needs a small markup-string
renderer that mirrors this established visual language (it cannot pass a Rich `Group` to `notify`).

**Key enabler:** the persisted `OutdatedComponent` already carries everything needed to build a `CommitSourceSpec` at
toast time:

- `install_type`, `source_root` (git root), `upstream_ref` → local **git** spec for editable/dev installs (this is
  Bryan's actual setup — sase + sase-core + plugins are editable checkouts, per the git-describe versions in the
  screenshot).
- `role` + `installed_version`/`latest_version` → **GitHub compare** spec for non-editable host/core installs.

## Desired behavior (target mockup)

Realistic case — sase (3 new commits), sase-core (1), sase-github (2), all editable, total 6 ≤ 20 so all shown:

```
↑ Updates available
3 updates available

↑ sase  0.10.2+132 → 0.10.2+133
  a1b6b59  chore: create VCS ref completion epic beads
  687eb05  chore: Add SDD prompt and plan for tools_pa…
  cb7945a  chore: Make vcs_ref_colon_completion an epic

↑ sase-core  0.4.1 → 0.4.2
  9f2c1a0  fix: correct compare-ref pagination

↑ sase-github  1.2.0 → 1.3.0
  1234567  feat: add PR ref completion
  89abcde  test: cover ref colon edge cases

Press ,U to update sase, core & plugins
```

- **Every updating repo gets its own section**, in the existing role-sorted order (host → core → plugins alphabetical),
  each headed by `↑ <repo>  <old> → <new>`.
- Repo header in the Updates accent (as today), versions dim, shas dim, subjects normal.
- Sections separated by a blank line for readability.
- The `Press ,U…` CTA stays as the final line.

### Degradation (still beautiful, still informative)

- A repo whose commits can't be fetched (offline, no `gh`, GitHub install we can't map to `owner/repo`, or fetch error)
  shows **just its header line** (`↑ repo  old → new`) — i.e. gracefully falls back to the current version-bump
  information for that repo.
- If _no_ repo yields commits, the toast collapses to the header lines for every repo (essentially today's toast,
  restyled) + the CTA. Nothing regresses.

## Design decisions

1. **Single rendering path.** The new per-repo-section renderer subsumes the old component-line renderer: a section with
   zero fetched commits is just its header. This removes the `_MAX_COMPONENT_LINES` / "…and K more" component cap
   entirely (replaced by the commit cap below).

2. **Single-pass fetch, no second round.** Fetch each repo with `limit = MAX_TOTAL` (20). Each `IncomingCommits` then
   carries the repo's true `total` **and** up to 20 newest commits. We allocate the 20-commit display budget from those
   totals and simply _slice_ each repo's already-fetched commit tuple — no second fetch. (GitHub cost is identical
   whether the limit is 7 or 20; git cost is trivial.)

3. **Uniform (max-min fair) truncation — the core requirement.** Allocate the global budget of 20 commit lines across
   the repos that have commits using **water-filling**:

   ```
   allocate_commit_budget(totals: list[int], budget: int) -> list[int]:
     alloc = [0]*n;  active = [i for i where totals[i] > 0]
     while budget > 0 and active:
       share = budget // len(active)
       if share == 0: break                      # remainder handled below
       for i in active:
         give = min(share, totals[i] - alloc[i])
         alloc[i] += give;  budget -= give
       active = [i for i in active if alloc[i] < totals[i]]
     # distribute the < len(active) remainder one-by-one, deterministic
     # (role-sorted) order, to repos that still want more
     for i in active (in original order): if budget: alloc[i]+=1; budget-=1
     return alloc
   ```

   Properties this guarantees (matching the user's spec exactly):
   - **One repo only** → it may use all 20. `totals=[20]` → `[20]`.
   - **Two repos each with 20** → `[10, 10]`, never `[20, 0]`.
   - Repos that want fewer than their fair share give the surplus back to hungrier repos: `totals=[3,2,30], budget=20` →
     `[3, 2, 15]`.
   - If everything fits (`sum(totals) ≤ 20`) everyone shows all their commits.
   - Fully deterministic; pure function; trivially unit-testable.

   Each section then shows `alloc_i` newest commits and a `+extra_i more…` footer where `extra_i = total_i − alloc_i`.

4. **Fetch off the UI thread, in the existing startup worker.** `_run_startup_update_toast_check` already runs
   `thread=True`. We (a) refresh the updates indicator immediately (unchanged latency), then (b) fetch commit sections
   in that same worker, then (c) `call_from_thread` to show the fully-formed toast **once**, all-at-once (no
   pop-then-grow). The toast still shows exactly once per session.

5. **Reliability guards.**
   - `fetch_incoming_commits` never raises; every fetch is additionally wrapped so one bad repo can't sink the toast.
   - **Fetch local `git` (editable) specs first, GitHub specs last**, under a wall-clock **deadline** (≈8s). If the
     deadline passes, remaining (network) repos render header-only. This keeps the toast fast/offline-friendly and
     preferentially preserves the instant local repos — which is the real-world all-editable case.
   - Per-call timeouts already exist (git 5s, `gh` 20s).

6. **Backward-compatible, testable seams.** Add a module-level `_fetch_incoming_commits = fetch_incoming_commits` seam
   in `update_toast.py` (mirrors the existing pattern in `plugins_browser_pane.py`) so tests inject synthetic commits
   and never touch the network. `patch_startup_loaders` is updated to stub this seam by default (like it already stubs
   `get_cached_update_status → None`), so every existing TUI/visual test stays offline and deterministic.

7. **Markup safety & tidiness.** All dynamic text (subjects, shas, labels, versions) is `escape()`d for Rich markup.
   Commit subjects are ellipsized to a fixed width so each commit stays on one line (no ugly wraps), mirroring the Rich
   renderer's `no_wrap/overflow="ellipsis"` intent.

## Implementation breakdown

### 1. `src/sase/updates/incoming_commits.py`

- Add `component_commit_spec(component) -> CommitSourceSpec | None` (typed via a `TYPE_CHECKING` import of
  `OutdatedComponent` — no runtime coupling to `status.py`, no import cycle):
  - editable (`install_type == "editable"` with `source_root` + `upstream_ref`) → git spec.
  - else host → `sase-org/sase`, core → `sase-org/sase-core` GitHub compare spec from
    `installed_version`/`latest_version` (reusing `_release_tag`).
  - else (plugin without a resolvable `owner/repo`) → `None` (degrades to header-only).
- Add pure `allocate_commit_budget(totals, budget)` water-fill helper (§Design 3).
- Export both from `incoming_commits.py` and `src/sase/updates/__init__.py`.

### 2. `src/sase/ace/tui/actions/update_toast.py`

- Extend `_UpdateToastConfig` with `incoming_commits_enabled: bool = True` (read from
  `ace.updates.incoming_commits.enabled`) and `startup_toast_max_commits: int = 20` (read from
  `ace.updates.startup_toast_max_commits`).
- Add a small `ToastRepoSection` (label, installed, latest, sliced `commits`, `total`) and
  `build_toast_commit_sections(components, *, fetch_fn, max_total, offline, deadline)` that: builds specs, fetches
  (git-first, deadline-guarded), runs `allocate_commit_budget`, and returns per-repo sections aligned to the components.
- Rewrite `_format_update_toast_message` to render count line → per-repo sections (header + allocated commits +
  `+K more…`) → CTA, from the sections.
- Rewire `_run_startup_update_toast_check`: refresh indicator first, then (only when `startup_toast` and `has_updates`)
  build sections in-thread and pass them through `_apply_startup_update_status` / `_show_startup_update_toast`.
- Add the `_fetch_incoming_commits` seam.

### 3. Config — `src/sase/default_config.yml`

Add under `ace.updates`:

```yaml
startup_toast_max_commits: 20
```

(`incoming_commits.enabled` already exists and is reused as the on/off switch.)

### 4. Tests

- `tests/test_incoming_commits.py`: unit-test `allocate_commit_budget` (all the §Design 3 cases, incl. 1-repo-gets-20,
  20+20→10+10, surplus redistribution, everything-fits, more-repos-than-budget remainder) and `component_commit_spec`
  (editable→git, host/core→github, unmappable plugin→None).
- `tests/ace/tui/test_update_toast.py`: update the format assertions to the new per-repo-section layout; add tests that
  inject a fake `_fetch_incoming_commits` and assert grouping, fair truncation to 20, `+K more…`, header-only
  degradation for unavailable repos, and CTA presence. Keep the "once per session" / disabled-config / indicator-only /
  default-TTL tests green.
- Visual: update `patch_startup_loaders` to stub the fetch seam; **regenerate the existing `startup_update_toast_120x40`
  golden** (header restyle) and **add a new visual snapshot** that exercises the grouped multi-repo layout with
  truncation, so the beautiful end state is pinned (`just test-visual` / `--sase-update-visual-snapshots`).

## Edge cases

- **Only one repo has commits** → up to 20 from it (explicit requirement).
- **> 20 total across repos** → fair split, each section footed with `+K more…`.
- **> 20 repos updating simultaneously** → remainder gives 1 each to the first repos; a repo allocated 0 but with
  commits renders header + `+total more…`.
- **Offline / no `gh` / fetch error / unmappable GitHub plugin** → that repo is header-only.
- **Fresh cache (no network on the status read)** → commit fetch is the only I/O and it's local git for editable
  installs; deadline-guarded for any GitHub repos.
- **Empty/whitespace commit subject** → renders sha alone; never crashes markup.

## Out of scope

- Changing the post-update toast, the updates indicator badge, or the Config Center plugin-browser commit previews (they
  keep their own config/limits).
- Persisting incoming commits into the status-snapshot cache schema (rejected: larger schema/revalidation change for
  marginal benefit; local git fetch at toast time is already fast and the deadline covers the network case).
- Any memory-file, `CLAUDE.md`, or provider-shim edits.

## Verification

- `just install` then `just check` (lint + mypy + tests).
- `just test-visual` to review/accept the regenerated and new toast snapshots.
- Manual: launch `sase ace` in the dev workspace with the branch behind upstream and confirm the grouped toast renders
  as designed.
