---
create_time: 2026-06-23 15:17:23
status: done
prompt: sdd/prompts/202606/linked_repo_diff_file_panels.md
---
# Plan: Per-linked-repo diff pages in the Agents-tab file panel

## Product context

On the **Agents** tab of `sase ace`, selecting an agent shows a detail view whose bottom panel is the **file panel**
(`AgentFilePanel`). That panel already behaves as a small "deck" of navigable pages: the user presses `<ctrl+n>` /
`<ctrl+p>` to cycle through the agent's live primary-workspace diff plus any static artifacts (plan, screenshots, PDFs).
Today the panel only ever shows the **primary** workspace's diff.

We recently fixed linked-repo deltas so the metadata header's **"DELTAS:"** section now lists changed files for each
configured linked repository (e.g. `sase-core`, `sase-github`) whose workspace the agent touched. But there is no way to
actually _read_ those linked-repo diffs — only the primary diff is viewable in the file panel.

**This feature:** give every linked repo with an open, modified workspace its own navigable **diff page** in the file
panel, reachable with the existing `<ctrl+n>` / `<ctrl+p>` keys. When the user lands on a linked-repo page it must be
**immediately and unmistakably clear** which repository's diff they are looking at.

### Design goals (intuitive, reliable, beautiful)

- **Intuitive:** linked diffs are "just more pages" in the deck the user already cycles. No new keybinding, no new mode,
  no new mental model. They sit directly after the primary diff so all code changes are contiguous, before the static
  artifacts.
- **Reliable:** a linked page exists **iff** that repo has an open suffix-strategy workspace on disk with a non-empty
  working-tree diff — the exact same eligibility the "DELTAS:" header already enforces. Pages appear/disappear as the
  agent edits, the user's current page is preserved across refreshes, and nothing blocks the Textual event loop.
- **Beautiful:** each linked page carries a styled banner (`⭐ sase-core · linked repo` + workspace path + fetch time)
  reusing the same star glyph and accent color already used for linked repos in the header, and the file panel's top
  border shows the current source (`⭐ sase-core`). The diff itself is syntax highlighted exactly like the primary diff.

## Background: how the relevant pieces work today

(Anchors are repo-relative; no behavior below changes unless this plan says so.)

1. **Single file panel, multiple "pages."** `AgentFilePanel` (`src/sase/ace/tui/widgets/file_panel/__init__.py`) holds
   `self._file_list: list[str]` and `self._current_file_index`. Entries are either the sentinel string
   `_LIVE_DIFF_SENTINEL` (`"__live_diff__"`, the auto-refreshing primary diff) or static file paths. `next_file()` /
   `prev_file()` cycle the index; every change posts a `FileListChanged` message. `<ctrl+n>`/`<ctrl+p>` are bound to
   `action_next_agent_file` / `action_prev_agent_file` (`src/sase/ace/tui/actions/agents/_panel_detail.py`) →
   `AgentDetail.cycle_next_file` / `cycle_prev_file` → `file_panel.next_file()` / `prev_file()`. **No keybinding work is
   needed.**

2. **Primary diff fetch.** `get_agent_diff(agent)` (`file_panel/_diff.py`) resolves the workspace + VCS provider and
   calls `provider.diff_with_untracked(workspace_dir, timeout=10)`, cached in `_diff_cache` by a
   `(identity, workspace_dir, provider, .git/index fingerprint, 1s TTL bucket)` key. It runs in a background thread
   (`_start_background_fetch` → `run_worker(thread=True)`); results land in `file_cache` and render via
   `_display_file_with_timestamp`.

3. **Linked-repo deltas (header).** `file_panel/_linked_deltas.py` already does, in a background worker
   (`compute_linked_delta_groups`, triggered from the prompt panel's async path in
   `prompt_panel/_agent_display_async.py`):
   - `_eligible_linked_repos(agent)` — keep only repos that are `suffix` strategy, have a non-empty `workspace_dir`, and
     whose agent status is **not** `Done`/`Failed`.
   - per repo, `_compute_repo_group` calls `provider.has_local_changes` then `provider.diff_with_untracked(...)`, parses
     the unified diff into `DeltaEntry` summaries, and returns a `LinkedDeltaGroup(repo_name, workspace_dir, entries)`
     **only when there are entries** (i.e. real changes). **The raw `diff_text` is currently parsed and then
     discarded.**
   - results are cached in-memory per agent: `get_cached_linked_delta_groups(agent)` returns the tuple of groups with
     **zero I/O** (safe to call on the event loop). `deltas_builder.build_delta_entries_section` renders these groups
     under "DELTAS:" using `WORKSPACE_GLYPH` (`⭐`) + `COLOR_WORKSPACE_GLYPH`/`COLOR_WORKSPACE_NAME`
     (`prompt_panel/_agent_context_common.py`).

