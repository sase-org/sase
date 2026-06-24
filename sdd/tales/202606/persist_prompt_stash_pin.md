---
create_time: 2026-06-24 14:05:11
status: done
prompt: sdd/prompts/202606/persist_prompt_stash_pin.md
---
# Plan: Persistent "pin" for prompt-stash entries (`<space>` toggles a pin that survives restarts)

## Goal

Turn the prompt-stash panel's `<space>` key from a transient **restore + keep** mark (the `+` glyph) into a **persistent
pin toggle**:

- `<space>` on a single-prompt row toggles a **pin** on that stash entry. Pinning shows a pin icon on the row instead of
  the old `+`.
- The pin is **persisted to disk immediately** (the instant `<space>` is pressed) and **survives restarts** of
  `sase ace` and of the machine, because it lives on the stash entry in the shared per-user store
  (`~/.sase/prompt_stash.jsonl`), read back into the panel every time it opens.
- A stash entry that carries the pin icon is considered **"pinned."**

This is the first, deliberately-scoped step. Per the approved Q&A:

- **Q1 — Pure pin toggle (no restore).** `<space>` only toggles the persistent pin. It does **not** restore the prompt
  into the bar. Restoring stays on `<tab>` (restore + pop, `✓`) and `<enter>` (restore the highlighted row). Pin becomes
  an organizational flag, cleanly separated from restore.
- **Q2 — Persist immediately on `<space>`.** The pin is written to disk the moment `<space>` is pressed, even if the
  user then presses `<esc>`. (Implemented without blocking the event loop — see "Persistence flow" — so it honors the
  timing the user chose while respecting the TUI performance rules.)
- **Q3 — Icon + persistence only.** For this step, "pinned" only means: show the pin icon and persist the flag across
  restarts. No protective or sorting behavior yet (pinned rows are **not** protected from pop/delete, **not** sorted to
  the top, **not** excluded from cleanup). All of that is explicitly deferred to a later change.

## Background / Context

The prompt stash is a single per-user pile of stashed prompt drafts persisted as JSONL at `~/.sase/prompt_stash.jsonl`.
The data model and all read/append/pop/rewrite persistence live in the **Rust core** (`sase-core`, crate `sase_core`),
are exposed to Python through the `sase_core_rs` PyO3 extension, and are fronted in this repo by a thin Python facade.
The TUI panel is a presentation-only Textual `ModalScreen`.

Relevant pieces (current state):

- **Rust core (`sase-core`, crate `sase_core`):**
  - `crates/sase_core/src/prompt_stash/wire.rs` — `PromptStashEntryWire` struct (fields: `id`, `created_at`, `text`,
    `frontmatter`, `project`, `source`, `pane_index`), the snapshot/pop-outcome/stats records, and
    `PROMPT_STASH_WIRE_SCHEMA_VERSION = 1`.
  - `crates/sase_core/src/prompt_stash/store.rs` — `read_prompt_stash_snapshot`, `append_prompt_stash`,
    `pop_prompt_stash`, `rewrite_prompt_stash` (all under a file lock; rewrite uses atomic temp-file rename and
    merge-by-id semantics), plus the shared helpers `read_rows_unlocked` / `write_entries_atomic`.
  - `crates/sase_core/src/prompt_stash/mod.rs` — re-exports the store fns and wire types.
  - `crates/sase_core_py/src/lib.rs` — PyO3 bindings `py_read_prompt_stash_snapshot`, `py_append_prompt_stash`,
    `py_pop_prompt_stash`, `py_rewrite_prompt_stash`, the `prompt_stash_entry_from_pydict` /
    `prompt_stash_entries_from_py_list` helpers, and the `m.add_function(...)` registrations.
  - `crates/sase_core/tests/prompt_stash_store_parity.rs` — store unit/parity tests.

