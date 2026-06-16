---
create_time: 2026-06-15 22:06:36
status: done
prompt: sdd/prompts/202606/prompt_stash.md
bead_id: sase-4q
tier: epic
---
# Plan: Prompt Stash — stash & restore prompt-input drafts

## 1. Product context & goal

Today a half-written prompt in the ACE prompt-input bar is ephemeral. If you cancel or unmount the bar, the only safety
net is the _cancelled_ prompt-history list (`<ctrl+k>`), which is lossy, undiscoverable for this purpose, and not a
deliberate "set this aside for later" gesture.

We want a **prompt stash** — conceptually `git stash` for prompt drafts. The user can:

1. **Stash the current prompt** (the active pane) with a keymap.
2. **Stash all visible prompts** (every pane in the prompt bar) with a keymap.
3. **Restore one or more** stashed prompts later (pop them back into the bar) with a keymap.

It must be:

- **Permanent** — stashes survive app restarts (persisted to disk).
- **Visible** — a clear indicator in the TUI chrome shows when restorable stashes exist.
- **Intuitive** — keymaps and the restore picker follow existing ACE conventions.
- **Reliable** — atomic, crash-safe writes; safe under concurrent ACE instances.
- **Beautiful** — a polished top-bar badge and a tasteful multi-select restore modal.

### Terminology (important — avoid a name collision)

The codebase **already** has a "prompt **stack**" (`PromptStackState` / `PromptStackItem` in
`src/sase/ace/tui/widgets/prompt_stack.py`) — the _multi-pane_ prompt bar where several agent prompts are drafted at
once and submitted one-by-one.

This feature is a **different, persistent thing**. We call it the **prompt stash** throughout (entries are _stashed
prompts_). "Stash all visible prompts" means "stash every _pane_ in the current bar."

## 2. Key design decisions (I'm leading these; flag any you'd change)

**D1 — Persistence lives in the Rust core (recommended).** Per the `rust_core_backend_boundary` rule, persistent domain
state a future CLI/web frontend would share belongs in `../sase-core`. We mirror the existing **notification store**
(atomic JSONL via `sase_core_rs` with lock/tempfile/rename) almost exactly — it is a proven template for "a persisted
list surfaced in the TUI." _Descope knob:_ if you'd rather not touch the sibling Rust repo now, Phase 1 can ship a
pure-Python store behind the **same facade interface** — Phases 2–4 are unaffected because they only depend on
`prompt_stash_facade`.

**D2 — One global stash, per-user.** Store at `~/.sase/prompt_stash.jsonl` (a single "git-stash-like" pile), not
per-project. Rationale: matches the user's "somewhere permanent" mental model, avoids project-resolution edge cases
(home/global prompts have no project), and is the simplest reliable v1. Each entry still records its **originating
project** as metadata so the restore picker can show a project chip and we can add per-project filtering later without a
data migration.

**D3 — A stash entry is a single prompt (one pane).** Uniform atom: "stash current" creates 1 entry; "stash all" creates
N entries (one per non-empty pane), preserving order. This keeps entries individually restorable and the model simple.
Each entry preserves the bar's YAML **frontmatter** so xprompt references round-trip losslessly (same contract as
single-pane submit's `attach_frontmatter`).

**D4 — Restore = a multi-select picker that pops.** The user asked to restore "one or more." A modal lists stashes
(newest first) with previews; `space` toggles, `enter` restores the selected set (or the highlighted one if none
toggled). Restored entries are **removed** from the stash (true pop) and loaded into the bar as panes. This cleanly
covers both "pop the latest" (enter on top item) and "cherry-pick several."