4. **Rendering + trim.** `_display.py` renders diffs (`# Last fetched:` comment prepended, lexer `diff`) and static
   files (a styled path header `Text` Grouped above the syntax). `_trim.py` re-renders on trim/expand from
   `_full_content` + `_content_mode`, reconstructing the static header from `_static_header_path` when
   `_content_mode in ("static", "static_diff")`.

5. **Zoom modal.** `modals/zoom_panel_modal.py` reuses `AgentFilePanel` (subclass `_ZoomFilePanel`), seeds its
   `_file_list`, and cycles pages with the same `next_file`/`prev_file`. So whatever pages we add to the base panel are
   automatically zoomable.

6. **Boundary check** (`memory/rust_core_backend_boundary.md`): the diff _content_ already comes through the shared VCS
   provider (`provider.diff_with_untracked`), identical to the primary diff. What we add is pure **TUI presentation** —
   extra navigable pages and their rendering. **No `sase-core` / Rust changes.**

## Design

### A. Carry the raw diff text on each linked group (so a page can render instantly)

The header worker already shells out and gets the full diff per repo; we just stop throwing it away.

- Extend `LinkedDeltaGroup` (`file_panel/_linked_deltas.py`) with two additive, defaulted fields: `diff_text: str = ""`
  and `fetched_at: datetime | None = None`. Defaults keep existing constructors and the header renderer (which only
  reads `.entries`) working unchanged.
- In `_compute_repo_group`, populate `diff_text` with the `diff_text` it already fetched and `fetched_at` with the
  wall-clock fetch time, when the group has entries.
- This reuses the **single** existing shell-out — no second `diff` call, and the page renders straight from the
  in-memory cache.

### B. Represent each linked repo as a navigable page ("slot") in the file panel

- Add shared slot helpers (in `file_panel/_messages.py`, the existing home for cross-module constants, to avoid a new
  import cycle):
  - `LINKED_DIFF_PREFIX = "__linked_diff__:"`
  - `linked_slot_id(repo_name) -> str`, `is_linked_slot(value) -> bool`, `linked_slot_repo_name(value) -> str`. Also
    relocate `_LIVE_DIFF_SENTINEL` here (it is currently duplicated in `__init__.py` and `_display.py` with a "keep in
    sync" comment) and import it in both, eliminating the duplication.
- A linked slot encodes only the **repo name**; its workspace dir and diff text are resolved at render time from
  `get_cached_linked_delta_groups(self._current_agent)` (module-level shared cache). This keeps slots as plain strings,
  so the zoom modal's existing `_file_list` seeding continues to work with no extra plumbing.

#### Canonical page ordering

Introduce one **single source of truth** for the page list so the three existing build sites can't drift:

`_desired_file_list(agent) -> (slots, default_value)` returns, in order:

1. `_LIVE_DIFF_SENTINEL` — **iff** a cached primary diff with non-empty output exists (unchanged rule).
2. one `linked_slot_id(group.repo_name)` per cached `LinkedDeltaGroup`, in the cache's order (which follows
   `agent.linked_repos` order — stable and predictable).
3. the agent's `extra_files` (plan, screenshots, PDFs) — unchanged.

`default_value` preserves today's behavior: for a `.plan`-chain agent with no code diff, default to the plan file;
otherwise the first slot. **Make the plan-default selection value-based** (locate the plan/first extra-file path)
instead of the current hard-coded `index == 1`, since linked slots now sit between the primary sentinel and the extra
files.

#### Reconciliation (add/remove/refresh pages without clobbering the user)

Replace the ad-hoc `_pick_up_extra_files` and the manual sentinel-insertion in `on_worker_state_changed` with one method
`_reconcile_file_list(agent, *, allow_initial_display)`:

- Compute `desired, default_value = _desired_file_list(agent)`.
- If `desired == self._file_list`: if the **current** page is a linked slot whose cached `diff_text` differs from what's
  displayed (`self._last_file_content`), re-render it preserving scroll; else no-op.
- Else: remember the current page's value, set `self._file_list = desired`, choose the new index by locating that value
  (fallback to `default_value`/clamp), post `FileListChanged`, and — when `allow_initial_display` and the current page
  changed/!displayed — render the current page.

Wire it in:

- **Different-agent / full-reset path** in `_update_display_body`: build via `_desired_file_list`, then keep the
  existing "display current page now + start background primary fetch" logic, with a new branch for the current page
  being a linked slot (render from cache; still kick off the primary background fetch so the primary sentinel can
  appear).
