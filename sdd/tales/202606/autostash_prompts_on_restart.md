---
create_time: 2026-06-29 06:58:00
status: done
prompt: sdd/prompts/202606/autostash_prompts_on_restart.md
---
# Plan: Auto-stash prompt drafts before a TUI restart

## Problem / product context

When a user presses `S` ("Sase update") on the **Updates** tab of the **SASE Admin Center** panel, SASE runs
`sase update` as a tracked background task. If that update actually changed installed code, the TUI **restarts itself**
(re-execs the process) to load the new code.

The restart tears down the running Textual app. Any draft the user had typed into the prompt input bar — including a
long, carefully-written multi-pane prompt — is **silently lost**, because nothing captures the in-progress draft before
the process re-execs.

**Goal:** Before the TUI restarts, automatically stash the current prompt draft as a single **bundle** into the existing
prompt-stash store, so the draft survives the restart and can be restored afterward. This makes update-triggered
restarts non-destructive to unsent work.

## Background: how the restart and stash systems already work

### The restart flow (the trigger)

`S` → `action_update_sase()` → preview → confirm modal → `_submit_sase_update_task()` → completion callback →
`_handle_code_update_completion()` → (only if code actually changed) `_restart_after_update()` →
**`AceApp._restart_tui(restart_axe=True)`**.

`_restart_tui` (`src/sase/ace/tui/actions/axe.py:219`) is the **single choke point** for restarts: it sets
`self.exit_action`, stops the stall watchdog, `_kill_all_running_tasks()`, then `_do_quit()`. After `app.run()` returns,
`src/sase/main/ace_handler.py` re-execs via `os.execv` based on `exit_action`.

`_restart_tui` is reached by **every** restart path, and only those:

- The `S` sase-update restart (`plugins_browser_sase_update.py:399`) — the case in this request.
- The plugin code-update restart (`plugins_browser_update.py` → `_restart_after_update`).
- The Quit modal's "Restart TUI" / "Restart TUI and axe" options (`axe.py:188`).

It is **not** reached by a plain quit (the `QUIT` exit action goes straight to `_do_quit()`), so hooking `_restart_tui`
preserves drafts on any _restart_ without changing ordinary _quit_ behavior (where unsent text already flows to
cancelled prompt history).

`_restart_tui` runs on the Textual UI thread, so it can `query_one` the prompt bar and write the stash synchronously
before quitting.

### The prompt input bar (what holds the draft)

- A single `PromptInputBar` (`id="prompt-input-bar"`) is mounted at a time. The agent-launch bar uses `mode="prompt"`
  and supports a stack of 1..N panes (split by `---`) plus shared YAML frontmatter. (The `feedback` / `approve_prompt`
  modal bars are transient and are intentionally **not** stashable/restorable — restore is prompt-mode-only by design,
  boundary rule D5.)
- The app finds it via `_mounted_prompt_bar()` (`query_one("#prompt-input-bar", PromptInputBar)`), which searches the
  whole app — so it is found even while the Admin Center modal is on top.

### The prompt-stash system (what we reuse — already complete)

- **Store:** one per-user pile `~/.sase/prompt_stash.jsonl` (`prompt_stash_path()`), fronted by the Rust-backed facade
  `src/sase/core/prompt_stash_facade.py` (`append_prompt_stash`, `pop_...`, `read_...`, etc.).
- **Wire record:** `PromptStashEntryWire` with fields
  `id, created_at, text, frontmatter, project, source, pane_index, pinned`. `source` is a **free-form string** on both
  sides (`pub source: String` in `crates/sase_core/src/prompt_stash/wire.rs`); existing values are `"all"`, `"current"`,
  `"failed_launch"`.
- **Bundle semantics already exist:** `_persist_stashed_panes(panes, source=...)` (`_prompt_bar_stash.py`) joins
  multiple captured panes with `\n---\n` into **one** entry, preserves the shared frontmatter, tags the originating
  project, and mints id/timestamp. This is exactly the "stash as a bundle" behavior requested.
- **Capture is presentation-only:** the bar produces `StashedPromptPane(text, frontmatter, pane_index)` values; the app
  enriches and persists them (boundary rule D6). See the existing manual paths `stash_all_panes()` (`gs`) and
  `stash_all_and_load_xprompt_markdown()` in `_prompt_input_bar_stash_actions.py`.
- **Restore already works:** after restart the top-bar `StashedPromptsIndicator` badge shows the count (refreshed on
  startup), and the global `@` keymap restores the bundle (auto-restores immediately when it is the only entry; opens
  the picker otherwise). There is a precedent for defensive, non-message auto-stash in the "failed launch" recovery
  path.

## Design

Add a synchronous "stash the current draft as a bundle" step into the restart choke point, reusing the existing
capture + persist machinery. No new persistence format, no Rust changes.

### 1. Bar: a synchronous capture helper (presentation layer)

In `src/sase/ace/tui/widgets/_prompt_input_bar_stash_actions.py`, add a method that returns the current draft as
`list[StashedPromptPane]` **without** posting a message or mutating the stack:

- Prompt-mode only (return `[]` for `feedback` / `approve_prompt`).
- `_sync_state_from_widgets()` first, then build one `StashedPromptPane` per non-empty pane (text stripped, shared
  `frontmatter`, original `pane_index`) — mirroring `stash_all_panes()`.
- Return `[]` when there is nothing worth keeping (no non-empty pane and no frontmatter).

