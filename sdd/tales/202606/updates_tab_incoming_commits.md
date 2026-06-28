---
create_time: 2026-06-28 16:36:55
status: done
prompt: sdd/prompts/202606/updates_tab_incoming_commits.md
---
# Plan: Incoming Commits on the Admin Center "Updates" Tab

## Goal

Make the Admin Center → **Updates** tab answer the question _"what will I actually get if I update?"_ by showing, **per
repo**, the first line (subject) of the incoming commit messages an update would pull in for **sase**, **sase-core**,
and every installed **plugin**:

- Show up to **7** commit subjects per repo (newest first).
- **Always** show the **true total** number of new commits, even when more than 7 (e.g. `↑ 23 incoming commits` with 7
  listed and `+16 more…`).
- Degrade gracefully (never crash, never block the UI) when the data can't be fetched.

This is a presentation + data-sourcing feature. It deliberately reuses the visual vocabulary of the existing Agents-tab
**COMMITS** panel (`<sha> <subject>` rows grouped under a repo) so the two surfaces feel like one product.

## Product context & current state

The Updates tab is the `PluginsBrowserPane` widget hosted by the Config Center modal. Today it shows:

- A top **"SASE Core"** panel: a 2-row table for `sase` and `sase-core` (installed → latest, update glyph), plus the
  `S run sase update` call-to-action and a "not a uv tool install" warning when applicable.
- A **summary line** (counts + offline badge + stale/warning hints).
- A **plugin master/detail browser**: a filterable `OptionList` of plugins on the left, and a Rich detail panel on the
  right (`build_detail_panel`) that mirrors `sase plugin show`.

It already detects _whether_ an update is available (version deltas, update glyphs `↑`) but says **nothing about what
changed**. A user sees `v0.5.0 → v0.6.0` and has to leave the TUI to find out what that means.

### Two install modes drive the design (verified)

The source of the incoming commits depends on how the component is installed:

