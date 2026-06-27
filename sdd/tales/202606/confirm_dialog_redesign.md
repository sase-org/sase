---
create_time: 2026-06-27 09:01:27
status: done
prompt: sdd/prompts/202606/confirm_dialog_redesign.md
---
# Plan: Unified, Beautiful Confirmation Dialogs for the `sase ace` TUI

## Problem & Motivation

Several yes/no confirmation prompts in the `sase ace` TUI render as a raw, full-width band pinned to the **top-left** of
the screen instead of a centered pop-up panel. The "Commit & Push" prompt is the canonical example: bare text and two
buttons sprawl across the top of the TUI with no border, no backdrop framing, and no visual containment.

### Root cause

All confirmation prompts are already Textual `ModalScreen` subclasses, but their styling is applied **by class name** in
`src/sase/ace/tui/styles.tcss`, and three of the simple ones were never added to the relevant rules:

- The centering rule (`align: center middle`) at `styles.tcss:148` lists `ConfirmKillModal`, `ConfirmDismissAllModal`,
  `ConfirmKillAllModal` — but **not** `ConfirmActionModal`, `ConfirmDeleteModal`, or `ConfirmRerunModal`.
- The container-sizing rule (width / border / background / padding) at `styles.tcss:152` has the same omission.

With no `align` and no width-capped bordered container, those modals' root `Container()` expands to fill the screen from
the top-left — exactly the artifact in the screenshot. The kill/dismiss modals look fine today only because they happen
to be in the list.

### Why this is worth doing well (not just a one-line CSS patch)

We _could_ fix the bug by appending three class names to two CSS selectors. But the confirmation prompts are a
scattered, inconsistent family: some have rich styling (`QuitConfirmModal`, `ConfirmRevertAgentModal`), some have
partial styling (`ConfirmKill*`), and three have none. Messages are terse and inconsistent ("Confirm Delete Project",
"Confirm Re-run"). The user has explicitly asked us to **lead the design** and make these "look beautiful" — so the goal
is a single, cohesive, polished confirmation-dialog _system_ that every yes/no prompt flows through, not a patch that
leaves the inconsistency in place.

## Design Vision

A unified confirmation dialog with one recognizable visual identity across the whole TUI.

### Visual anatomy

A compact, centered panel floating over the dimmed app (the `ModalScreen` backdrop already dims the content behind it):

```
        ╭─ ↑  Commit & push ─────────────────────────╮
        │                                             │
        │   Commit and push your changes to           │
        │   src/sase/default_config.yml               │
        │                                             │
        │         ╭ Yes (y) ╮   ╭ No (n) ╮            │
        │                                             │
        ╰──────────────────── y confirm · esc cancel ─╯
```

Key design decisions:

1. **Titled bordered panel via Textual's `border_title` / `border_subtitle`.** Instead of a separate title `Label`
   stacked above the body, the title (with a leading glyph) is rendered _into the top border_, and the keyboard hints
   (`y confirm · esc cancel`) into the _bottom border_. This is the idiomatic Textual way to build a titled dialog: it
   is more compact, reads as a single framed object, and looks markedly more polished than stacked labels. Container
   width ~58–64 cells, `height: auto`, `max-height: 80%`, centered.

2. **A rounded border** (`round`) for a softer, modern silhouette versus the current blocky `thick`. (The codebase
   already uses modern border types such as `hkey`, so this is safe.)

3. **Severity-aware accent + glyph.** A small `ConfirmKind` drives the panel's accent color, leading glyph, and the
   affirmative button variant:
   - `NEUTRAL` — `$primary` accent, default glyph `?`; affirmative button `variant="primary"`. For constructive actions
     (commit & push, re-run) callers pass a context glyph (`↑`, `↻`).
   - `DANGER` — `$error` (red) accent, glyph `⚠`; affirmative button `variant="error"`. Used for destructive actions
     (delete, kill, dismiss-all, revert). This keeps the palette coherent (two accent colors) while letting individual
     prompts feel tailored, and lets the panel _signal the stakes_ before the user reads a word.

4. **Emphasized subject.** The thing being acted upon (a file path, project name, agent description) is rendered on its
   own line, bold and accent-colored, so the eye lands on _what is affected_. The dialog API takes an optional `subject`
   argument and renders it safely (escaped), separately from the lead-in sentence — avoiding markup-injection from
   dynamic paths/names.