**D5 — Keymaps (defaults; all configurable).** Capture needs a focused bar, so it uses the bar's existing comma-leader
(vim normal mode, alongside `,j/,k/,J/,K/-`). Restore works anywhere, so it is also wired app-side. | Action | Default |
Where | |---|---|---| | Stash current pane | `,s` | prompt bar (comma-leader, normal mode) | | Stash all panes | `,S` |
prompt bar (comma-leader, normal mode) | | Restore / pop | `,P` | app leader-mode subkey **and** the bar's comma-leader
(same chord everywhere) | `,P` ("Pop") avoids the existing app leader `,p` = _projects_. The bar owns its own
comma-leader, so reusing `P` there is safe and keeps one consistent chord for restore.

**D6 — The bar stays presentation-only.** Following the boundary rule, the `PromptInputBar` _captures_ pane text and
posts a message (e.g. `PromptInputBar.Stashed` / a restore request); the **app** layer performs persistence through
`prompt_stash_facade` and refreshes the indicator. This matches how submit / cancel already post messages the app
handles.

## 3. Architecture overview

```
 prompt bar (capture, presentation)          app glue                core
 ───────────────────────────────────         ─────────────          ──────────────────────
 ,s / ,S  → capture pane text(s) ──post──▶  app handler ──────▶  prompt_stash_facade ──▶ sase_core_rs
 ,P       → request restore     ──post──▶  open picker modal  ◀─────  read snapshot
                                            on confirm: pop ──────▶  prompt_stash_facade ──▶ sase_core_rs
                                            load into bar / mount
                                            refresh top-bar indicator (count)
```

Disk: `~/.sase/prompt_stash.jsonl` (atomic JSONL, schema-versioned).

## 4. Phased delivery

Four phases, linear dependencies (P1 → P2 → P3 → P4), each independently testable and each **must leave `just check`
green** (a distinct agent owns each phase).

### Phase 1 — Backend: prompt-stash store + bindings + Python facade

_No TUI changes._ Deliver a tested, importable persistence API.

- **`../sase-core`** (`crates/sase_core`): new `prompt_stash` module modeled on the notifications store —
  `PromptStashEntry` (id, created_at, text, frontmatter, project, source, pane_index) + a snapshot type, a
  schema-version constant, and atomic ops: `read_prompt_stash_snapshot`, `append_prompt_stash`,
  `pop_prompt_stash(ids) -> {removed, snapshot}` (atomic remove+return), `rewrite_prompt_stash`. Reuse the existing
  lock/tempfile/rename helper. Rust unit tests.
- **`crates/sase_core_py`**: PyO3 `#[pyfunction]` wrappers (dict in/out, GIL released on IO); register them and update
  the module-docs binding list.
- **This repo**: `src/sase/core/prompt_stash_wire.py` (frozen wire dataclasses + `*_from_dict` / `*_to_json_dict` +
  schema version), `src/sase/core/ prompt_stash_facade.py` (thin `require_rust_binding` wrappers, mirrors
  `notification_store_facade.py`), and a `prompt_stash_path()` helper in `src/sase/core/paths.py`. Python unit tests
  against a temp store.
- **Note for the agent**: rebuild the Rust extension (`just install`) before running tests; read sibling Rust files via
  `sase workspace open -p sase-core <N>`.

**Exit:** `read/append/pop` round-trip via the facade; `just check` green.

### Phase 2 — Capture: stash keymaps + top-bar indicator + toasts

After this you can stash and watch the badge grow; entries land on disk.

- Add `s` / `S` to the bar comma-leader dispatch (`_handle_stack_leader_key` in `_vim_normal_pending.py`) → new bar
  methods (e.g. `stash_active_pane`, `stash_all_panes` in `_prompt_input_bar_stack_actions.py`) that sync widget→state,
  collect non-empty pane text(s) + frontmatter, and **post** a `PromptInputBar.Stashed` message. After stashing: remove
  the pane(s); unmount the bar when it becomes empty (reuse existing cancel-when-empty/unmount path) **without**
  double-recording to cancelled history.
- App handler: persist via `prompt_stash_facade.append`, show a toast (`self.notify("Stashed prompt", ...)`), refresh
  the indicator.