- **Same-agent fast/stale/in-flight paths:** call `_reconcile_file_list(agent, allow_initial_display=True)` (replacing
  `_pick_up_extra_files`) so linked pages appear/update on the periodic active-agent refresh even when the primary-diff
  fast path returns early.
- **`on_worker_state_changed` SUCCESS (primary diff arrived):** call
  `_reconcile_file_list(agent, allow_initial_display=False)` to splice in the primary sentinel (preserving the user's
  current page), then keep the existing "if currently on the sentinel, repaint the refreshed diff with
  change-detection + scroll preservation" tail.

#### Make linked pages appear promptly (no heartbeat lag)

The linked-delta worker lives on the **prompt** panel; on success it currently re-renders only the prompt header. Add a
tiny notification so the sibling file panel reconciles immediately:

- In `prompt_panel/_agent_display_async.py::_apply_agent_linked_delta_worker_result` (SUCCESS, is-current),
  `post_message(LinkedDeltasRefreshed(agent_identity))` (new lightweight message).
- `AgentDetail` handles `on_linked_deltas_refreshed` by calling
  `file_panel._reconcile_file_list(current_agent, allow_initial_display=True)` when the identity matches.

Even without this, the periodic active-agent refresh would pick pages up within a heartbeat; the message just makes it
feel instant. The in-memory cache is the single source of truth either way.

### C. Render a linked page beautifully and unmistakably

Add `display_linked_diff(repo_name, workspace_dir, diff_text, fetched_at)` in `_display.py`, modeled on
`_display_file_with_timestamp` but with a **styled banner** (full color control, like the static-file header):

- `_content_mode = "linked_diff"`; store `_linked_repo_name` / `_linked_workspace_dir`; reset them in
  `_reset_trim_state`.
- `_full_content = "# Last fetched: HH:MM:SS\n\n" + diff_text`, lexer `diff` — identical line-counting / trim /
  re-render to the primary diff. `_last_file_content = diff_text` (raw) so `E` (edit) / `y` (copy) / zoom operate on the
  real diff.
- Banner `Text` reconstructed by a `_build_linked_banner()` helper:
  - line 1: `⭐ {repo_name}` in bold `COLOR_WORKSPACE_NAME`/`COLOR_WORKSPACE_GLYPH`, then a dim `· linked repo` tag —
    visually matching the header's linked-repo styling;
  - line 2: the workspace dir, dim. Grouped above the diff syntax: `Group(banner, Text(""), syntax[, indicator])`.
- **Trim parity:** add a `"linked_diff"` branch to `_render_trimmed_content` and `_render_full_content` (rebuild the
  banner via `_build_linked_banner()` so it survives `=`/`-`/page expand), and include `"linked_diff"` in the
  `_update_timestamp_header` guard.

`_display_file_at_current_index` gains a branch: when the page `is_linked_slot(...)`, look up the matching cached group
for `self._current_agent` and call `display_linked_diff(...)`; if the group is momentarily absent (e.g. the repo just
went clean and reconcile hasn't run), show a soft `⭐ {repo} — no changes` placeholder (reconcile will drop the page
next pass).

Guards: `get_current_file_path()` returns `None` for linked slots (like the sentinel) so the editor never tries to open
the sentinel string; `_handle_static_read_result`'s path-match guard explicitly ignores linked slots.

### D. Always-visible "which repo" cue: the file panel's top border

Beyond the in-content banner (which also survives zoom/edit/copy), label the **top border** of the file scroll with the
current source:

- Add `AgentFilePanel.current_source_label() -> str | None`: `"⭐ {repo}"` for a linked slot, the file basename for a
  static file, `"diff"` for the primary sentinel, `None` when empty.
- In `_agent_detail_panels.py`, set `#agent-file-scroll` `border_title` from this label in `on_file_list_changed` /
  `on_file_visibility_changed` (alongside the existing subtitle/indicator updates). Add `border-title-align: left` for
  `#agent-file-scroll` in `styles.tcss`.
- Optionally append the label to the existing prompt-scroll indicator (`● files [2/4] · ⭐ sase-core`) for extra
  redundancy.

This is a deliberate, small visual upgrade (the panel currently has no border title). It touches existing PNG goldens
that include the file panel — see Verification.

### E. Zoom modal parity

`_ZoomFilePanel` inherits everything (banner + slots). Additionally surface the source in the modal header: extend
`ZoomPanelModal._update_header` to append `current_source_label()` to the `FILE (i/n)` line so the zoomed view names the
repo too.

## What explicitly does NOT change

- No new keybinding, mode, or config value — `<ctrl+n>`/`<ctrl+p>` already cycle pages.
- No change to primary-diff fetch/cache, completed-agent (`set_file_list(all_files)`) behavior, or the "DELTAS:" header
  rendering (groups gain a field it ignores).
