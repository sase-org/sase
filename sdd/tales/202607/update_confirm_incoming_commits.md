---
create_time: 2026-07-07 12:16:32
status: done
prompt: sdd/prompts/202607/update_confirm_incoming_commits.md
---
# Plan: Show All Incoming Commits in the Updates-Tab Update Confirm Modal

## Goal

When the user presses `u` on the "Updates" tab of the SASE Admin Center (and, for uniformity, `U` on a single plugin),
the y/n confirm modal (`PluginActionConfirmModal`) should show **every incoming commit, grouped per repo that will be
updated**, in a scrollable section driven by `ctrl+d` / `ctrl+u`. Today the modal only shows the command, a summary
line, and short operation details — the user confirms an update without seeing what code it pulls in, even though the
Updates tab itself already previews up to 7 incoming commits per repo.

## Current State (verified)

- `u` → `SaseUpdateActionsMixin.action_update_sase` (`src/sase/ace/tui/modals/plugins_browser_sase_update.py`) plans
  off-thread, then routes to one of two confirm modals:
  - **Dev path** (editable installs): `_open_sase_dev_update_modal(plan, ...)` with a `DevUpdatePlan`. Planning already
    ran `git fetch` per root (with a cached-upstream fallback), and each `DevUpdateRootPlan` carries `git_root` +
    `upstream` — everything needed for a fast, local `git log HEAD..<upstream>`.
  - **Managed path**: `_open_managed_sase_update_modal()` — no per-repo info in the modal today. The pane already holds
    `_core_versions` (sase / sase-core with `update_available` markers) and `_catalog` (plugins with
    `update_available`), plus two incoming-commit caches fetched with `limit=7`: `_core_incoming_commits` (eager, from
    `load_plugins_catalog_for_pane`) and `_incoming_commit_cache` (lazy per-plugin).
- `U` → `PluginUpdateActionsMixin.action_update` (`plugins_browser_update.py`) routes to
  `_open_update_modal(UpdateReady)` (managed) or `_open_dev_update_modal(DevUpdatePlan)` (editable) — same modal class,
  same gap.
- The incoming-commits domain layer (`src/sase/updates/incoming_commits.py`) already provides `CommitSourceSpec` (git /
  github sources), `fetch_incoming_commits` (never raises; returns an `IncomingCommits` with authoritative `total`,
  capped `commits`, and `source="unavailable"` + `error` on failure), and spec builders `core_package_commit_spec` /
  `plugin_entry_commit_spec`.
- The shared renderer `build_incoming_commits_renderable` (`src/sase/plugins/render_common.py`) draws the
  `↑ N incoming commits` header, dim-sha commit rows, `+N more…` footer, the loading line, and the unavailable line. It
  is used by both the SASE Core panel and the plugin detail panel.
- `PluginActionConfirmModal` (`plugin_action_confirm_modal.py`) is purely presentational: one `Static` inside a
  `Container` (width 76, `max-height: 80%`), y/n/esc/g bindings, **no scrolling**.
- Config: `ace.updates.incoming_commits.{enabled, max_per_repo}` in `src/sase/default_config.yml` (defaults `true` /
  `7`), parsed by `_load_incoming_commits_config` (`plugins_browser_incoming.py`).

## UX Design

### Layout

Keep the existing preview panel (intro, `Would run …`, summary, details) **fixed at the top**, and add a new bordered,
independently scrollable **"Incoming commits"** box between it and the buttons. Rationale: while the user scrolls a long
commit list, the command they are about to confirm and the y/n affordance stay visible at all times — scrolling never
costs them the confirmation context.

```
┌─ ↑  Update SASE dev checkouts ──────────────────────────────┐
│ ┌─ Confirm dev update ────────────────────────────────────┐ │
│ │ Confirm to fetch, fast-forward, and reconcile editable  │ │
│ │ SASE checkouts.                                         │ │
│ │                                                         │ │
│ │ Would run  sase update                                  │ │
│ │                                                         │ │
│ │ sase: Updates 1 editable package; across 1 checkout;    │ │
│ │ then runs 1 reconcile step; skips 3 unsafe/current      │ │
│ │ - fetch + fast-forward origin/master in sase            │ │
│ │ - …                                                     │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─ Incoming commits ──────────────────────────────────────┐ │
│ │ ↑ sase — 6 incoming commits                            ▲│ │
│ │   410e8853  feat(tui): improve ACE tab guide content   █│ │
│ │   3e3cdb8c  chore: Add SDD prompt and plan for tab_gu… ░│ │
│ │   904a3e15  fix(ace): support tab switching in popup … ░│ │
│ │   …                                                    ░│ │
│ │ ↑ sase-github — 2 incoming commits                     ▼│ │
│ └──────────────────────────────── ctrl+d/u scroll ────────┘ │
│            [ Confirm (y) ]        [ Cancel (n) ]            │
│                   y confirm · n/esc cancel                  │
└─────────────────────────────────────────────────────────────┘
```

