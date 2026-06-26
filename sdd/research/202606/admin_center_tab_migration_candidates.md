---
create_time: 2026-06-26
updated_time: 2026-06-26
status: research
---

# SASE Admin Center — Pop-up Panel → New Tab Migration Candidates

## Research Request

We recently added/improved the SASE Admin Center panel in the TUI by adding new tabs to it. Find new opportunities to
integrate existing TUI pop-up panels into the Admin Center as new tabs, and recommend the top 3 candidates for
migration.

## Bottom Line

The three strongest candidates to become new Admin Center tabs are:

1. **Runners panel** (`,R` → `runners_modal.py`) — the system-wide "what's running right now" overview. It is the most
   *admin-flavored* surface still living as a standalone modal.
2. **Task Queue panel** (`,t` → `task_queue_modal.py`) — the global background-task manager. Its list+detail layout
   already matches the Plugins/XPrompts pane shape, and migrating it exposes a consolidation opportunity with the
   Runners panel's "Background Tasks" section.
3. **Prompt Stash panel** (`@` → `stashed_prompts_modal.py`) — the lowest-effort, cleanest migration; it pairs
   thematically with the existing XPrompts tab as "prompt resource" management.

The **Notification Center** (`i` → `notification_modal.py`) is the single best *architectural* precedent — it already
uses the exact `[`/`]` sub-tab navigation the Admin Center adopted — but it is deliberately **excluded** from the top 3
because it is a high-frequency inbox; burying it two levels deep under `#` would be a UX regression (see
[Honorable Mentions](#honorable-mentions--deliberately-excluded)).

## What the Admin Center Is Today

The "SASE Admin Center" is a full-screen `ModalScreen` (renamed from "SASE Config" in `b9c3692ee`) that hosts four
internal tabs over a `ContentSwitcher`:

| Tab | Pane widget | Source | Former standalone surface |
| --- | --- | --- | --- |
| Config | `ConfigPane` | `config_pane.py` | new (schema-driven editor skeleton) |
| Projects | `ProjectsPane` | `projects_pane.py` | the `,p` project-management modal (now deleted) |
| Plugins | `PluginsBrowserPane` | `plugins_browser_pane.py` | mirrors `sase plugin list` |
| XPrompts | `XPromptBrowserPane` | `xprompt_browser_pane.py` | the standalone XPrompt Browser modal |

Key facts (`src/sase/ace/tui/modals/config_center_modal.py`):

- `#` opens the modal on the **Config** tab; `[` / `]` cycle tabs with modulo wrapping
  (`config_center_modal.py:119-124`, `:186-198`).
- The tab order/labels/colors are declared in three small literals (`_TAB_ORDER`, `_TAB_LABELS`, `_TAB_COLORS`,
  `config_center_modal.py:41-53`) — adding a tab is a localized change.
- Panes are mounted in `compose()` (`config_center_modal.py:144-148`) and switched via the `ContentSwitcher`.

### The pane contract

Each tab is a plain `Widget` that **may** implement `focus_default()`. On open / tab-switch, the modal calls it to put
focus on the pane's natural starting widget (`config_center_modal.py:160-164`). All four current panes implement it:

- `plugins_browser_pane.py:156`, `projects_pane.py:173`, `xprompt_browser_pane.py:319`, `config_pane_widget.py:127`.

This is the *only* hard requirement a modal must satisfy to become a tab. The migration pattern observed across
sase-54 (XPrompts), sase-59 (Plugins), and sase-5a (Projects) is:

1. Decompose the modal's logic into reusable **action mixins** + **rendering helpers** (most candidates were already
   split this way for testability).
2. Wrap the compose/widget structure in a `*Pane` widget implementing `focus_default()`.
3. Register the pane in the three tab literals + `compose()`.
4. Delete the standalone modal and its leader key, replacing access with a command-palette entry (e.g. `,p` was removed
   in `5a6a9bb28`).

## Migration Criteria (derived from precedent + planning docs)

From `sase_config_tui_panel_ux_consolidated.md` ("Recommended Surface"): a surface belongs as a top-level **main-tab-bar
tab** only if it is *continuously monitored* (ChangeSpecs, Agents, AXE). A *focused management task opened occasionally*
belongs in the Admin Center, reached via `#` + `[`/`]`.

A modal is a **good Admin Center tab candidate** when it is:

- **App-global**, not per-entity. It manages a collection (all runners, all tasks, the stash) rather than acting on the
  currently-selected ChangeSpec/Agent. (Per-entity modals lose meaning when you tab away from the selection.)
- **A persistent browser/manager**, not a transient prompt. You navigate a list, view details, take management
  actions, and stay open — rather than "pick one thing / confirm / type, then close."
- **Opened occasionally from a global leader key**, not continuously watched (those stay in the main tab bar) and not a
  blocking step inside another workflow.
- **Cleanly separable** into reusable action/rendering logic (so the pane reuses, not forks, the modal's behavior).

A modal should **stay a modal** when it is per-entity, a brief confirm/input/select dialog, or a blocking step inside a
workflow (e.g. HITL approval).

## Full Candidate Survey

Every modal reachable from a global keybinding (or otherwise app-global), classified against the criteria. Verified by
reading the modal sources and `src/sase/default_config.yml` keymaps.

| Modal | Invocation | Scope | Nature | LOC | Verdict |
| --- | --- | --- | --- | --- | --- |
| `runners_modal.py` | `,R` (leader) | App-global | Persistent sectioned browser | ~619 | **TOP 3** |
| `task_queue_modal.py` | `,t` (leader) | App-global | Persistent list+detail | ~414 | **TOP 3** |
| `stashed_prompts_modal.py` | `@` (global) | App-global | Persistent manager | ~273 (+row/pin helpers) | **TOP 3** |
| `notification_modal.py` | `i` (global) | App-global | Persistent browser **w/ `[`/`]` sub-tabs** | ~1,486 (6 files) | Honorable mention (high-frequency; excluded) |
| `activity_modal.py` | `,i` (leader) | App-global | Read-only dashboard | ~293 | Honorable mention (monitoring, not mgmt) |
| `prompt_history_modal.py` | `.` (prompt bar) | App-global | Browser, but bar-coupled | ~462 (+3 helpers) | Honorable mention (needs decouple refactor) |
| `saved_agent_group_revival_modal.py` | `R` on Agents tab | App-global | Browser inside a revive callback | ~667 | Maybe (embedded in revive flow) |
| `temporary_llm_override_modal.py` | `,o` (leader) | App-global | Multi-step wizard | ~448 | Reject (transient wizard) |
| `model_picker_modal.py` | child of `,o` | App-global | Transient picker | ~582 | Reject (picker) |
| `custom_model_input_modal.py` | child of picker | App-global | One-field input | ~75 | Reject (input) |
| `command_history_modal.py` | bgcmd `!` flow | App-global | Transient picker | ~271 | Reject (workflow picker) |
| `hook_history_modal.py` | hooks `.` hint | App-global | Transient picker + delete | ~183 | Reject (hint-mode workflow) |
| `mentor_review_modal.py` | `,m` (leader) | **Per-ChangeSpec** | Persistent browser | ~671 | Reject (per-entity) |
| `mentor_profile_select_modal.py` | child of `,m` | Transient | Picker | ~149 | Reject (picker) |
| `workflow_select_modal.py` | `r` on ChangeSpec | Transient | Picker | ~42 | Reject (picker) |
| `workflow_hitl_modal.py` | workflow step | Transient | **Blocking** approval | ~188 | Reject (blocking) |
| `save_agent_group_modal.py` | `s` (marked agents) | Per-selection | Input prompt | ~85 | Reject (input) |
| confirm/input/name/select/duration/snooze dialogs | various contextual | Per-entity | Transient | small | Reject (dialogs) |

## Detailed Analysis — Top 3

### 1. Runners panel (`,R` → `runners_modal.py`)

- **What it is:** A real-time, system-wide overview organized into sections — Manual Agents, Axe Agents, Running
  Processes, Background Tasks — with jump-to-entry navigation (hint keys) into the main views.
- **Why it fits:** It is app-global (system-wide, not tied to a selection), persistent (you browse and jump, it stays
  open), and reached by an occasional leader key (`,R`, `default_config.yml:190`). Semantically it is the most
  *"admin"* of all the remaining modals — a control-room view of everything the daemon is doing. That makes it the
  most natural thematic addition to a panel literally named "Admin Center."
- **Structural fit:** ~619 LOC, already a sectioned list browser with its own rendering/jump helpers. It reads as a
  monitoring surface, so the pane would implement `focus_default()` to focus the list.
- **Caveat:** It currently spans the full screen and shows live state. As a tab it shares the modal's frame width;
  needs light TCSS adaptation. Its jump-to-entry behavior closes the modal to navigate the underlying view — that
  contract (jump then dismiss the Admin Center) should be preserved.

### 2. Task Queue panel (`,t` → `task_queue_modal.py`)

- **What it is:** A list+detail manager of background tasks (running / success / error) with a live-output right pane
  that polls ~1×/sec; supports dismiss, kill, edit-in-`$EDITOR`, and copy.
- **Why it fits:** App-global background-task store, persistent browser, occasional leader key (`,t`,
  `default_config.yml:206`). Its **left-list + right-detail** layout is the closest existing match to the
  `PluginsBrowserPane`/`XPromptBrowserPane` panes already in the Admin Center, so it would feel native.
- **Bonus — consolidation opportunity:** The Runners panel *also* renders a "Background Tasks" section. Migrating both
  surfaces into the Admin Center is the natural moment to decide whether "Background Tasks" should live in one place
  (a Tasks tab) rather than be duplicated across two panels. If both land, consider Runners = live agents/processes and
  Tasks = the queue, to avoid overlap.
- **Caveat:** The 1-second auto-refresh timer must be tied to the pane's mount/unmount (or tab-visibility) so a
  hidden tab doesn't keep polling — a TUI-performance concern (see `memory/tui_perf.md`).

### 3. Prompt Stash panel (`@` → `stashed_prompts_modal.py`)

- **What it is:** A unified manager for the prompt stash (`~/.sase/prompt_stash.jsonl`): newest-first list with age,
  project chip, bundle marker, pin indicator, preview; restore/pop, toggle-pin, and delete with multi-select.
- **Why it fits:** App-global persistent store, manager-style multi-action UI, already reached by a global top-level key
  (`@` = `restore_prompt_stash: "at"`, `default_config.yml:98`). It is the **lowest-effort** migration in the set
  (~273 LOC core, single OptionList, minimal coupling) and it pairs thematically with the existing **XPrompts** tab —
  the Admin Center would then own all "prompt resource" management (authored xprompts + stashed prompts) in one place.
- **Caveat:** Its `update_pinned_stash_modal.py` sub-flow stays a nested modal launched from the pane (fine — Projects
  already spawns child modals from pane actions). The `@` global key can be retained as a shortcut that opens the Admin
  Center directly on the Stash tab, preserving muscle memory.

## Honorable Mentions / Deliberately Excluded

- **Notification Center (`i` → `notification_modal.py`)** — The strongest *architectural* precedent: it already
  implements `[`/`]` sub-tab navigation (`notification_modal.py:62-63, 393-405`) across HITL / Errors / General / Done /
  custom-tags / Muted, and the Admin Center docstring explicitly says it mirrors "the notification panel's sub-tab
  navigation." **Excluded from the top 3 on purpose:** notifications are a *high-frequency inbox*, the kind of
  continuously-watched surface the criteria say should stay quick-access, not be nested under `#` → tab. It is also the
  largest surface (~1,486 LOC across 6 files), and nesting its own sub-tabs inside an Admin Center tab risks
  `[`/`]` keybinding ambiguity. If anything, it is a candidate for its *own* main-tab-bar tab, not an Admin Center tab.
- **Activity Dashboard (`,i` → `activity_modal.py`)** — App-global and would work as a read-only "Activity" tab, but it
  is *telemetry/monitoring* rather than management, so it sits slightly outside the Config/Projects/Plugins/XPrompts
  theme. Reasonable as a later, low-cost addition.
- **Prompt History (`.` → `prompt_history_modal.py`)** — High user value as a searchable prompt archive, but it is
  tightly coupled to `PromptInputBar` ("load into bar" actions assume a mounted bar). Viable only after a refactor that
  decouples its result actions. Pairs with the Stash tab conceptually.
- **Saved Agent Group Revival (`R` on Agents → `saved_agent_group_revival_modal.py`)** — App-global browser, but it is
  embedded in a revive *callback flow* (selecting a group resumes a specific workflow). Migrating it would shift it from
  "task modal" to "admin utility," which changes its UX role; revisit only if agent restoration becomes a standalone
  admin function.

## Explicitly Rejected (and why)

These are not Admin Center material — they are transient prompts, per-entity actions, or blocking workflow steps:

- **Per-entity / per-ChangeSpec:** `mentor_review_modal.py` (tied to the selected CL's mentors),
  `save_agent_group_modal.py` (acts on marked agents).
- **Transient pickers / inputs:** `model_picker_modal.py`, `custom_model_input_modal.py`,
  `mentor_profile_select_modal.py`, `workflow_select_modal.py`, `command_history_modal.py`, `hook_history_modal.py`,
  plus the confirm/rename/tag/duration/snooze dialog family.
- **Multi-step wizards / blocking:** `temporary_llm_override_modal.py` (override → model → duration chain),
  `workflow_hitl_modal.py` (blocks workflow execution awaiting approval).

## Implementation Notes (for whoever picks this up)

- Adding a tab is a localized change: extend `_TAB_ORDER`, `_TAB_LABELS`, `_TAB_COLORS`, and `compose()` in
  `config_center_modal.py:41-148`, and have the new pane implement `focus_default()`.
- Preserve the legacy leader/global keys as shortcuts that open the Admin Center on the corresponding tab (the
  `initial_tab` argument already supports this, `config_center_modal.py:126-136`), so existing muscle memory keeps
  working even after the standalone modal is removed.
- Follow the sase-5a/-59 decomposition: move logic into reusable mixins/helpers first, then wrap in a pane — do not
  fork behavior.
- **Rust core boundary:** any shared backend behavior these panels rely on (runner enumeration, task-queue state, stash
  storage) belongs behind `sase_core_rs` per `memory/rust_core_backend_boundary.md`; the migration is
  presentation-only and should keep calling through existing adapters, not reimplement core logic.
- **TUI performance:** the Task Queue panel's poll timer (and any Runners refresh) must be gated on tab visibility /
  pane mount so hidden tabs don't refresh in the background; consult `memory/tui_perf.md` before wiring refresh loops.
- Remember the cross-cutting maintenance rules: update `?` help content, the help modal bindings, and
  `default_config.yml` keymaps for any binding changes (see `src/sase/ace/AGENTS.md` and `memory/gotchas.md`).

## Sources Verified

- `src/sase/ace/tui/modals/config_center_modal.py` (tab model, pane contract, `initial_tab`).
- Pane `focus_default()` implementations: `plugins_browser_pane.py:156`, `projects_pane.py:173`,
  `xprompt_browser_pane.py:319`, `config_pane_widget.py:127`.
- `src/sase/default_config.yml` keymaps: `restore_prompt_stash:"at"` (98), `show_notifications:"i"` (128),
  `runners:"R"` (190), `activity_info:"i"` (203), `task_queue:"t"` (206), `temporary_llm_override:"o"` (212).
- Notification sub-tab navigation: `notification_modal.py:62-63, 393-405`.
- Each candidate/rejected modal source (purpose, scope, nature, LOC) under `src/sase/ace/tui/modals/`.
- Prior planning/criteria: `sdd/research/202606/sase_config_tui_panel_ux_consolidated.md`,
  `sdd/epics/202606/projects_admin_center_tab.md`.
- Migration precedent commits: `b9c3692ee` (rename to Admin Center), `be370bd2c`/`5a6a9bb28` (Projects tab/cutover),
  `d4a75326d` (Plugins epic).