- No `sase-core` / Rust changes (boundary check passes — diff content already flows through the shared VCS provider).
- Completed (`Done`/`Failed`) agents get no linked pages (cache returns `()`), matching the header.

## Reliability / performance notes (per `memory/tui_perf.md`)

- The only new work on the event loop is in-memory list reconciliation + at most one render
  (`get_cached_linked_delta_groups` is a lock-guarded dict read). **No subprocess / disk I/O is added to the event
  loop.**
- The actual linked diff is still produced by the existing off-thread `compute_linked_delta_groups` worker; we only
  retain its already-computed `diff_text`.
- Current-page selection is preserved by value across refreshes (no j/k surprise); pages add/remove idempotently from
  the shared cache.

## Verification

1. **Unit / behavior tests** (extend `tests/test_file_panel.py`, `tests/ace/tui/test_file_panel_selection_preserved.py`,
   and `_linked_deltas` coverage):
   - `_compute_repo_group` populates `diff_text` / `fetched_at` (mock provider).
   - `_desired_file_list` ordering: `[sentinel, linked(a), linked(b), plan]`; plan-default is value-based.
   - Reconcile adds linked pages from a seeded cache, posts `FileListChanged`, and preserves the current page by value
     when pages are added/removed.
   - Navigating to a linked page renders the banner (repo name + workspace + `diff` lexer) and sets
     `_content_mode == "linked_diff"`; `get_current_file_path()` is `None`; `get_current_content()` is the raw diff.
   - `current_source_label()` returns `⭐ repo` / basename / `diff` / `None` appropriately.
   - Completed agents produce no linked pages.
   - Trim expand/reset on a linked page keeps the banner (`_render_full_content`/`_render_trimmed_content`).
2. **Visual snapshot:** add a new PNG golden showing the file panel on a linked-repo diff (banner + border title) under
   `tests/ace/tui/visual/snapshots/png/`. Regenerate, and review/regenerate any existing goldens that include the file
   panel now that it has a border title (`--sase-update-visual-snapshots`); enumerate and eyeball each diff.
3. **Gate:** `just install` then `just check` (lint + mypy + tests, incl. visual suite via `just test-visual`).
4. **Manual end-to-end:** launch an agent on a project with a configured linked repo that has local edits; open
   `sase ace`, select the agent; confirm `<ctrl+n>` reaches a clearly-labeled `⭐ <repo>` diff page after the primary
   diff, that the border title + banner name the repo, that zoom (and `E`/`y`) operate on the linked diff, and that a
   clean/Done linked repo shows no page.

## Files to change (sase repo only)

- `src/sase/ace/tui/widgets/file_panel/_linked_deltas.py` — add `diff_text`/`fetched_at` to `LinkedDeltaGroup`; populate
  in `_compute_repo_group`.
- `src/sase/ace/tui/widgets/file_panel/_messages.py` — slot constants/helpers; home for `LIVE_DIFF_SENTINEL`.
- `src/sase/ace/tui/widgets/file_panel/__init__.py` — `_desired_file_list`, `_reconcile_file_list` (replacing
  `_pick_up_extra_files` + manual sentinel insert), linked-slot branch in `_display_file_at_current_index`,
  `current_source_label()`, slot guards in `get_current_file_path`.
- `src/sase/ace/tui/widgets/file_panel/_display.py` — `display_linked_diff` + `_build_linked_banner`; linked-slot
  handling in the static-read path-match guard.
- `src/sase/ace/tui/widgets/file_panel/_trim.py` — `"linked_diff"` branches in re-render + timestamp guard.
- `src/sase/ace/tui/widgets/_agent_detail_panels.py` — set `#agent-file-scroll` border title from
  `current_source_label()`; optional indicator suffix.
- `src/sase/ace/tui/widgets/agent_detail.py` — `on_linked_deltas_refreshed` → reconcile file panel.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_async.py` — post `LinkedDeltasRefreshed` on worker success.
- `src/sase/ace/tui/modals/zoom_panel_modal.py` — append source label to the FILE zoom header.
- `src/sase/ace/tui/styles.tcss` — `border-title-align` for `#agent-file-scroll`.
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py` (and any `?`-popup copy) — note that `<ctrl+n>`/ `<ctrl+p>`
  also cycle linked-repo diffs.
- Tests + one new visual golden as above.

## Out of scope

- Reusing the linked diff for anything beyond viewing (no new commit/stage/apply actions).
- Changing linked-repo resolution/config (`src/sase/linked_repos.py`) or the diff computation itself.
- Linked diffs for completed agents (intentionally excluded, consistent with the header).
