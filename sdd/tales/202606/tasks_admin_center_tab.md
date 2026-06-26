---
create_time: 2026-06-26 17:29:05
status: done
prompt: sdd/prompts/202606/tasks_admin_center_tab.md
---
# Plan: Migrate the `,t` Tasks Queue panel into the SASE Admin Center as a "Tasks" tab

## 1. Goal

Retire the standalone `,t` **Task Queue** modal and re-home it as a new **Tasks** tab in the SASE Admin Center (`#`),
inserted **immediately after the Config tab** (so the order becomes
`Config → Tasks → Logs → Projects → Plugins → XPrompts`). The new tab must reproduce _everything_ the old panel did —
including its live, second-by-second streaming of running-task output — feel native to the Admin Center, and be
intuitive, reliable, and beautiful. The `,t` leader keymap is removed.

This is the same migration the **Logs** and **Projects** panels already underwent (their standalone `,L` / `,p` modals
were retired and re-homed as Admin Center tabs). We deliberately follow that precedent end-to-end so the result is
consistent with the codebase's established pattern. The one place this migration is genuinely _new_ — and where the
design must do real work — is **live auto-refresh**: unlike Logs (manual `r` only), the Tasks panel streams a running
task's output on a 1-second timer. Preserving that faithfully inside a shared, multi-pane modal is the heart of this
plan.

## 2. Background: what exists today

**The Admin Center** (`ConfigCenterModal`, `src/sase/ace/tui/modals/config_center_modal.py`) is a full-screen
`ModalScreen` hosting five tabs over a `ContentSwitcher`: `Config → Logs → Projects → Plugins → XPrompts`. Tabs are
declared in four parallel structures — `CenterTab` (a `Literal`), `_TAB_ORDER`, `_TAB_LABELS`, `_TAB_COLORS` — rendered
by a clickable `_ConfigCenterTabStrip`, and switched with `[` / `]` (modulo-wrapping) or mouse clicks. Each tab is a
`Vertical` pane with `can_focus = False`, a `focus_default()` method, its own pane-scoped `BINDINGS`, and an `id`
matching its tab name. `#` opens the modal on Config. All panes are mounted simultaneously; the inactive ones are simply
hidden by the `ContentSwitcher`.

**The Task Queue panel** (`TaskQueueModal`, `src/sase/ace/tui/modals/task_queue_modal.py`) is a two-pane modal opened
globally from any tab via `,t`. It is the live monitor for background work the app submits — sync, mail, accept, rebase,
agent launch/fan-out, kill, dismiss, rename, plugin install/uninstall/update — tracked in the app-level `TaskQueue`
registry (`src/sase/ace/tui/task_queue.py`).

- **Left (40%)** — an `OptionList` of all tasks, newest first. Each row is a status glyph (`●` running / `✓` success /
  `✗` error, colored), the task `label`, and a dim relative time (`3m ago`). When the queue is empty, a centered "No
  tasks" placeholder is shown instead (mounted/unmounted dynamically).
- **Right (60%)** — a `VerticalScroll` showing the selected task's output: live captured stdout/stderr for running tasks
  (`Text.from_ansi`), an `Error: …` block for failures, the finished ANSI output for successes, or a dim
  `Completed: <message>` fallback. The output title shows `Output — <label>`.
- **Live behavior** — a `set_interval(1, …)` timer polls the registry every second: if any task's status changed it
  rebuilds the list (preserving the highlight); otherwise it refreshes the selected running task's output and
  auto-scrolls to the bottom _unless the user has scrolled up_ (tracked by a `_user_scrolled` flag, reset when a
  different task is highlighted). On open it `prune_old()`s the registry.
- **Keybindings** — `j/k` · `↓/↑` navigate tasks (the modal deliberately drops `ctrl+n/p`); `d` dismiss the selected
  completed task; `D` dismiss all completed; `K` kill the selected running task (after a `ConfirmActionModal`); `e` open
  the output in `$EDITOR` (via `app.suspend()`); `y` copy the output to the system clipboard; `ctrl+d` / `ctrl+u`
  half-page scroll the output; `esc` / `q` close.