### Visual rules

- **Per-repo group**: header `↑ <repo> — N incoming commits` (existing cyan `↑` glyph; repo name bold cyan; count in the
  existing cyan header style), followed by the existing commit rows (`  <short-sha dim>  <subject>`). Groups are
  separated by one blank line. This deliberately matches the Updates-tab rendering — one shared renderer keeps every
  update surface visually identical.
- **Commit subjects** render on one line each with `no_wrap` + ellipsis overflow (no wrapped rows — a long subject must
  not turn one commit into three visual lines).
- **Truthful totals**: per-repo commit lists are capped at a new confirm-specific limit (default **250**, see Config
  below); when capped, the existing dim `+N more…` footer keeps the total honest.
- **Loading state**: while the fetch runs, the box shows the existing `↑ checking incoming commits…` dim line. The modal
  is fully usable (y/n) during loading — the preview is enrichment, never a gate.
- **Failure state**: a repo whose fetch fails renders `<repo>: incoming commits unavailable (<reason>)` in dim, under
  its group position; other repos still render normally.
- **Empty state**: if no repo yields a commit spec (e.g. nothing has update markers), the whole box is hidden — the
  modal looks exactly like today.
- **Scroll affordance**: the commits box border-subtitle shows `ctrl+d/u scroll`, ideally only when the content actually
  overflows (check `max_scroll_y > 0` after the content lands via `call_after_refresh`; falling back to
  always-shown-when-populated is acceptable if the conditional proves flaky). Mouse-wheel scrolling works for free via
  the scroll container.
- **Width**: when a commits box is present, the modal widens (add a `has-commits` CSS class on the container; e.g. width
  76 → 100, `max-width: 95%`) so real-world subjects fit. Modals without commit groups (install, uninstall) keep today's
  dimensions.

### Keymaps

- `ctrl+d` / `ctrl+u`: scroll the commits box down/up by half its viewport height
  (`scroll_relative(y=±h//2, animate=False)` — the same convention as `PlanApprovalModal`). Bound on the modal so they
  work regardless of which button has focus. No-ops when the box is absent or not overflowing.
- All existing bindings (`y`, `n`, `q`, `esc`, `g` toggle-source) are unchanged; `g`/`G` top/bottom scrolling is
  intentionally **not** added because `g` already toggles install-source variants.

## Architecture & Data Flow

### 1. Domain layer (`src/sase/updates/incoming_commits.py`)