- New `StashedPromptsIndicator` widget (mirror `notification_indicator.py`), composed in `app.py` top bar (~line 272),
  with a TCSS style (distinct accent + glyph, e.g. `⌯`/`❄`). Hidden at count 0. `_refresh_prompt_stash_indicator()`
  reads the snapshot count; called on startup and after each capture.
- Update the bar's normal-mode subtitle / placeholder hints to advertise `,s` / `,S`.
- Tests: capture state/actions (temp store or mocked facade), indicator rendering, empty-pane no-op + toast.

**Exit:** stash current/all works, badge increments, persisted; `just check` green.

### Phase 3 — Restore: picker modal + pop semantics + load into bar

Completes the end-to-end loop.

- `StashedPromptsModal(ModalScreen[...])` multi-select picker built on `OptionListNavigationMixin` (cf.
  `agent_cleanup_custom_modal.py`): newest-first rows with age ("2m ago"), project chip, truncated first-line preview,
  `✓` selection; `space` toggle, `a` toggle-all, `enter` confirm, `esc` cancel, optional `d` to delete an entry without
  restoring. Title shows the count. (Stretch: side preview pane of the highlighted entry's full text for the "beautiful"
  bar.)
- App action `action_restore_prompt_stash` — new `AppKeymaps` field `restore_prompt_stash` + `_BINDING_META` entry +
  `default_config.yml` leader-mode subkey (`,P`); also handle `P` in the bar comma-leader. Opens the picker; on confirm:
  `pop` selected via facade, then **load into the bar** — if a prompt bar is shown, append restored entries as new panes
  (`load_stack_from_text` / `append_bottom`); if not, mount the home prompt bar first. Refresh indicator + toast.
- Guard: restore only in `prompt` mode (no-op + toast in feedback/approve-prompt).
- Footer (conditional, per `ace/AGENTS.md`): show the restore keymap **iff** the stash is non-empty. Add a help-modal
  entry. Keep help/footer docs in sync.
- Tests: modal selection/confirm/cancel, restore action (pop + load, mount-if-needed), footer-condition, mode guard.

**Exit:** full stash→restore loop; `just check` green.

### Phase 4 — Polish: visual snapshots, hardening, docs

- PNG visual snapshot tests for the indicator and the restore modal (`tests/ace/tui/visual/snapshots/png/`, per
  `build_and_run.md`).
- Hardening: long-prompt preview truncation, malformed/old-schema store tolerance, concurrent-instance indicator refresh
  (refresh on app focus/lifecycle, not just local ops), graceful behavior when `sase_core_rs` is unavailable.
- Docs: finalize `?` help-popup content and footer text; manual verification with `just run` (screenshot the badge +
  modal). Propose any short/long memory updates for approval (memory files are not edited without the user's OK).

**Exit:** polished, snapshot-covered, documented; `just check` + `just test-visual` green.

## 5. Risks & mitigations

- **Cross-repo Rust build (P1).** Mitigation: notifications is a near-exact template; the descope knob (D1) keeps the
  TUI phases unblocked if Rust is deferred.
- **Comma-leader key conflicts.** Bar comma-leader is independent of app leader; `,P` chosen to dodge `,p`=projects.
  Verified `s`/`S`/`P` are free in the bar leader.
- **Don't double-save to cancelled history** when stashing then unmounting — explicitly clear/remove pane text before
  the safety-net unmount runs.
- **Multi-instance count drift** on the badge — acceptable for v1; P4 adds a lifecycle refresh. Writes are atomic
  regardless.

## 6. Out of scope (future)

- A `sase stash` CLI surface (the Rust core makes it easy later; would also pull in the generated-skills/CLI-contract
  pipeline — deliberately excluded now).
- Per-project stash filtering UI (data model already carries the `project` field).
- Editing a stashed prompt in place from the picker.