- The top-bar `TaskIndicator` badge (`⚙ N`) shows the running count and is **independent** of this modal.

The pure helpers in `task_queue_modal.py` (`_relative_time`, the `_STATUS_DISPLAY` glyph/style map) are module-level.
The backend `TaskQueue`/`TaskInfo` registry and the app-level lifecycle (`task_actions.py`: `_submit_*`,
`_kill_background_task`, `_update_task_indicator`, completion routing) are independent of the modal and stay put.

Note the asymmetry vs. Logs: the Task Queue panel currently has **no command-palette entry** — it is reachable _only_
via `,t` (it does surface as the auto-generated `leader.task_queue` palette command, which disappears the moment the key
is retired). So removing `,t` would orphan the panel unless we add a keyless command, exactly as the Logs/Projects
migrations did.

## 3. Design

### 3.1 Shape — a native Admin Center pane that keeps the two-pane live monitor

Create `TasksPane(Vertical)` modeled on `LogsPane`/`ProjectsPane`, keeping the panel's beloved two-pane "browse left,
watch right" layout but dressing it in the Admin Center's visual idiom: a bold pane title with a **live count**,
bordered panels with `config-region-header` "Tasks"/"Output" headers (the same class every other tab uses), and a bottom
hints line matching the other panes' format.

```
Tasks  [2 running · 5 done]                  ← pane title (live count)
┌ Tasks ──────────────┐ ┌ Output — sync sase-42 ────────────────┐
│ ● sync sase-42  3s   │ │ Syncing sase-42…                       │  ← live ANSI tail,
│ ● launch fanout foo  │ │ remote: Enumerating objects: 1240      │    auto-scrolls while
│ ✓ mail sase-41  2m   │ │ remote: Counting objects: 100% (…)     │    running unless the
│ ✗ rebase sase-40 5m  │ │ …                                      │    user scrolls up
│ ✓ accept sase-39 9m  │ │                                        │
└──────────────────────┘ └────────────────────────────────────────┘
j/k: move  d/D: dismiss  K: kill  e: edit  y: copy  ctrl+d/u, g/G: scroll  [ / ]: tab  Esc: close
```

The right detail keeps the same `scrollbar-gutter: stable` treatment as the Logs/Config detail so live output doesn't
jump horizontally when the scrollbar appears.

### 3.2 Reuse, don't reimplement — move the UI logic, keep the registry and lifecycle

- The backend `TaskQueue`/`TaskInfo` registry (`task_queue.py`) and all app-level submission/kill/indicator logic
  (`task_actions.py`) are **unchanged** — they are the backend↔UI contract and are independent of the modal. This keeps
  every existing submit/dedup/kill/quit-confirm path and its tests valid.
- The view logic moves into `tasks_pane.py`: the `compose`, list-building, output-rendering, live-refresh, and action
  methods migrate from `task_queue_modal.py` essentially as-is, restructured to the pane idiom (pane-scoped nav actions
  that delegate to the `OptionList` cursor, like `LogsPane`/`ConfigPane`, instead of `OptionListNavigationMixin` whose
  `escape`/`q` are screen-oriented). The pure helpers `_relative_time` and `_STATUS_DISPLAY` move verbatim.
- `task_queue_modal.py` is deleted; `TaskQueueModal` is removed from `modals/__init__.py`; the now-dead
  `_show_task_queue_modal` app method is removed from `task_actions.py`.

### 3.3 The live-refresh decision (the one genuinely new design problem)

The pane owns the same `set_interval(1, …)` poll the modal had, started in `on_mount` and stopped in `on_unmount`. Two
deliberate calls make it safe inside a shared, all-panes-mounted modal:

1. **The timer no-ops when Tasks isn't the visible tab.** The poll callback returns early unless `self._is_active_tab()`
   (the same `screen._active_tab == self.id` check `LogsPane` already uses). So when the user is on Config/Logs/etc.,
   the hidden Tasks pane does zero UI work — no list rebuilds, no output churn — while the modal is open. Registry reads
   are in-memory and cheap; the guard removes even those from the hot path when hidden.