1. **uv-tool / wheel install (the common case — Bryan's `sase` is `uv tool install sase v0.5.0`).** There is **no local
   git checkout** of the installed component, so we cannot `git log` it. We resolve the incoming commits via the
   **GitHub compare API**: `gh api repos/{owner}/{repo}/compare/v{installed}...v{latest}`, which returns:
   - `total_commits` — the authoritative total (it exceeds the 250-cap `commits[]` array on large diffs), and
   - `commits[].sha` + `commits[].commit.message` (first line = subject).
2. **Editable / dev install.** A local checkout exists and the dev-update detection already `git fetch`-ed the upstream,
   so we use the precise, offline-friendly local path: `git rev-list --count <current>..<upstream>` (total) +
   `git log -n8 --format=… <current>..<upstream>` (subjects).

Both paths produce the same shape (`total` + list of `(short_sha, subject)`) and feed **one shared renderer**, so
presentation is identical regardless of source. (This mirrors the asymmetric-source / unified-presentation design
already used by the Agents-tab COMMITS panel.)

### Verified facts the design relies on

- Release tags are `vX.Y.Z` for `sase`, `sase-core`, and plugins (e.g. `sase-telegram`).
- Repo-identity mapping: host `sase` → `sase-org/sase`; the `sase-core-rs` **distribution** maps to the
  **`sase-org/sase-core`** repo (there is no `sase-core-rs` repo); plugins map via the catalog's `full_name`.
- The GitHub compare endpoint returns `total_commits` accurately even when `commits[]` is truncated at 250.
- `gh` is installed and authenticated; the plugin catalog already shells out to `gh api`, so this is an established,
  in-pattern access path.

## Design

### 1. Data layer — a small, testable domain module

Add `src/sase/updates/incoming_commits.py` (lives beside the existing pure-Python `src/sase/updates/` domain):

- `CommitSummary` (frozen): `short_sha: str`, `subject: str`.
- `IncomingCommits` (frozen):
  - `total: int` — true total new-commit count.
  - `commits: tuple[CommitSummary, ...]` — newest-first, already capped to the display limit.
  - `source: Literal["git", "github", "unavailable"]`.
  - `error: str | None` — populated (not raised) when unavailable.
  - Convenience: `shown` (= `len(commits)`), `extra` (= `max(0, total - shown)`).
- `CommitSourceSpec` — resolves a component to a source: `repo_full_name`, `base_ref`, `head_ref`, and for the editable
  case `git_root` + `upstream_ref` + `current_ref`. Helpers build this from:
  - a `CorePackageVersion` (sase / sase-core), applying the `sase-core-rs → sase-org/sase-core` mapping and the `vX.Y.Z`
    tag convention; and
  - a `PluginCatalogEntry` (uses `entry.full_name`, `entry.installed.version`, `entry.latest.version`,
    `entry.latest.source`/`install_type` to choose git vs github).
- `fetch_incoming_commits(spec, *, limit=7, offline=False, run_fn=…, gh_fn=…) -> IncomingCommits`:
  - editable → local git (`git rev-list --count` + `git log`), reusing the existing `run_git` helpers / the
    subject-parsing approach already used by `_get_commits_ahead` and the revert-discovery log parser
    (NUL/`%x1f`-delimited `%h`/`%s` so bodies with newlines never corrupt parsing).
  - otherwise → GitHub compare via a thin `gh api` wrapper modeled on `github_source.fetch_catalog_payload` (timeout,
    non-zero-exit handling, JSON parse). Commits come back oldest-first; reverse to newest-first, take `limit`, set
    `total = total_commits`.
  - Any failure (gh missing, timeout, non-zero exit, 404 from a not-yet-pushed tag, malformed JSON) returns
    `IncomingCommits(source="unavailable", error=…)` — **never raises**. Injectable runners make every branch
    unit-testable with no network/git.

**Rust-core boundary note (decision for review):** the `rust_core_backend_boundary` rule says shared backend behavior
belongs in `sase-core`. I am proposing to keep this in **Python** because the _entire_ existing updates / dev-update /
uv-tool domain — including its GitHub access via the `gh` subprocess — already lives in Python, and the Rust core
currently has **no** update-checking or GitHub-client surface to extend. Adding a brand-new network/`gh` capability to
Rust for this one feature would diverge from the established, recently and actively maintained Python pattern. **This is
the one architectural call I'd like confirmed at plan review**; if you'd rather seed an `incoming_commits` primitive in
`sase-core`, the data-layer module above is the clean seam to move.

### 2. Shared renderer — one look for core and plugins

Add a renderer (in `src/sase/plugins/render_common.py` or a small `incoming_commits_render.py`) producing a Rich
renderable from an `IncomingCommits` (plus the loading state):

- Header: `↑ {total} incoming commit{s}` (always the true total), styled like the existing `_UPDATE_GLYPH` cyan accent.
- Up to 7 rows: `  {short_sha}  {subject}` (sha dim, subject default) — same vocabulary as the Agents-tab COMMITS panel
  for cross-surface consistency.
- If `extra > 0`: a dim `  +{extra} more…` line.
- Loading state: `↑ checking incoming commits…` (dim).
- Unavailable state: dim `incoming commits unavailable ({error})` — the version delta shown above still tells the user
  an update exists, so this is informative, not alarming.

Using one renderer in both placements guarantees they look identical (DRY + visual parity).

### 3. Placement & interaction

Keep the tab's proven two-zone layout (no invasive selection/action refactor); surface commits in the two natural homes,
both using the shared renderer:

- **Plugins → right-hand detail panel (lazy).** Extend `build_detail_panel` to accept an optional `IncomingCommits` and
  render the section under the detail rows when the highlighted plugin has an update. Fetching is **lazy, off-thread,
  debounced, and cached**, reusing the existing `DetailPanelDebouncer`:
  1. On highlight of an updatable plugin with no cached result, paint the detail immediately with the _loading_ commits
     section, then spawn a worker to fetch.
  2. On completion, **re-read the current highlight** (per the TUI-perf "re-capture after await" rule) and patch the
     detail only if it's still the same plugin.
  3. Cache `IncomingCommits` per `(repo, base, head)` for the session; the version pair only changes when a fresh
     update-check runs, so the cache is naturally correct.
  4. Offline mode and "not an update" plugins render no commits section (no fetch).
- **Core (sase / sase-core) → inline in the top "SASE Core" panel (eager).** For each core package with an update,
  render the commits section directly beneath its row. There are at most two such packages, so fetch them **in the
  existing background loader** (`load_plugins_catalog_for_pane`) — already off the event loop — and carry the results on
  `PluginsLoadResult`. The panel shows the _loading_ state on first paint and the results when the load lands (the panel
  already re-renders via `_update_static("#sase-core-versions", …)`).

This honors "up to 7 per repo" uniformly, keeps core commits where core lives and plugin commits where plugin detail
lives, and avoids reworking the plugin-centric selection/install/update/uninstall machinery.

### 4. Configuration

Add an `ace.updates.incoming_commits` block to `src/sase/default_config.yml` and `config/sase.schema.json`:

- `enabled: true` — master toggle (off ⇒ no fetch, no section).
- `max_per_repo: 7` — display cap (the requirement's default; configurable).

Resolved in the same style as the existing `ace.updates` knobs (`startup_toast`, `check_ttl_minutes`).

### 5. Performance & reliability guardrails

- **Never block the event loop.** Plugin commits fetch in a dedicated worker; core commits fetch in the existing load
  worker. UI only ever reads cached/known data synchronously.
- **Debounced + last-selection-wins** for the plugin path (held j/k ⇒ one final fetch + paint; stale results for a
  no-longer-highlighted plugin are dropped).
- **Bounded work:** one `gh`/`git` call per component per version-pair, cached for the session; authenticated `gh` rate
  limits are a non-issue.
- **Total-truth guarantee:** the count always comes from `total_commits` / `rev-list --count`, never from the (possibly
  truncated) shown list.
- **Graceful degradation everywhere:** missing `gh`, offline, timeouts, un-pushed tags, and non-editable repos without a
  usable tag all resolve to the "unavailable" section, not an error or crash.

## Files (anticipated)

- **New:** `src/sase/updates/incoming_commits.py` (data models + dual-source fetcher + repo/tag/spec helpers).
- **New/extend:** shared `IncomingCommits` renderer (in `render_common.py` or a sibling module).
- **Edit:** `src/sase/plugins/render_catalog.py` — `build_detail_panel` gains the optional commits section.
- **Edit:** `src/sase/ace/tui/modals/plugins_browser_loading.py` — `PluginsLoadResult` carries core incoming commits;
  loader fetches them for updatable core packages.
- **Edit:** `src/sase/ace/tui/modals/plugins_browser_pane.py` — lazy plugin-commit worker + cache + wiring into the load
  result for core.
- **Edit:** `src/sase/ace/tui/modals/plugins_browser_rendering.py` — pass cached/loading commits into the detail and
  core-panel renderers.
- **Edit:** `src/sase/default_config.yml` + `config/sase.schema.json` — the `incoming_commits` config block.
- **Edit:** the Updates-tab `?` help content — document the new incoming-commits behavior (per the ace "Help Popup
  Maintenance" rule).

## Testing

- **Unit (`incoming_commits.py`)** with injected runners (no network/git):
  - GitHub path: canned compare JSON → correct total, newest-first ordering, 7-cap + `extra`, sha shortening, subject =
    first message line.
  - Git path: canned `rev-list`/`log` output → total + subjects + truncation.
  - Repo/tag mapping: `sase`→`sase-org/sase`, `sase-core-rs`→`sase-org/sase-core`, plugin→`full_name`, `vX.Y.Z` tags.
  - Failure modes: gh missing / non-zero / timeout / 404 / malformed JSON / offline → `source="unavailable"`, no raise.
- **Renderer:** header total/pluralization, ≤7 vs `+N more`, loading and unavailable states.
- **Widget/TUI:** detail panel shows the section for an updatable plugin and hides it otherwise; loading→loaded patch
  lands on the still-highlighted plugin; held j/k debounces to a single fetch; core panel renders inline commits from
  the load result; offline mode fetches nothing.
- **Visual PNG snapshots:** update goldens for the new detail section and the expanded core panel via
  `just test-visual --sase-update-visual-snapshots` (intentional visual change).
- Run `just install` then `just check` (and `just test-visual`) before completion.

## Out of scope / future

- Full bodies / links to GitHub commit pages (subjects only, per the request).
- Folding the two core packages into the plugin `OptionList` as selectable rows (a larger unification that would touch
  install/update/uninstall gating) — noted as a possible future refactor, not done here.
- Surfacing incoming commits in the startup update toast or the CLI (`sase plugin show` / `sase update`); the data layer
  is reusable for that later.