5. **Safer default focus.** Destructive (`DANGER`) dialogs focus the **cancel** button by default (mirroring today's
   `QuitConfirmModal`), so an accidental `enter` is non-destructive. Neutral dialogs may default focus to confirm. This
   is configurable per call.

6. **Better copy.** Titles and messages are rewritten to be clear and human, and buttons get action-specific verbs where
   it helps (e.g. "Commit & push (y)" / "Cancel (n)"; "Delete (y)" / "Keep (n)"). Every dialog keeps the `(y)` / `(n)`
   key hints in the labels and the muted hint line in the bottom border.

### Interaction (unchanged, made consistent)

`y` / `enter` → confirm · `n` / `esc` / `q` → cancel. These already exist on every modal; the redesign standardizes them
in one place so behavior can't drift between dialogs.

## Technical Approach

### 1. A shared foundation: `ConfirmDialog`

Add `src/sase/ace/tui/modals/confirm_dialog.py`:

- `ConfirmKind` enum (`NEUTRAL`, `DANGER`) plus the default glyphs per kind.
- `ConfirmDialog(ModalScreen[bool])` — the canonical binary yes/no dialog implementing the visual anatomy above.
  Constructor (roughly):

  ```python
  ConfirmDialog(
      title: str,
      message: str,
      *,
      subject: str | None = None,
      kind: ConfirmKind = ConfirmKind.NEUTRAL,
      icon: str | None = None,            # overrides the kind's default glyph
      confirm_label: str = "Yes",         # "(y)" appended automatically
      cancel_label: str = "No",           # "(n)" appended automatically
      default: Literal["confirm", "cancel"] = "cancel",
  )
  ```

  It owns: `compose()` (container with `border_title`/`border_subtitle`, message/subject `Static`s, centered two-button
  `Horizontal`), the `y/n/esc/q` bindings, `on_mount` focus, and `dismiss(bool)`. It also exposes small mutation helpers
  (`_set_kind`, `_set_title`, `_set_message`) so escalating dialogs (see KillAll) can re-skin themselves at runtime.

### 2. One shared CSS block

Replace the scattered per-class confirm rules with a single `.confirm-dialog` style group in `styles.tcss`:

- One `align: center middle` rule and one container rule (width / `max-height` / `round` border / `$surface` background
  / padding) targeting the shared class.
- Severity modifiers `.confirm-dialog--danger` / `.confirm-dialog--neutral` set only the border (and the escalation case
  sets `$error`). This replaces the bespoke `.confirmed-once` red-border hack.
- Shared rules for the message, emphasized subject, centered button row, and the hint subtitle.

Remove the now-dead confirm entries from `styles.tcss:148`, `:152`, `:161`, and the `ConfirmKill*/ConfirmDismissAll*`
block at `:1050–1066` once those modals adopt the shared class.

### 3. Migrate every simple yes/no confirm modal onto the foundation

All become thin subclasses (or direct uses) of `ConfirmDialog`, preserving their **public class names and call
signatures** so the ~20 existing call sites keep working unchanged:

| Modal                    | Change                                                                                                                                                                                      | Kind / glyph                        |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `ConfirmActionModal`     | Becomes a thin subclass of `ConfirmDialog`; keeps the `(title, message)` positional signature; gains optional `kind`/`icon`/`subject`.                                                      | `NEUTRAL` (callers opt into glyphs) |
| `ConfirmDeleteModal`     | Subclass; rewritten copy ("Delete project '<name>'? This can't be undone.").                                                                                                                | `DANGER` / `⚠`                      |
| `ConfirmKillModal`       | Subclass.                                                                                                                                                                                   | `DANGER` / `⚠`                      |
| `ConfirmDismissAllModal` | Subclass.                                                                                                                                                                                   | `DANGER` / `⚠`                      |
| `ConfirmKillAllModal`    | Subclass; keeps double-confirm, but the escalation flips `kind` → `DANGER` + "FINAL CONFIRMATION" via the base mutation helpers (drops the `.confirmed-once` CSS).                          | escalates to `DANGER`               |
| `ConfirmRerunModal`      | Three-way outcome (True/False/None) is bespoke, so it keeps its own button set + key handling, but **adopts the shared `.confirm-dialog` container/border styling** so it matches visually. | `NEUTRAL` / `↻`                     |