2. **Switching to the tab refreshes immediately.** `focus_default()` (called by the host on tab activation _and_ on
   initial open) renders the current snapshot and selects the newest task, so the user never waits up to a second for
   the first paint. The pane is created fresh each time `#` opens the modal, so its lifecycle matches the old
   open-on-demand modal exactly (including `prune_old()` on mount).

This preserves the live-streaming feel precisely while respecting the Admin Center's "many panes, one visible"
architecture. The `_user_scrolled` auto-scroll-suppression behavior moves over unchanged.

### 3.4 The data/callback wiring — the pane reaches the app, no constructor plumbing

The old modal was constructed with `TaskQueueModal(app._task_queue, kill_callback=app._kill_background_task)`. The pane
instead reads these from `self.app` lazily (the Admin Center is pushed on the `AceApp`, which mixes in
`TaskActionsMixin`, so `self.app._task_queue` and `self.app._kill_background_task` are always present at runtime). A
thin accessor tolerates their absence (returns an empty task list / no-op kill) so the pane degrades gracefully in
isolation.

This is the key reason **`ConfigCenterModal`'s constructor stays unchanged** — it is instantiated from many call sites
(`action_open_config_center`, the Projects/Logs openers, and numerous tests) and must not grow a required argument.
`kill` confirmation (`ConfirmActionModal`), `$EDITOR` editing (`app.suspend()`), and clipboard copy + `notify` all work
unchanged from a widget via `self.app` — the same APIs the modal used.

### 3.5 Key interaction decisions (the deliberate design calls)

1. **`[` / `]` belong to tab switching, not in-pane motion.** Inside the Admin Center, `[` / `]` is the universal
   prev/next-tab gesture; the `OptionList` doesn't bind them, so they bubble to the host modal automatically. The old
   panel never used `[` / `]`, so nothing is lost.

2. **Action keys are pane-scoped and don't collide.** `d`, `D`, `K`, `e`, `y`, `ctrl+d`, `ctrl+u` (and the added
   `g`/`G`) live in `TasksPane.BINDINGS`. Because Textual bindings fire only when focus is within the pane, and exactly
   one pane is ever active, these never clash with the Config pane's `e`/`r`/`g` or any other tab — the same
   pane-scoping the Logs tab already relies on. Navigation is `j/k` and `↓/↑` (we keep the old panel's deliberate
   omission of `ctrl+n/p`).

3. **Output scrolling: keep `ctrl+d`/`ctrl+u`, add `g`/`G` for consistency.** `ctrl+d`/`ctrl+u` half-page scroll is
   preserved verbatim (mandatory parity). We additionally bind `g`/`G` to jump the output to top/bottom — the Admin
   Center's established detail-scroll gesture (Logs has it) — by **generalizing the host modal's existing g/G
   forwarder** from "logs only" to "any active pane exposing `action_scroll_to_top`/`action_scroll_to_bottom`."
   `TasksPane` implements those two actions; `LogsPane` already does, so its behavior is identical. This is a small,
   net-positive consistency win, not parity-critical — easy to drop in review if undesired.

4. **`esc` / `q` close the whole Admin Center**, via the host modal's existing bindings — no per-pane dismiss (we drop
   `OptionListNavigationMixin`, whose `escape`/`q` call the screen's `dismiss`).

5. **Empty state is rendered, not mounted.** Rather than the old modal's dynamic mount/unmount of a "No tasks" `Static`
   (a fiddly, bug-prone bit), the pane keeps the `OptionList` always present and shows a friendly centered "No
   background tasks yet." in the detail pane when the queue is empty. This is a deliberate **reliability** improvement —
   fewer moving widgets, no mount races during live refresh — with no capability loss.

6. **Tasks gets its own tab color** in `_TAB_COLORS`: a clear green (proposed `#5FD75F`) that echoes the running-task
   `●` glyph and sits naturally in the strip between Config's teal and Logs' gold. Easy to retune during review.