- **Python (this repo):**
  - `src/sase/core/prompt_stash_wire.py` — `PromptStashEntryWire` dataclass + dict (de)serialization
    (`_prompt_stash_entry_from_dict`, `prompt_stash_wire_to_json_dict`) + `PROMPT_STASH_WIRE_SCHEMA_VERSION = 1`.
  - `src/sase/core/prompt_stash_facade.py` — `read_prompt_stash_snapshot`, `append_prompt_stash`, `pop_prompt_stash`
    (each calls `require_rust_binding(...)`).
  - `src/sase/core/rust.py` — `require_rust_binding` raises `AttributeError` (with an install hint) when the installed
    `sase_core_rs` lacks a binding (a "stale wheel").
  - `src/sase/ace/tui/modals/stashed_prompts_modal.py` — `StashedPromptsModal` (presentation-only). `<space>` →
    `action_toggle_keep` (`+`, `_keep` set), `<tab>` → `action_toggle_pop` (`✓`, `_pop` set, `priority=True`), `d` →
    delete (`✗`), `a` → toggle-all (for pop), `enter` → confirm. Confirm dismisses with a
    `StashRestoreResult(pop_ids, keep_ids, delete_ids)`. `_stash_row_label(...)` renders the row; `_hint_text()` is the
    in-panel hint line.
  - `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py` — `PromptBarStashMixin`, the app glue that owns all
    stash persistence and badge refresh. It opens the panel (`_open_prompt_stash_panel`, reads the snapshot off-thread),
    applies the picker result (`_apply_stash_restore`), and persists captures (`_persist_stashed_panes`). All disk work
    runs off the event loop via `asyncio.to_thread`.
  - `src/sase/ace/tui/widgets/stashed_prompts_indicator.py` — the top-bar `❄ N` badge (count only; pin does **not**
    affect the count).

- **Tests:**
  - `tests/ace/tui/modals/test_stashed_prompts_modal.py` — pure row-helper tests + pilot interaction tests.
  - `tests/ace/tui/actions/test_prompt_stash_restore.py` — app-glue tests (drives the mixin handlers; uses
    `_skip_without_prompt_stash_bindings()` to skip when the Rust binding is absent).
  - `tests/ace/tui/visual/test_ace_png_snapshots_prompt_stash.py` + goldens under `tests/ace/tui/visual/snapshots/png/`
    — PNG snapshots for the badge and the restore modal.

### Key facts established during exploration

1. **A persistent pin is core/domain data, not presentation state.** It lives on the stash entry in the shared per-user
   store, so a future web UI / CLI / editor would need it to match the TUI. Per `memory/rust_core_backend_boundary.md`,
   the field and the persistence operation belong in `sase-core`; this repo calls through the binding/facade.
   (Presentation — the key binding, the icon, the row layout — stays here.)

2. **The pin field is an additive, backward-compatible change. No schema-version bump.** The Rust `PromptStashEntryWire`
   already uses `#[serde(default)]` on optional fields. Adding `pinned: bool` with `#[serde(default)]` means: old
   on-disk rows (missing the field) deserialize to `pinned = false`; new rows serialize the field; readers ignore
   unknown fields by default. `PROMPT_STASH_WIRE_SCHEMA_VERSION` stays `1` on both sides.
   - _Forward-compat caveat (note only):_ an **older** `sase_core_rs` (without the field) that pops/rewrites the store
     would not re-serialize `pinned` and could drop pins for rows it rewrites. Normal usage installs the new wheel, so
     this only matters for a mixed old/new concurrent setup. Acceptable; documented, not guarded.

3. **Persistence requires a new `sase_core_rs` release + a dependency-pin bump.** The field lives in the Rust struct, so
   even reusing `rewrite_prompt_stash` would need the new struct. `pyproject.toml` pins `sase-core-rs>=0.1.1,<0.3.0`;
   the lower bound must be raised to the release that ships the pin support. For local development the editable build
   (`just rust-install`, against the sibling `sase-core`) picks up the new binding without a release.

4. **Python must degrade gracefully when the binding is absent** (older/stale wheel), mirroring the existing
   `_skip_without_prompt_stash_bindings()` pattern: the new persistence call is wrapped in try/except in the app glue
   (toast on failure), and new tests that exercise real persistence skip when the binding is missing. The modal's icon
   rendering does **not** depend on the binding (it reads `entry.pinned` from the in-memory wire), so the visual/modal
   tests run regardless.

5. **Visual-snapshot determinism comes from font-pinning, not glyph coverage.** The PNG suite pins fontconfig to _only_
   the bundled Fira Code (Regular + Bold). A glyph missing from Fira Code renders as the font's deterministic `.notdef`
   box — identically on every host. In fact the current goldens already contain `.notdef` boxes: `✗` (U+2717, the delete
   marker) and `❄` (U+2744, the badge glyph) are **both absent** from the bundled Fira Code yet ship in the goldens
   today. So a pin emoji renders deterministically too; the glyph choice is purely a real-terminal UX decision.

