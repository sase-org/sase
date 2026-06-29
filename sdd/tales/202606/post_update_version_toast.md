---
create_time: 2026-06-29 10:53:50
status: done
prompt: sdd/prompts/202606/post_update_version_toast.md
---
# Plan: "You just updated" version toast after a SASE self-update + TUI restart

## 1. Product context & goal

When a user runs a full SASE self-update from the **SASE Admin Center → Updates** tab (the `S` keymap, "Sase update"),
and the update actually changes code, the TUI **restarts itself into the freshly-installed version**. Today that restart
is silent about the one thing the user most wants confirmed: _did it work, and what version am I on now?_ The
pre-restart toast ("… — restarting ACE to load new code.") is shown in the **old** process and vanishes with it; the
**new** process comes up with no acknowledgement of the update at all.

**Goal:** In the newly-launched TUI instance, show a single, beautiful toast that confirms the update and reports the
version transition — e.g. `sase 0.4.0 → 0.5.0`, plus a short summary of any plugins that moved. The toast must feel
native, fire exactly once, and never get in the way.

### Success criteria

- After an `S`-triggered update that changes code and restarts the TUI, the new instance shows a toast naming the old →
  new version(s).
- The toast renders for **both** update paths: managed (`uv tool upgrade`, semver versions) and dev/editable checkouts
  (git-based versions).
- It shows **exactly once** per update, never on an ordinary restart (`R`) or normal launch, and never repeats on the
  next launch.
- It is visually consistent with the existing "↑ Updates available" startup toast.
- It is best-effort everywhere: a missing/corrupt/stale handoff never blocks first paint, never throws, and never shows
  a wrong/old version.

## 2. Why this is the right shape (key constraints discovered)

- **The restart is a real process boundary.** `_restart_tui` (`src/sase/ace/tui/actions/axe.py`) sets an `AceExitAction`
  and quits; `src/sase/main/ace_handler.py` then `os.execv`s a brand new process. Nothing in memory survives — so the
  old process must **hand off state via disk**, and the new process reads it on startup. This is exactly how the
  prompt-draft stash and the persisted Admin Center tab already work.
- **The version transition data already exists at the restart decision point.** The update task's completion payload is
  an `UpdateSummary` (managed; `src/sase/uv_tool/render.py`) or a `DevUpdateResult` (dev;
  `src/sase/dev_update/models.py`). Both expose per-package `old_version` / `new_version` and enough role/status info to
  identify the primary `sase` package vs. plugins. We do **not** need to re-derive versions — we capture them from the
  payload.
- **There is a proven "startup toast" pattern to mirror.** `UpdateToastMixin`
  (`src/sase/ace/tui/actions/update_toast.py`) already renders a Rich-markup startup toast with the Updates-tab accent
  color, a glyph, capped component lines with `old → new` arrows, and an overflow line. The new toast should reuse this
  grammar so the two feel like siblings.
- **There is a proven tiny-disk-state pattern to mirror.** `src/sase/ace/admin_center_tab.py` persists a tiny JSON blob
  under `sase_home()` with a module-level test override and fully swallowed I/O errors. The handoff file should follow
  this template precisely.

### Rust core boundary

This is **TUI-restart presentation state**, not shared domain behavior. The toast exists _only_ because the long-lived
TUI restarts itself; a CLI `sase update` prints its result synchronously and never needs it, and no web/editor frontend
needs to reproduce a "what you updated to" toast. The version-transition data types (`UpdateSummary`, `DevUpdateResult`)
already live in this Python repo, not in `sase-core`. Therefore **no Rust changes** — this mirrors the explicit
rationale in `admin_center_tab.py`'s own docstring. The new persistence module will carry a similar docstring justifying
its Python/ACE placement.

## 3. Design overview

A **single-shot "pending update toast" handoff file**:

1. **Capture (old process, right before restart).** When the update completion handler decides to restart because real
   changes landed, normalize the completion payload into a small serializable **receipt** (primary `sase` transition, a
   capped list of plugin transitions, a dependency count, a `managed`/`dev` kind, a timestamp, and a format version) and
   write it atomically to a JSON file under `sase_home()`. Then restart exactly as today.
2. **Consume (new process, after first paint).** During post-mount startup loads, **read-and-delete** the receipt. If
   present, fresh, and enabled, render a beautiful toast naming the version transition. The file is deleted on read
   (consume-once) so the toast can never repeat.

### Why a dedicated handoff file rather than the notification inbox