7. **Live count in the title.** `Tasks  [N running · M done]`, updated each refresh — mirroring `Logs  [… active]` and
   giving an at-a-glance status that the bare "Task Queue" title never did.

### 3.6 Access path after `,t` is removed (mirrors the Logs/Projects migrations)

- **Primary:** `#` opens the Admin Center; `]` once lands on Tasks (the tab immediately right of Config).
- **Fast path:** a **keyless command-palette entry** "Open tasks panel" (aliases `tasks`, `task queue`,
  `background tasks`, `jobs`, `queue`) that opens the Admin Center pre-focused on Tasks — exactly mirroring the keyless
  "Open logs panel" / "Open project management panel" commands. Backed by a new `open_tasks_panel` app action that does
  `ConfigCenterModal(initial_tab="tasks")`. `tasks` / `task queue` are also added to the `open_config_center` aliases so
  `#`-search finds it too.
- The top-bar `TaskIndicator` badge is **unchanged** and remains the always-on running-count cue.

## 4. Functionality parity checklist (nothing left out)

| Old `,t` capability                                | New Tasks tab                                          |
| -------------------------------------------------- | ------------------------------------------------------ |
| List all tasks, newest first, status glyph + time  | ✅ list-building moved verbatim                        |
| Live running-output streaming (1s poll)            | ✅ pane-owned timer, active-tab-guarded (§3.3)         |
| Status-change → rebuild list, preserve highlight   | ✅ moved verbatim                                      |
| Auto-scroll output unless user scrolled up         | ✅ `_user_scrolled` flag moved verbatim                |
| Error / success / running / completed render modes | ✅ output renderer moved verbatim                      |
| `d` dismiss completed                              | ✅ pane action                                         |
| `D` dismiss all completed                          | ✅ pane action                                         |
| `K` kill running (with confirm modal)              | ✅ pane action → `ConfirmActionModal` on `self.app`    |
| `e` edit output in `$EDITOR`                       | ✅ pane action → `self.app.suspend()`                  |
| `y` copy output to clipboard                       | ✅ pane action → `copy_to_system_clipboard` + `notify` |
| `j/k` · `↓/↑` navigate (no `ctrl+n/p`)             | ✅ pane nav actions → `OptionList` cursor              |
| `ctrl+d/u` half-page output scroll                 | ✅ pane bindings                                       |
| _(new)_ `g`/`G` output top/bottom                  | ➕ added for Admin Center consistency (§3.5.3)         |
| Empty "No tasks" state                             | ✅ rendered in detail (more reliable; §3.5.5)          |
| `prune_old()` on open                              | ✅ in `on_mount`                                       |
| Top-bar `⚙ N` indicator                            | ✅ unchanged (independent of the modal)                |
| Opens from any context                             | ✅ `#` from any tab; keyless command anywhere          |
| `esc`/`q` close                                    | ✅ host modal bindings                                 |

## 5. Implementation breakdown

### Create

- **`src/sase/ace/tui/modals/tasks_pane.py`** — `TasksPane(Vertical)`: `compose()` (title + Tasks/Output panels +
  hints), `on_mount` (`prune_old`, render snapshot, start 1s timer), `on_unmount` (stop timer), `focus_default` (focus
  list + immediate refresh), the live-poll callback (active-tab-guarded), list-building + output-rendering, the
  `_user_scrolled` handling, and actions `dismiss_task` / `dismiss_all_done` / `kill_task` / `edit_output` /
  `copy_output` / `scroll_output_down` / `scroll_output_up` / `scroll_to_top` / `scroll_to_bottom` / nav. The
  `_relative_time` and `_STATUS_DISPLAY` helpers move here.

### Modify

- **`config_center_modal.py`** — add `"tasks"` to `CenterTab`, `_TAB_ORDER` (index 1, after config), `_TAB_LABELS`,
  `_TAB_COLORS`; import `TasksPane`; `yield TasksPane(id="tasks")` as the second pane in the `ContentSwitcher`.
  Generalize `on_key`'s g/G forwarder from the `logs`-only guard to "active pane has scroll-to-top/bottom actions."