6. **In-panel keys are documented only by the modal's own hint line, not the `?` help popup or the footer.** The `?`
   help (`help_modal/agents_bindings.py`) and the footer (`keybinding_footer.py`) document only the _open_ action (`@` /
   `restore_prompt_stash`). So the AGENTS.md "keep the `?` help in sync" and "footer convention" rules are satisfied by
   updating the modal hint line; no help-modal, footer, or `default_config.yml` changes are needed. (The word "pinned"
   already appears in help for an unrelated **agents** filter — `mark_inactive_pinned` — which is a different feature;
   no collision.)

7. **`<space>` was the only producer of "restore + keep" marks.** Repurposing `<space>` to pin removes the only way to
   create a keep mark from the panel. See "Scope decision: restore + keep" for exactly how far the keep removal goes.

## Design

### Data model (Rust core → Python wire)

Add a boolean `pinned` to the stash entry, defaulting to `false`, persisted in the JSONL row.

### Persistence operation (Rust core)

Add a dedicated, explicit core operation rather than reusing `rewrite_prompt_stash`:

```
set_prompt_stash_pinned(path, ids, pinned: bool) -> PromptStashSnapshotWire
```

It runs under the existing exclusive file lock, reads current rows, sets `pinned = <value>` on rows whose `id` is in
`ids` (ignoring unknown ids), writes atomically (reusing `write_entries_atomic`), and returns a fresh snapshot —
mirroring `pop_prompt_stash`'s shape. A dedicated op is chosen over reusing `rewrite_prompt_stash` because it is
**race-safe** (it only mutates the `pinned` field of the on-disk rows; it never clobbers other fields from a possibly
stale in-memory copy) and it makes "pin" a first-class core operation that any future frontend can call identically.
Taking `ids` (a list) rather than a single id keeps parity with `pop_prompt_stash` and leaves room for a future "pin
all" without another op.

### Persistence flow (immediate, but off the event loop)

The user chose "persist immediately on `<space>`" (Q2). Implement that timing **without** doing synchronous disk I/O in
the modal's key handler (which TUI perf rule #1 forbids and which would block the paint path). The modal stays the
intent layer; the app mixin — which already owns every other off-thread stash write — does the persistence:

1. On `<space>`, the modal toggles the entry in its in-memory `_pinned` set and **repaints that row immediately** (the
   pin icon appears/disappears instantly — optimistic UI).
2. The modal posts a Textual message — `StashedPromptsModal.PinToggled(entry, pinned)` — carrying the entry and the
   **absolute desired** pin value.
3. `PromptBarStashMixin` handles it (`on_stashed_prompts_modal_pin_toggled`) and persists **off-thread** via
   `asyncio.to_thread(set_prompt_stash_pinned, prompt_stash_path(), [entry.id], pinned)`. The write is serialized
   through a single `asyncio.Lock` so rapid toggles (space, space, …) apply in press order and last-write-wins matches
   the row's final on-screen state. Failure (e.g. a stale wheel missing the binding) is caught and toasted; the
   optimistic icon remains for the session.

Because the message is posted on `<space>` (before any later `<esc>`), the write happens even if the user immediately
escapes — satisfying Q2's "survives esc." The pin does **not** change the stash count, so no badge refresh is needed.

When the panel is next opened (this session or after a restart), `_open_prompt_stash_panel` reads the snapshot, each
`PromptStashEntryWire` now carries `pinned`, and the modal seeds `self._pinned = {e.id for e in entries if e.pinned}` —
which is what makes the pin "survive restarts."

### Pin glyph (real-terminal UX decision — needs your sign-off)

Per fact #5, the snapshot is deterministic regardless of the glyph; this is purely about how the pin looks in a real
terminal.

- **Recommended:** the literal pushpin emoji **📌 (U+1F4CC)** — it is exactly the "pin icon" requested and renders
  correctly in modern terminals / Nerd Fonts. Trade-offs to accept: (a) in the committed PNG golden it renders as Fira
  Code's deterministic `.notdef` box (same as `✗`/`❄` already do today); (b) `📌` is an East-Asian-wide glyph (2 cells),
  so it gets its own fixed 2-cell row slot, and terminals that render emoji at 1 cell may show minor alignment wobble.
- **Alternative (if you prefer pixel-clean goldens and strict 1-cell alignment):** a width-1 icon. Note none of the
  obvious pin/star/flag dingbats (`★`, `⚑`, `❄`) are in the bundled Fira Code either, so they'd also be `.notdef` in the
  golden; a width-1 glyph only buys cleaner alignment, not glyph fidelity, in the snapshot.