This comprehension is currently duplicated across `stash_all_panes`, `stash_all_and_load_xprompt_markdown`,
`request_save_as_xprompt`, and `request_update_pinned_stash`; factor the shared capture into the new helper and have
those callers reuse it (a small, behavior-preserving cleanup, not a requirement of the feature).

### 2. App: a synchronous "stash before restart" helper (glue layer)

In `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`, add a method (e.g.
`_stash_prompt_bar_before_restart()`) plus a `source` constant (e.g. `_RESTART_STASH_SOURCE = "restart"`). It must:

- Get `bar = self._mounted_prompt_bar()`; no-op if absent or not `mode == "prompt"`.
- Capture panes via the new bar helper; no-op if empty (avoid empty stash rows).
- Persist them as one bundle via the existing `self._persist_stashed_panes(panes, source=_RESTART_STASH_SOURCE)` — a
  **synchronous** Rust write so it completes before the re-exec.
- Be wrapped so any failure is swallowed/logged and **never blocks the restart** (mirror the defensive posture of the
  failed-launch recovery path).
- No badge refresh needed — we are quitting; the new process re-reads the count on startup.

### 3. Wire it into the restart choke point

In `src/sase/ace/tui/actions/axe.py`, call `self._stash_prompt_bar_before_restart()` at the top of `_restart_tui`
(before `_kill_all_running_tasks()` / `_do_quit()`), inside a guard so a stash error can never prevent the restart.

### 4. User feedback (small nicety)

The restart toast already says "…restarting ACE to load new code." When a draft was stashed, append a short hint (e.g.
"Your prompt draft was stashed — press @ to restore.") so the user knows where the draft went and how to get it back.
Keep this optional/minimal; the persistent badge after restart is the primary signal.

## Decisions

- **Hook the general restart funnel, not just the `S` path.** `_restart_tui` is the one choke point for all restart
  paths; losing a draft on a plugin-update restart or a manual "Restart TUI" is equally bad, and a single hook is
  simpler and consistent with the "treat runtimes/paths uniformly" ethos. Plain quit is deliberately excluded.
- **Stash only the `mode="prompt"` agent bar.** The `feedback`/`approve_prompt` bars are transient modal prompts; the
  stash/restore system is prompt-mode-only by design, and restoring a feedback reply as an agent prompt would be wrong.
- **One bundle entry, reusing existing semantics.** Reuse `_persist_stashed_panes` so multi-pane drafts become a single
  `\n---\n`-joined bundle with frontmatter preserved — identical to a manual `gs` capture, just with `source="restart"`.
- **New `source="restart"` value, no Rust change.** Verified `source` is a free-form `String` in the core wire; this
  stays entirely in the Python/TUI layer, respecting the Rust core boundary (capture = presentation, persistence =
  existing facade).
- **Restore is the existing flow (manual `@` + badge), not auto-restore.** This fully satisfies "the prompt is no longer
  lost" with minimal risk and matches established stash UX.

## Open question (for the reviewer)

Should the restored draft be **auto-restored** into a freshly mounted prompt bar on the next startup, instead of waiting
for the user to press `@`? This is a natural follow-up but adds meaningful complexity (distinguishing the restart bundle
from any pre-existing stash entries, deciding when/whether to mount the bar on startup, and avoiding surprise).
Recommendation: ship the auto-stash first; treat auto-restore as a separate, optional enhancement to confirm before
building.

## Testing

- **Bar capture helper:** returns expected `StashedPromptPane`s (text, frontmatter, ordered `pane_index`) for a
  multi-pane stack; `[]` when empty; `[]` for non-prompt modes.
- **App stash-before-restart, happy path:** mount a `mode="prompt"` bar with a multi-pane draft + frontmatter (pointing
  `prompt_stash_path()` at a temp file), invoke the restart path, and assert exactly one bundle entry is written with
  `source="restart"`, bodies joined by `\n---\n`, and frontmatter preserved. Follow the existing patterns in
  `tests/ace/tui/test_failed_launch_stash.py` and `tests/test_core_facade/test_prompt_stash.py`.
- **No-ops:** no entry written when no bar is mounted, when the draft is empty, or when the bar is in
  `feedback`/`approve_prompt` mode.
- **Resilience:** with `append_prompt_stash` monkeypatched to raise, `_restart_tui` still sets `exit_action` and quits
  (stash failure never blocks the restart).
- **Restore round-trip (lightweight):** the written `source="restart"` bundle is picked up by the existing badge count +
  `@` restore path (reuse existing restore tests rather than duplicating).

## Files expected to change

- `src/sase/ace/tui/widgets/_prompt_input_bar_stash_actions.py` — new synchronous capture helper (+ optional dedup of
  the shared capture comprehension).
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py` — `_stash_prompt_bar_before_restart()` and the
  `"restart"` source constant.
- `src/sase/ace/tui/actions/axe.py` — call the helper from `_restart_tui` before quitting.
- (Optional) restart toast text where the restart message is composed.
- Tests under `tests/ace/tui/` (and a widget-level test) per the Testing section.

**No Rust / `sase-core` changes required.**

## Out of scope

- Auto-restore on startup (see Open question).
- Stashing the `feedback` / `approve_prompt` modal prompts.
- Auto-stashing on a plain (non-restart) quit.

## Validation

After implementation, run `just install` then `just check` (lint + type-check + tests), including the prompt-stash tests
above.