- **`styles.tcss`** — add `TasksPane` to the shared `ConfigCenterModal <Pane>` width/height rule; add `TasksPane`-scoped
  rules for the panels, list, and output scroll (adapt the existing `TaskQueueModal` block to the panel idiom). Remove
  the old `/* ===== Task Queue Modal Styling ===== */` block.
- **`actions/base.py`** — add `action_open_tasks_panel` → `ConfigCenterModal(initial_tab="tasks")` (mirrors
  `action_open_log_panel`).
- **`commands/catalog.py`** + **`commands/_app_metadata.py`** — add a keyless `_iter_tasks_command` registered in
  `build_command_catalog` (mirror `_iter_logs_command`); add `tasks` / `task queue` to the `open_config_center` aliases.
- **`commands/_mode_commands.py`** — remove the now-stale `_LEADER_LABELS["task_queue"]` entry.
- **`modals/__init__.py`** — drop the `TaskQueueModal` import/export.
- **`actions/task_actions.py`** — remove the dead `_show_task_queue_modal` method (keep everything else).

### Remove `,t`

- **`src/sase/default_config.yml`** (line 206) and **`keymaps/types.py`** (line 447) — delete `task_queue: "t"` from
  leader-mode keys (kept in parity, per the keymap convention).
- **`keymaps/loader.py`** — add `"task_queue"` to `_RETIRED_LEADER_KEYS` so any stale user override of the old key is
  filtered out (mirrors the `log_panel` retirement).
- **`actions/agent_workflow/_leader_mode.py`** (lines 184–188) — delete the `task_queue` dispatch branch.
- **`widgets/_keybinding_modes.py`** (line 245) — delete the `bindings.append((k("task_queue"), "task queue"))`
  leader-footer entry.

### Help & docs

- **`help_modal/changespecs_bindings.py`** (lines 209–212) — remove the `,t` "Task queue viewer" leader entry. (Unlike
  `,L`, this entry exists only in the changespecs help, so agents/axe help need no change.)
- Update the `#` Admin Center description in the three help binding files to include Tasks, keeping within the 57-char
  box (abbreviate the tab list, e.g. `Admin Center: Config/Tasks/Logs/Projects/…`).
- **`docs/ace.md`** — remove the `,t` row from the leader keymap table (line ~214); rewrite the `## Task Queue Modal`
  section (line ~2071) to describe the **Tasks** tab in the Admin Center and its access (`#` then `]`, or the keyless
  "Open tasks panel" command).

### Delete

- **`src/sase/ace/tui/modals/task_queue_modal.py`** (logic moved to `tasks_pane.py`).

## 6. Tests

### New / migrated

- **`tests/ace/tui/test_tasks_pane.py`** — pilot tests opening `ConfigCenterModal(initial_tab="tasks")` against an app
  whose `_task_queue` is seeded: assert tasks listed newest-first with correct glyphs, first task selected + output
  rendered, `j/k` updates the output pane, live refresh updates a running task's output and rebuilds on status change,
  `d`/`D` dismiss, `K` opens the confirm modal and removes on confirm, `e`/`y` guard on empty output, `ctrl+d/u` and
  `g/G` scroll the output, empty-state message renders, `focus_default` focuses the list. (Drive refresh by calling the
  poll method directly rather than waiting on the timer, to avoid flakiness.) Plus unit coverage for `_relative_time`.
- **Visual snapshot** — add `_open_tasks_modal` + a task-seeding helper to
  `tests/ace/tui/visual/_ace_config_center_png_snapshot_helpers.py`; add
  `tests/ace/tui/visual/test_ace_png_snapshots_config_center_tasks.py`; generate the golden
  `config_center_tasks_tab_120x40.png` with `--sase-update-visual-snapshots`. **Determinism note:** relative times come
  from `datetime.now()`, so the test must freeze the pane's time source (monkeypatch `tasks_pane`'s `_relative_time` /
  clock) and seed fixed `started_at`/`finished_at` so the snapshot is stable.