- Add `RepoIncomingCommits` dataclass: `label: str` + `incoming: IncomingCommits` — the unit the modal renders.
- Add `dev_update_root_commit_spec(root: DevUpdateRootPlan) -> CommitSourceSpec | None`: git-source spec from
  `root.git_root` + `root.upstream` (label = basename of `git_root`, matching the details lines' `in sase` wording).
  Returns `None` when either field is missing.
- Extend `_fetch_github_incoming_commits` to support large limits: today it fetches at most one tail page of 100.
  Generalize to walk compare pages **from the tail backwards** (per_page=100), concatenating until `limit` newest
  commits are collected or page 1 is reached. Behavior for existing callers (limit 7) is unchanged. Note: the GitHub
  compare API caps listed commits (~250) while `total_commits` stays authoritative — the `+N more…` footer keeps the UI
  truthful past any API cap. Verify actual pagination behavior against the live API during implementation and cap the
  page walk at `ceil(limit / 100)` requests.
- Add a small orchestration helper
  `fetch_incoming_commit_groups(specs: Sequence[tuple[str, CommitSourceSpec]], *, limit, offline, seed: Mapping[IncomingCommitsCacheKey, IncomingCommits]) -> tuple[RepoIncomingCommits, ...]`:
  for each `(label, spec)`, reuse `seed[spec.cache_key]` **iff** it is complete (`extra == 0` and source is not
  `"unavailable"`), else call `fetch_incoming_commits(spec, limit=limit, offline=offline)`. Pure function, easy to
  unit-test; fetches run sequentially in the caller's worker thread.

This stays in Python by prior accepted decision (the whole updates/dev-update/uv-tool domain is pure Python and Rust
core has no update/GitHub surface) — consistent with the existing Updates-tab incoming-commits feature.

### 2. Shared renderer (`src/sase/plugins/render_common.py`)

- Extend `build_incoming_commits_renderable(incoming, *, loading=False, label: str | None = None)`:
  - With `label`, the header becomes `↑ <label> — N incoming commits` and the unavailable line becomes
    `<label>: incoming commits unavailable (<reason>)`.
  - Commit-row `Text` gains `no_wrap=True, overflow="ellipsis"`.
  - Existing callers (tab panels) pass no label and render exactly as before.

### 3. Modal (`src/sase/ace/tui/modals/plugin_action_confirm_modal.py`)

- New optional constructor arg: `incoming_commits_loader: Callable[[], tuple[RepoIncomingCommits, ...]] | None`. The
  modal stays presentational — it never knows how commits are sourced, it just runs the injected loader off-thread. This
  keeps one mechanism for all four call sites.
- `compose()` gains, between the preview `Static` and the buttons, a `VerticalScroll(id="plugin-action-commits")`
  (border title `Incoming commits`) containing one `Static`. Only composed when a loader was provided.
- `on_mount()`: when a loader exists, render the loading line, then
  `run_worker(loader, thread=True, exclusive=True, group="confirm-incoming-commits")`. On worker success, update the
  `Static` with the group renderables (blank-line separated
  `build_incoming_commits_renderable(g.incoming, label=g.label)`), toggle the subtitle hint, or hide the box when the
  result is empty. On worker error, render a single dim `incoming commits unavailable (<reason>)` line. Guard all
  updates with `is_attached` / try-except — a dismissed modal must never crash on a late worker (Textual also cancels
  workers of removed nodes).
- Bindings: add `("ctrl+d", "scroll_commits_down")` / `("ctrl+u", "scroll_commits_up")` with the `PlanApprovalModal`
  half-page implementation, no-op when the box is missing.
- Never block the event loop: the only on-loop work is composing/updating renderables (TUI perf rule 1); the modal opens
  instantly in every path.

### 4. CSS (`src/sase/ace/tui/styles.tcss`)

- `#plugin-action-commits { height: auto; max-height: 40vh; border: round $primary; ... }` — auto-sizes for short lists,
  caps and scrolls for long ones; the container keeps `max-height: 80%`.
- `PluginActionConfirmModal.has-commits > #plugin-action-container { width: 100; }` widened variant.
- Verify sizing/clipping interactions with the PNG snapshots (Textual auto-height + capped-scroll-child nesting is
  exactly the kind of thing the visual suite exists for).

### 5. Call-site wiring (group builders live with the pane's incoming-commits mixin)

Add builder helpers to `plugins_browser_incoming.py` (they need pane state: config, offline flag, cache snapshots) that
return `None` when `ace.updates.incoming_commits.enabled` is false, else a zero-arg loader closure over **plain
snapshots taken on the UI thread** (no live widget state read from the worker thread):

1. **Dev sase update** (`_open_sase_dev_update_modal`): specs from `plan.actionable_roots` via
   `dev_update_root_commit_spec`; labels = root basenames; plan order. Local `git log` only — effectively instant, and
   consistent with what the update will actually fast-forward (planning already fetched, with the documented
   cached-upstream fallback on fetch failure).
2. **Managed sase update** (`_open_managed_sase_update_modal`): specs from `_core_versions.packages` (via
   `core_package_commit_spec`, labels = package names, host `sase` first, then `sase-core`) plus installed catalog
   entries with `update_available` (via `plugin_entry_commit_spec`, labels = plugin names, alphabetical). Seed =
   `_core_incoming_commits` + `_incoming_commit_cache` snapshots keyed by `spec.cache_key` (reused only when complete,
   so a repo whose tab preview said `+3 more…` re-fetches with the confirm limit).
3. **Plugin dev update** (`_open_dev_update_modal` in `plugins_browser_update.py`): same as (1) from its
   `DevUpdatePlan`.
4. **Managed plugin update** (`_open_update_modal`): specs for the `UpdateReady.targets` entries via
   `plugin_entry_commit_spec`, seeded from `_incoming_commit_cache`.

The modal results are **not** written back to the pane caches — the tab renders every commit in a cached tuple, so
seeding it with 250-commit results would explode the tab panels (caches were fetched with `max_per_repo=7`).

### 6. Config (`src/sase/default_config.yml` + `plugins_browser_incoming.py`)

- Add `ace.updates.incoming_commits.confirm_max_per_repo: 250` (0 = header/total only, mirroring `max_per_repo`
  semantics) and surface it on `IncomingCommitsConfig`. `enabled: false` disables the modal section along with the tab
  previews, as users would expect from the existing flag.

## Edge Cases & Reliability

- **Fetch failure / timeout**: `fetch_incoming_commits` never raises (git 5 s, gh `GH_TIMEOUT_SECONDS` caps); per-repo
  unavailable lines; loader runs off-thread so a slow `gh` never freezes the UI, and y/n works while loading.
- **Offline mode**: github-source repos render `unavailable (offline mode)`; dev git-log groups still work (fully
  local).
- **Confirm-before-loaded**: allowed by design; the worker dies with the dismissed modal.
- **Zero groups / spec-less repos** (missing upstream, unparseable versions): those repos are simply omitted;
  all-omitted hides the box.
- **Huge histories**: hard per-repo cap (`confirm_max_per_repo`) + `+N more…` keeps rendering bounded (~250 `Text` rows
  per repo worst case, built off the hot path and only re-rendered once when the worker lands).
- **Variant toggling (`g`)**: the commits box is modal-level, not variant-level — update modals have a single variant,
  and the multi-variant install modal passes no loader, so there is no interaction.

## Testing

1. **`tests/test_incoming_commits.py`**: `dev_update_root_commit_spec` (happy path, missing upstream/root); github tail
   pagination across multiple pages with fake `gh_fn` (order = newest-first, respects limit, truthful `total`);
   `fetch_incoming_commit_groups` seeding rules (complete cache hit reused, partial `extra > 0` re-fetched, unavailable
   never reused).
2. **Modal unit tests** (alongside existing plugin-action/confirm tests): loader → placeholder → populated transition;
   empty result hides the box; worker error renders the unavailable line; `ctrl+d`/`ctrl+u` actions scroll and no-op
   without the box; no commits box when no loader is passed (install/uninstall regression guard).
3. **Renderer tests**: labeled header, labeled unavailable line, unchanged unlabeled output.
4. **PNG visual snapshots** (`tests/ace/tui/visual/test_ace_png_snapshots_config_center_plugin_actions.py`, goldens
   under `tests/ace/tui/visual/snapshots/png/`): (a) dev-update confirm with two repos and enough commits to overflow —
   shows grouped commits, scrollbar, and the `ctrl+d/u scroll` hint; (b) the same modal after one `ctrl+d` (scrolled
   state, summary panel still fixed); (c) loading-placeholder state via a stubbed never-completing loader (or a
   deterministic stub, whichever renders stably). Reuse the existing `_stub_plugin_incoming_commits` conftest machinery
   for deterministic data; regenerate any existing update-confirm goldens whose layout legitimately changes with
   `--sase-update-visual-snapshots`.
5. Check the Admin Center help/tab-guide content for Updates-tab confirm documentation and update it if the modal's keys
   are described there (per the ace help-sync rule).

## Verification

- `just install` (fresh ephemeral workspace) → `just check`.
- `just test-visual`; inspect `.pytest_cache/sase-visual/` artifacts for the new/changed goldens before accepting them.
- Manual smoke: `sase ace` → Admin Center → Updates → `u` in a dev checkout with incoming commits (the exact scenario in
  the reference screenshot), confirm scrolling, cancel; repeat with `enabled: false` config to confirm the box
  disappears.

## Explicit Non-Goals

- No change to how updates execute, to the Updates-tab previews, or to the install/uninstall confirm modals.
- No write-back of confirm-time fetches into the tab caches.
- No Rust-core involvement (documented boundary decision for the updates domain).