The plan below assumes **📌**; swapping to a different glyph is a one-line change in two places (the row label and the
hint line) plus regenerating the one modal golden.

### Row rendering

The pin is **orthogonal** to the transient `✓` pop / `✗` delete marks (a row can be pinned _and_ marked for pop/delete
in the same session, since pin doesn't protect anything yet — Q3). So the pin gets its **own fixed-width column**, kept
visible independent of the transient marker. Layout becomes:
`[transient marker ✓/✗/blank][pin slot 📌/blank][age][project chip][bundle chip][preview]`. The pin slot is sized to a
constant display width; the preview width is trimmed slightly so the full row still fits the modal's fixed option area
(~86 cols). Toggling pin never clears a pop/delete mark, and toggling pop/delete never clears the pin.

### Scope decision: restore + keep

Repurposing `<space>` removes the only key that produced "restore + keep" marks. To keep the diff focused on the pin
feature and minimize blast radius (Q3 framing: "start adding a pin"), the **transport/app layer keeps its keep
capability**, while the **modal drops keep entirely**:

- **Modal:** remove `action_toggle_keep`, the `_keep` set, the `+`/`marked_for_keep` rendering branch, and the
  `keep_ids` line in `action_confirm` (it would always be empty). The modal no longer produces keep marks and has no
  dead keep code.
- **Result + app layer:** **leave `StashRestoreResult.keep_ids` and `_apply_stash_restore`'s keep handling intact.**
  They remain a functional, tested transport capability (load-without-pop) that simply is not currently driven by any
  panel key — preserved for a possible future "restore + keep" key without re-plumbing, and avoiding churn to the
  app-glue tests. This will be called out in code comments so a reviewer understands `keep_ids` is intentionally
  UI-unreachable for now. _(Alternative considered: fully remove `keep_ids` end-to-end. Rejected for this step — larger,
  orthogonal churn for no user-facing benefit.)_

## Scope of changes

### A. Rust core (`sase-core`, crate `sase_core`) — open via `sase workspace open -p sase-core`

1. **`crates/sase_core/src/prompt_stash/wire.rs`** — add `#[serde(default)] pub pinned: bool,` to
   `PromptStashEntryWire`. Leave `PROMPT_STASH_WIRE_SCHEMA_VERSION = 1` unchanged.
2. **`crates/sase_core/src/prompt_stash/store.rs`** — add `set_prompt_stash_pinned(path, ids, pinned)` (lock → read rows
   → set `pinned` on matching ids → `write_entries_atomic` if anything changed → return snapshot), following the
   `pop_prompt_stash` shape. Serialization needs no change (serde handles the new field).
3. **`crates/sase_core/src/prompt_stash/mod.rs`** — re-export `set_prompt_stash_pinned`.
4. **`crates/sase_core_py/src/lib.rs`** — add `py_set_prompt_stash_pinned` (mirroring `py_pop_prompt_stash`: take
   `path`, `ids: Vec<String>`, `pinned: bool`; `py.allow_threads(...)`; serialize to a Python dict) and register it with
   `m.add_function(wrap_pyfunction!(py_set_prompt_stash_pinned, m)?)?;`.
5. **`crates/sase_core/tests/prompt_stash_store_parity.rs`** — add tests: round-trip a `pinned` row (append → read);
   `set_prompt_stash_pinned` sets/clears the flag on matching ids and is a no-op for unknown ids; the on-disk JSON
   carries the `pinned` key (extend the existing wire-keys test); a legacy row without `pinned` reads back as
   `pinned = false`.
6. **Release/version:** bump the `sase_core_rs` package version per the sase-core release process so the new binding can
   be depended upon downstream.

### B. Python wire + facade (this repo)

1. **`src/sase/core/prompt_stash_wire.py`** — add `pinned: bool = False` to `PromptStashEntryWire`; read it in
   `_prompt_stash_entry_from_dict` (`bool(data.get("pinned", False))`). `prompt_stash_wire_to_json_dict` (via `asdict`)
   includes it automatically. Schema version unchanged.
2. **`src/sase/core/prompt_stash_facade.py`** — add
   `set_prompt_stash_pinned(path, ids, pinned) -> PromptStashSnapshotWire` calling
   `require_rust_binding("set_prompt_stash_pinned")`; add to `__all__`.

### C. Modal (this repo) — `src/sase/ace/tui/modals/stashed_prompts_modal.py`

1. **Bindings:** replace `("space", "toggle_keep", "Restore + keep")` with `("space", "toggle_pin", "Pin")`. `<tab>` →
   `toggle_pop` keeps `priority=True` (unchanged).
2. **State:** add `self._pinned = {e.id for e in entries if e.pinned}` in `__init__`; remove `self._keep`.
3. **`action_toggle_pin`:** for the highlighted single-prompt row (honor `_is_selectable`, i.e. inert on bundle rows),
   toggle membership in `_pinned`, update `entry.pinned` on the in-memory wire so a re-open within the session is
   consistent, repaint the row, and `post_message(StashedPromptsModal.PinToggled(entry, pinned))`. Do **not** touch
   `_pop`/`_deleted` (orthogonal).
4. **`PinToggled` message:** add a nested `class PinToggled(Message)` carrying `entry: PromptStashEntryWire` and
   `pinned: bool`.
5. **Remove `action_toggle_keep`** and the `keep_ids` line in `action_confirm` (build only `pop_ids`/`delete_ids`).
6. **`_stash_row_label`:** drop the `marked_for_keep`/`+` branch; add a `pinned: bool` parameter and a fixed-width pin
   column (📌 when pinned, blanks otherwise) placed after the transient marker; trim the preview width so the row still
   fits. `_build_options` passes `pinned=entry.id in self._pinned`.
7. **`_hint_text`:** change `space + restore+keep` to `space 📌 pin` (overall line gets shorter — no overflow risk).
8. **Docstrings:** update the module docstring and the `on_mount` comment — `<space>` pins (persisted immediately);
   `<tab>` restore+pop; `<enter>` restore highlighted. Note the modal now posts a persistence message (no longer
   strictly "never touches the store").

### D. App glue (this repo) — `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`

1. Add `on_stashed_prompts_modal_pin_toggled(self, event)` — guard the type, then persist off-thread via
   `asyncio.to_thread(set_prompt_stash_pinned, prompt_stash_path(), [event.entry.id], event.pinned)`, serialized through
   a per-mixin `asyncio.Lock` (lazily created, like `_prompt_stash_async_tasks`). Wrap in try/except and toast on
   failure (covers a stale wheel missing the binding). Reuse the existing `_spawn_prompt_stash_task` machinery to hold a
   task reference. No badge refresh (pin doesn't change the count).
2. Leave `_apply_stash_restore` / `keep_ids` handling untouched (see "Scope decision"); add a brief comment that
   `keep_ids` is intentionally not produced by the panel for now.

### E. Dependency pin (this repo) — `pyproject.toml`

Raise the `sase-core-rs` lower bound to the release that ships `set_prompt_stash_pinned` + the `pinned` field (exact
version from step A.6), keeping the upper bound policy as-is.

### F. Tests (this repo)

1. **`tests/ace/tui/modals/test_stashed_prompts_modal.py`:**
   - Replace the keep-oriented pilot tests with pin tests: `<space>` on a selectable row posts a
     `PinToggled(pinned= True)` and shows the pin icon; pressing it again posts `PinToggled(pinned=False)`; `<space>` is
     inert on bundle rows (no message); pin is orthogonal to pop/delete (pinning then `<tab>`/`d` keeps the pin set and
     also marks pop/delete; the confirm result still reflects pop/delete). Capture posted messages via a handler on the
     test host app.
   - Update `_stash_row_label` tests: drop the `+`/keep assertion; assert the pin column shows the pin when
     `pinned= True` and the row is plain otherwise; keep the `✓`/`✗`/bundle assertions.
   - Update `test_title_and_hints_describe_unified_panel` to assert the hint now advertises pin (e.g. `"pin"` substring)
     and still mentions `restore+pop` and `delete`; drop the `restore+keep` assertion.
   - Update the module docstring.
2. **`tests/ace/tui/actions/test_prompt_stash_restore.py`** (or a small new sibling test module): add a
   `_skip_without_pinned_binding()` helper (checks `hasattr(rust_module, "set_prompt_stash_pinned")`) and a test that
   driving `on_stashed_prompts_modal_pin_toggled` persists `pinned=True` to a temp store and that a subsequent snapshot
   read reflects it (and toggling back clears it). The existing keep-only tests stay as-is (keep transport unchanged).
3. **Python wire test** (extend the existing prompt-stash wire tests if present, else add): `PromptStashEntryWire`
   round-trips `pinned` through `prompt_stash_wire_to_json_dict` / `_prompt_stash_entry_from_dict`, and a dict missing
   `pinned` defaults to `False`.

### G. Visual snapshot (this repo)

- **`tests/ace/tui/visual/test_ace_png_snapshots_prompt_stash.py`:** in the modal snapshot fixture, replace the
  `modal._keep = {...}` line with a `modal._pinned = {...}` (pin one row) so the golden exercises the new pin column
  alongside `✓` pop and `✗` delete; update the docstring's marker description (`+` keep → 📌 pin). The badge snapshot is
  unaffected (pin doesn't change the count).
- Regenerate **only** the modal golden `tests/ace/tui/visual/snapshots/png/stashed_prompts_restore_modal_120x40.png`
  with `--sase-update-visual-snapshots`, and confirm the diff is limited to the pin column + the hint line. Leave
  `stashed_prompts_indicator_badge_120x40.png` untouched.

## Out of scope / explicitly deferred

- **Pinned-row protection/sorting/cleanup behavior** (no pop/delete protection, no sort-to-top, no cleanup exclusion) —
  deferred (Q3). Pin is icon + persistence only.
- **`<tab>` (restore + pop), `d` (delete), `a` (toggle-all → pop), `<enter>` (restore highlighted/confirm), `esc`/`q`,
  j/k navigation, bundle-row inertness** — unchanged.
- **`StashRestoreResult.keep_ids` / `_apply_stash_restore` keep handling** — retained as an unused-by-UI transport
  capability (see "Scope decision").
- **The top-bar badge** (`StashedPromptsIndicator`) — still a count; pin doesn't change it.
- **The global open key** (`@` / `restore_prompt_stash`), `default_config.yml`, the keymap registry, `bindings.py`, the
  `?` help modal, and the footer — unchanged (in-panel keys are documented only in the modal hint line).

## Verification

1. **Rust (`sase-core`):** `cargo test -p sase_core` (store parity tests, including the new pin tests) and the crate's
   lints/format per its own checks.
2. **Wire up the new binding locally:** build the editable Rust extension against the sibling `sase-core`
   (`just rust-install`) so `sase_core_rs` exposes `set_prompt_stash_pinned`; otherwise the binding-dependent Python
   tests skip and pin persistence degrades to a toast.
3. **Python (this repo):** `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy +
   tests). Targeted:
   - `tests/ace/tui/modals/test_stashed_prompts_modal.py`
   - `tests/ace/tui/actions/test_prompt_stash_restore.py`
   - the prompt-stash wire test
4. **Visual:** `just test-visual` for the ACE PNG suite; regenerate the one modal golden with
   `--sase-update-visual-snapshots` and confirm the diff is confined to the pin column + hint line.
5. **Manual sanity (optional):** in `sase ace`, open the stash panel, press `<space>` on a row → pin icon appears;
   `<esc>`; reopen → the pin is still there; restart `sase ace` → the pin is still there; press `<space>` again → it
   clears and stays cleared after reopen.

## Risks / Notes

- **Cross-repo sequencing.** The `pinned` field + `set_prompt_stash_pinned` ship in `sase-core` first (new
  `sase_core_rs` release); this repo then bumps the `sase-core-rs` pin. Until the new wheel is installed, the binding is
  absent: pin persistence degrades to a toast at runtime and the binding-dependent tests skip (the modal icon and the
  visual/modal tests still work, since they read `entry.pinned` from the in-memory wire). This mirrors the existing
  `_skip_without_prompt_stash_bindings()` contract.
- **Boundary correctness.** Persistence + the field live in Rust core (shared domain data); only the key binding, icon,
  and row layout live here — per `memory/rust_core_backend_boundary.md`.
- **Perf.** No synchronous disk I/O in the `<space>` handler: the modal repaints optimistically and posts a message; the
  app persists off-thread (serialized by a lock). Honors Q2's "immediate" timing and TUI perf rule #1.
- **Backward/forward compatibility.** Additive `#[serde(default)]` field, no schema bump; old rows read as unpinned.
  Only a _mixed_ old/new `sase_core_rs` setup could drop pins on rewrite (documented, not guarded).
- **Pin glyph.** The 📌-vs-width-1 choice is a real-terminal UX call (the snapshot is deterministic either way) and is
  flagged for your sign-off above; the plan assumes 📌.
- **Plan-file portability.** All paths above are repo-relative; `sase-core` edits/reads are done through
  `sase workspace open -p sase-core` (no hard-coded workspace directories).