### Update (these break from the tab insertion / key retirement — all identified)

- **`tests/test_keymaps_defaults.py`** — add `test_leader_mode_drops_task_queue_key` (mirror the `log_panel` test).
- **`tests/ace/tui/test_leader_keybinding_footer.py`** — add `test_footer_omits_task_queue_after_cutover`.
- **`tests/test_command_catalog.py`** — replace the `assert "leader.task_queue" in ids` (line ~303) with a
  `test_tasks_command_is_keyless_and_global` (mirror `test_logs_command_is_keyless_and_global`); add `"tasks"` to the
  keyless-exemption set in `test_command_specs_are_well_formed`.
- **`tests/test_command_catalog_guards.py`** — add `"tasks"` to the keyless exemption in
  `test_every_command_spec_has_label_and_key_display`.
- **`tests/test_command_palette_modal.py`** (lines ~166–174) — replace the `leader.task_queue` / "Task queue" filter
  assertions with the new keyless `tasks` command.
- **`tests/test_command_palette_wiring.py`** (lines ~322, ~338) — replace the `leader.task_queue` execute test with
  `tasks` → `action_open_tasks_panel` (mirror `test_execute_logs_command_uses_app_action`).
- **`tests/ace/tui/test_plugins_browser_pane_loading.py`** — `test_config_center_cycles_five_tabs` (line ~142) becomes a
  six-tab cycle: `config → tasks → logs → projects → plugins → xprompts → config` (rename accordingly).
- **`tests/ace/tui/test_log_panel_keymap.py`** — `test_logs_tab_sits_immediately_after_config`
  (`_TAB_ORDER[:2] == ("config","logs")`, line ~48) updates to `("config","tasks")` (logs now at index 2); add a
  `test_tasks_tab_sits_immediately_after_config` assertion.
- **`tests/ace/tui/test_logs_pane.py`** — `test_brackets_switch_admin_center_tabs_not_log_sources` (line ~210): `[` from
  Logs now lands on **Tasks**, not Config — update that one assertion.
- _(Audited & unaffected:_ `tests/ace/tui/test_projects_pane.py` — its `[`/`]` assertions check Projects' neighbors
  (Logs ←, Plugins →), which don't move when Tasks is inserted before Logs.)_

### Verify

- Run `just install` first (ephemeral workspace), then `just check` (lint + mypy + `just test`) green; run
  `just test-visual` for the PNG suite.

## 7. Boundary & risk notes

- **Rust core boundary (`memory/rust_core_backend_boundary.md`):** none crossed. The `TaskQueue` registry is in-memory
  Python TUI state with no cross-frontend contract; this change is presentation-only Textual state (a tab swap + view
  relocation), so no `../sase-core` changes are needed.
- **Risk — live timer in a shared modal:** mitigated by the active-tab guard (§3.3) and explicit `on_unmount` stop; the
  pane is created/destroyed per modal-open, matching the old modal's lifecycle.
- **Risk — broken tab-order / command-palette tests:** inserting a tab shifts Config's and Logs' `[`/`]` neighbors, and
  retiring the key removes the `leader.task_queue` palette command. Every affected test is enumerated in §6 and updated
  as part of the change.
- **Risk — snapshot non-determinism** from relative times: addressed by freezing the time source in the visual test
  (§6).
- **Risk — help-modal width:** adding "Tasks" to the `#` description must stay within the 57-char box
  (`src/sase/ace/AGENTS.md`); abbreviate the tab list as needed.

## 8. Out of scope (possible future polish, not in this change)

- A `/` filter/search over tasks (other tabs have one); low value for a typically-short, transient queue, so deferred to
  keep this a faithful, reliable migration.
- Making the output pane independently focusable for native PageUp/PageDown.
- Auto-selecting a newly-submitted task while the tab is open (today selection is user-driven; preserved as-is).
- Renaming the backend `TaskQueue`/`task_queue` concept (it stays; only the user-facing surface becomes the "Tasks"
  tab).