Call sites that benefit from richer context pass the new optional args — e.g. the Commit & Push prompts in
`_prompt_bar_save_xprompt.py` and `xprompt_browser_actions.py` pass `subject=rel_path`, `icon="↑"`, and a cleaner
message.

### 4. Cohesion pass for the rich confirmation modals

`QuitConfirmModal`, `ConfirmRevertAgentModal`, and `PluginActionConfirmModal` already render as proper centered panels
with bespoke bodies (task cards, repo cards, the exact `uv` command preview). They are **not broken** and keep their
bodies. The pass aligns their _frame_ with the new system: adopt the `round` border, the
`border_title`/`border_subtitle` title+hint treatment, and the shared accent tokens, so the entire confirmation family
reads as one design language. This is lower-risk polish and can land as the final step (or be split out if review
prefers to keep the bug-fix + simple-modal redesign focused).

### 5. Visual snapshot coverage

PNG snapshot tests are the project's contract for TUI appearance. Using
`tests/ace/tui/visual/test_ace_png_snapshots_quit_confirm.py` as the template, add a new
`test_ace_png_snapshots_confirm_dialog.py` that captures:

- A `NEUTRAL` dialog (the Commit & Push case, with emphasized subject + `↑` glyph).
- A `DANGER` dialog (delete, with the red accent + `⚠`).
- The `ConfirmKillAllModal` escalated "FINAL CONFIRMATION" state.

Goldens are generated with `--sase-update-visual-snapshots` and committed under `tests/ace/tui/visual/snapshots/png/`.
Existing snapshots that legitimately change appearance (if the cohesion pass touches Quit/Revert) are regenerated and
re-reviewed in the same step.

## Scope, Boundaries & Risks

- **Rust core boundary:** Per `memory/rust_core_backend_boundary.md`, this is presentation-only Textual styling, layout,
  and widget composition. **No `sase-core` changes** — nothing here is shared backend/domain behavior that another
  frontend must match.
- **Default keymap config:** The confirm modals use hardcoded `BINDINGS` (`y`/`n`/`esc`/`q`), not config-driven keymaps,
  so `src/sase/default_config.yml` should not need changes. We will confirm during implementation that no configurable
  keymap feeds these dialogs (per the "Default Keymap Config" gotcha).
- **Backward compatibility:** Keeping the existing class names and positional signatures means the ~20 call sites across
  `actions/` and `modals/` need **no behavioral changes** — only the handful we deliberately enrich with
  `subject`/`icon`/better copy.
- **Help / docs:** No `sase` CLI options change, so the `?` help popup and AGENTS.md help rules are unaffected.
- **Verification:** Because this touches files in the `sase` repo, run `just install` then `just check` before
  completion (lint + mypy + tests, including the visual suite). Optionally launch the TUI to eyeball the Commit & Push
  and a delete prompt.

## Deliverables

1. `confirm_dialog.py` — `ConfirmKind` + `ConfirmDialog` foundation.
2. `styles.tcss` — one shared `.confirm-dialog` style group; dead per-class confirm rules removed.
3. Migrated `ConfirmActionModal`, `ConfirmDeleteModal`, `ConfirmKillModal`, `ConfirmDismissAllModal`,
   `ConfirmKillAllModal`, `ConfirmRerunModal`.
4. Enriched copy + `subject`/`icon` at the Commit & Push and other high-value call sites.
5. (Cohesion pass) `QuitConfirmModal` / `ConfirmRevertAgentModal` / `PluginActionConfirmModal` adopt the shared frame.
6. New + regenerated PNG visual snapshots and a `test_ace_png_snapshots_confirm_dialog.py`.
7. Green `just check`.

## Definition of Done

- Every yes/no prompt — starting with Commit & Push — renders as a centered, rounded, titled pop-up panel; none stretch
  across the top-left of the TUI.
- Destructive prompts are visually distinct (red accent + ⚠) and default-focus the safe option; constructive prompts use
  the primary accent and a fitting glyph.
- Messages and button labels are clear and consistent.
- `just check` passes, including new/updated visual snapshots.