The persistent notification store (`~/.sase/notifications/…`, Rust-backed, surfaced by the `sase_notify` skill) is for
**durable** user notifications. A "you just restarted into a new version" message is **transient UI handoff**, not inbox
history — putting it there would pollute the inbox and cross the Rust boundary. The existing "updates available" toast
also does **not** use the inbox (it reads the update-status cache). A small, self-cleaning file is the consistent,
lower-risk choice.

### Receipt schema (illustrative)

```json
{
  "format": 1,
  "created_at": 1719700000.0,
  "kind": "managed",
  "primary": { "name": "sase", "old": "0.4.0", "new": "0.5.0" },
  "plugins": [{ "name": "sase-github", "old": "0.2.0", "new": "0.3.0" }],
  "plugin_overflow": 2,
  "dependency_count": 3
}
```

- `primary` is `null` when only plugins/dependencies changed.
- `plugins` is capped to a small N (e.g. 3, matching the existing toast's `_MAX_COMPONENT_LINES`); `plugin_overflow`
  records how many more were updated.
- For the **dev** path, `old`/`new` are whatever git-based version strings the payload carries; the renderer prints them
  verbatim.

## 4. Reliability design (exactly-once, never-wrong)

- **Atomic write:** write to a temp file in the same dir, then `os.replace` — a kill mid-write can never leave a torn
  file masquerading as valid.
- **Consume-once:** on startup, read the bytes, **delete the file first**, then parse/validate/show. Even if rendering
  throws, the file is already gone, so it can never re-fire.
- **Freshness guard:** ignore (but still delete) a receipt whose `created_at` is older than a generous bound (e.g. 30
  minutes). A genuine update→restart completes in seconds; this guard defends the one real failure mode — the old
  process wrote the receipt but the re-exec never happened, so the file would otherwise surface a stale toast on some
  unrelated launch days later.
- **Format guard:** ignore unknown `format` values (forward/backward compatibility).
- **Total best-effort I/O:** every read/write/parse is wrapped and swallowed with a debug log, matching
  `admin_center_tab.py` and `update_toast.py`. No path blocks first paint or raises.
- **No double-toast:** consuming + showing the post-update toast also marks the session's update-toast guard as
  already-shown, so the redundant "↑ Updates available" toast is suppressed on the same startup (a freshly-updated
  instance should celebrate the update, not nag about updates).
- **Uniform across runtimes:** no runtime-specific branching (honors the "Uniform Agent Runtimes" convention); the
  capture/consume path is identical regardless of agent runtime.

## 5. Beauty design (visual spec)

Mirror the existing update toast's grammar so it reads as a sibling, but signal **success** clearly and distinctly from
"updates available":

- **Severity:** `information` (Textual has no `success` severity); success is conveyed with a green `✓` glyph and the
  Updates accent (`center_tab_accent("updates")`, fallback `#AF87FF`).
- **Title (adaptive):**
  - primary updated → `✓ Updated to sase {new}` (immediately answers "what am I on now?")
  - only plugins/deps → `✓ SASE updated`
- **Body (Rich markup):**
  - Primary line (if changed): `sase  [dim]{old}[/] [dim]→[/] [bold green]{new}[/]`
  - Up to N plugin lines: `• {name}  [dim]{old} →[/] [green]{new}[/]` (names/versions `escape()`d, exactly like the
    existing `_component_line`)
  - Overflow: `…and {M} more`
  - Optional dim tail: `+{k} dependencies` and/or `[dim]Reloaded into the new version.[/]`
- **Timeout:** ~10s (comparable to the existing 12s available-toast; long enough to read, not sticky). Dismissable with
  the usual `ctrl+l`.

A PNG visual snapshot will lock this rendering (the repo already snapshots the available-toast).

## 6. Implementation outline (files & responsibilities)

**New — pure persistence + normalization (testable without Textual):**

- `src/sase/ace/update_receipt.py`
  - `UpdateToastReceipt` dataclass + the schema above.
  - `build_update_receipt(payload, *, created_at) -> UpdateToastReceipt | None` — `isinstance`-dispatch on
    `UpdateSummary` vs `DevUpdateResult`; extract only real updates (managed: `outcome.is_update`, `role` for
    primary/plugin/dependency; dev: `status == "updated"`, primary via `record.name == "sase"`). Returns `None` when
    nothing meaningful changed (caller then writes nothing).
  - `write_pending_update_toast(receipt)` — atomic best-effort write under `sase_home()`.
  - `read_and_clear_pending_update_toast() -> UpdateToastReceipt | None` — read, delete, validate, apply freshness +
    format guards.
  - Module-level `_PENDING_UPDATE_TOAST_FILE: Path | None` test override (mirrors `admin_center_tab.py`).
  - Docstring justifying Python/ACE placement (TUI-restart presentation handoff; no Rust).

**New — the toast mixin (Textual side):**

- `src/sase/ace/tui/actions/post_update_toast.py`
  - `PostUpdateToastMixin._maybe_show_post_update_toast()` — read-and-clear the receipt; if disabled by config, return
    (file already cleared); if absent/stale, return; else build markup, call `self.notify(...)`, and set the session's
    update-toast-shown guard to suppress the available toast.
  - Message/title builders reusing the accent + `escape()` + overflow grammar from `update_toast.py`.

**Wiring:**

- `src/sase/ace/tui/actions/__init__.py` — export `PostUpdateToastMixin`.
- `src/sase/ace/tui/app.py` — add `PostUpdateToastMixin` to `AceApp`'s bases.
- `src/sase/ace/tui/actions/_startup_loads.py` — in `_start_post_mount_background_loads`, call
  `self._maybe_show_post_update_toast()` **before** `self._schedule_startup_update_toast_check()` (deterministic
  suppression; the read is a sub-millisecond local file, run post-first-paint, so inline is acceptable and avoids
  cross-worker ordering races), each wrapped in best-effort try/except.
- `src/sase/ace/tui/modals/plugins_browser_sase_update.py` — in `_handle_code_update_completion`, just before
  `self._restart_after_update(...)`, build the receipt from `completion.payload` and persist it. This one site covers
  **both** managed and dev completions (they share this handler).

**Config:**

- `src/sase/default_config.yml` — add `ace.updates.post_update_toast: true` alongside the existing `startup_toast` /
  `indicator` / `check_ttl_minutes`.
- Extend the existing `_UpdateToastConfig` / `_load_update_toast_config` in `update_toast.py` with a
  `post_update_toast: bool = True` field (same `ace.updates` block, reuse `_coerce_bool`) so both toasts share one
  config object rather than duplicating loaders.

## 7. Testing strategy

- **Unit (pure module) — `tests/ace/test_update_receipt.py`** (mirrors `test_admin_center_tab.py`): round-trip
  write→read; consume-once (second read is `None`); stale receipt ignored + deleted; corrupt JSON / non-object / unknown
  `format` ignored; missing file → `None`; normalization from a managed `UpdateSummary` (sase primary upgrade +
  plugins + deps) and from a dev `DevUpdateResult`; `build_update_receipt` returns `None` when nothing meaningful
  changed.
- **TUI behavior — `tests/ace/tui/test_post_update_toast.py`** (mirrors `test_update_toast.py`): with a receipt present,
  `notify` is called with the expected title/markup and the available-toast is suppressed; with no receipt, nothing is
  shown; with config disabled, nothing is shown but the file is consumed; the receipt is gone after startup.
- **Visual — `tests/ace/tui/visual/test_ace_png_snapshots_post_update_toast.py`** + a new golden PNG under
  `tests/ace/tui/visual/snapshots/png/` (mirrors the existing update-toast snapshot) to lock the beautiful rendering.
- Run `just check` (after `just install`). Note the known-noise items from prior runs (the `default_effort: xhigh`
  `llm_provider` failures and the sandbox SIGTERM on the full suite) are pre-existing and unrelated; rely on targeted
  pytest subsets for the new tests plus the static gates.

## 8. Documentation & conventions

- Update the `ace.updates` config documentation wherever the existing `startup_toast`/`indicator` keys are documented,
  to include `post_update_toast`.
- Per `src/sase/ace/AGENTS.md`, verify whether the `?` help modal references the Updates/startup-toast behavior; this
  feature adds no keybinding, but if the help text enumerates the updates toasts, add a one-line mention. (No footer
  keybinding changes — the toast is automatic, not a conditional keymap.)

## 9. Out of scope / deferred

- Showing the toast when `sase update` is run from the **CLI** (no TUI restart involved).
- A persistent, browsable "update history" (this is a one-shot confirmation, not inbox history).
- Coordinating with a TUI that happens to be open while a _separate_ CLI update runs.

## 10. Risks & mitigations

- **Stale toast on an aborted restart** → freshness window + consume-on-read.
- **Dev-path version strings differ from semver** → renderer prints whatever strings the payload carries; `kind` is
  captured if wording needs to differ; no parsing assumptions.
- **Two toasts at once (updated + available)** → post-update consume marks the available-toast guard.
- **First-paint regressions** → all handoff I/O is tiny, local, post-paint, and best-effort.
