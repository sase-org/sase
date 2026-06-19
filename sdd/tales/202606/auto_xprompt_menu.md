---
create_time: 2026-06-19 15:48:29
status: done
prompt: sdd/prompts/202606/auto_xprompt_menu.md
---
# Plan: Auto-trigger xprompt completion on `#<X>` (like `#+` project completion)

## Goal

Today, the `#+` VCS-project completion menu pops open **automatically** as the user types `#+` in the `sase ace` TUI
prompt input — no extra keystroke, instant feedback. By contrast, normal xprompt completion (tokens like `#foo`, and
`#!foo` for standalone-only xprompts) requires the user to press `<ctrl+t>` to open the menu.

We want normal xprompt completion to **auto-open the same dropdown menu** as the user types `#<X>` — where `<X>` is any
character (including `!`) — matching the look, feel, and speed of `#+` project completion. The `<ctrl+t>` trigger
remains as-is for explicit invocation (and for kinds we don't auto-trigger, e.g. file paths).

Non-negotiable: it must be **fast** — no perceptible keystroke lag, no synchronous disk I/O on the event loop
(`memory/tui_perf.md`).

## Current architecture (what we're mirroring)

The prompt input is a `PromptTextArea` (`src/sase/ace/tui/widgets/prompt_text_area.py`) composed of several mixins. The
completion machinery lives in `_file_completion.py`, `_file_completion_context.py`, and the keystroke entry point
`_prompt_text_area_key_handling.py`.

**How `#+` auto-opens (the model to copy):**

- In `_prompt_text_area_key_handling.py` (`_on_key`, ~lines 308-317), after the default key insert, the handler calls
  `_refresh_file_completion_from_cursor()` (narrows an already-open menu), then — guarded by `event.character == "+"`,
  insert mode, and `not self._file_completion_active` — calls `_try_vcs_project_completion()`.
- `_try_vcs_project_completion()` (`_file_completion.py` ~145) detects the `#+query` trigger, builds candidates from a
  **warm in-memory catalog**, sets `_completion_kind = VCS_PROJECT_COMPLETION_KIND`, `_file_completion_active = True`,
  and paints the panel. It does **not** auto-accept a single candidate or auto-extend a shared prefix — it just shows
  the menu.
- Narrowing as you keep typing is handled by `_refresh_file_completion_from_cursor()` (the `VCS_PROJECT_COMPLETION_KIND`
  branch, ~380).
- Speed comes from warming: `_warm_vcs_project_completion_catalog()` runs the catalog build in a background worker on
  mount, so the first keystroke reads a populated module-level cache instead of touching disk.

**How xprompt completion works today (only via `<ctrl+t>`):**

- `<ctrl+t>` → `_try_file_completion_tab()` (`_file_completion.py` ~469). It tries `#+` first, then Jinja, then
  xprompt-arg, then falls back to a raw-token classifier: `is_xprompt_like_token(raw_token)` →
  `_completion_kind = "xprompt"`, candidates from `self._build_xprompt_completion_candidates(token)`.
- Crucially, the `<ctrl+t>` path has **explicit-invocation semantics** we must NOT replicate for an auto-trigger: if
  exactly one candidate matches it **auto-inserts** it, and on a shared prefix it **auto-extends** the token (lines
  ~527-574). That is correct for a deliberate keypress but wrong for typing — we don't want a single match to be
  silently committed mid-word.
- `self._build_xprompt_completion_candidates(token)` (`_file_completion_context.py` ~246) is the fast path: it prefers
  the **warm** per-project catalog (`_get_warm_xprompt_arg_assist_entries()`), merged with live local xprompts from the
  Frontmatter Panel. The warm catalog is filled on mount by `_warm_current_xprompt_assist_entries()` (background
  worker). **However**, when the warm cache is cold it falls back to a **synchronous** catalog build (disk scan) —
  acceptable for a one-shot `<ctrl+t>`, but unacceptable to run repeatedly on the per-keystroke auto path.
- The dropdown widget, rendering, navigation (`ctrl+n/p`), and accept (`ctrl+l` / `enter`) are already shared across all
  completion kinds — no new UI is needed.

**Token boundaries (already favorable):** `extract_token_around_cursor()` (`file_completion.py` ~45) splits on
whitespace and delimiters. `#` is not a delimiter, so a `#`-token only starts after whitespace/line-start (e.g.
`foo#bar` → token `foo#bar`, not an xprompt; `foo #bar` → `#bar`). `!` is a delimiter but there is special handling that
re-includes the `#!` marker, so `#!foo` extracts as one token. `#+` is handled by its own `find_vcs_project_trigger()`
and stays owned by the `#+` path. This means the natural boundary behavior already matches `#+`'s "only at start / after
whitespace" rule.

## Design

Add an xprompt analog of the `#+` auto-open, parallel in shape and equally fast.

### 1. New auto-open method (presentation glue, `_file_completion.py`)

Add `_try_auto_xprompt_completion() -> bool` modeled on `_try_vcs_project_completion()`:

1. Only in prompt mode (mirror `#+`'s `bar._mode == "prompt"` guard).
2. **Yield `#+` to the project path:** if `_get_vcs_project_trigger()` is not `None`, return `False` (the `#+` menu owns
   those tokens).
3. Resolve the xprompt token via `_get_xprompt_token_context()`. Require `is_xprompt_like_token(token)` and a token
   length ≥ 2 — i.e. `#` plus at least one character, or the bare `#!` marker. (A lone `#` does not open, exactly as a
   lone `#` doesn't open the `#+` menu until `+` is typed.) Scope to `#`-prefixed tokens only; `/skill` slash tokens
   stay on `<ctrl+t>` for now.
4. Build candidates from **warm-or-local entries only** (see Performance) — never a synchronous global build. If the
   catalog is cold, schedule the warm pass and return `False` (no menu this keystroke; it opens on the next keystroke
   once warm).
5. If no candidates match, return `False` and leave the menu closed (no "no matches" placeholder — keeps it unobtrusive
   in prose; contrast with `#+`'s "no active projects" row, which is desirable there but noise here).
6. Otherwise set `_completion_kind = "xprompt"`, `_file_completion_active = True`, candidates, index 0, and paint the
   panel. **No auto-accept, no auto-extend** — show-only, just like `#+`.

Narrowing as the user keeps typing already works: the `_completion_kind == "xprompt"` branch of
`_refresh_file_completion_from_cursor()` recomputes candidates and dismisses when the token stops matching. No change
needed there.

### 2. Wire it into the keystroke handler (`_prompt_text_area_key_handling.py`)

Right after the existing `#+` auto-open block in `_on_key`, add a sibling block guarded by: insert mode,
`not self._file_completion_active`, and `event.character` being a single printable non-whitespace character. Call
`_try_auto_xprompt_completion()`. Because the method yields on `#+` tokens and the `#+` block already runs first, there
is no double-trigger. The trailing `_on_prompt_completion_context_changed()` (soft/ghost completion) is naturally
suppressed while the menu is active (`_soft_completion_blocked()` already returns `True` when
`_file_completion_active`), so ghost text and the dropdown never fight.

### 3. Performance: warm-only candidate sourcing

The auto path fires on (potentially) every keystroke, so it must never block the event loop. Add a helper that sources
candidates **only** from already-available data — the warm per-project catalog
(`_get_warm_xprompt_arg_assist_entries()`) merged with live local xprompts (`_local_xprompt_assist_entries()`) — and
returns "not ready" instead of doing a synchronous disk build. This is exactly the pattern soft completion already uses
(`_soft_completion_xprompt_entries()`). When cold, it calls `_warm_current_xprompt_assist_entries()` (idempotent;
already invoked on mount) and bails for this keystroke. Filtering warm entries is pure in-memory work — O(number of
xprompts) — matching `#+`'s speed.

This is the one deliberate divergence from the `<ctrl+t>` path, which is allowed to do a one-shot synchronous build. It
keeps us inside `memory/tui_perf.md` rule #1 (never block the loop) and #7 (memoize per-keystroke). The existing
narrowing path is unchanged: by the time a menu is open, the warm catalog (or local entries) that opened it is
available, so narrowing stays on the fast path.

### 4. Config toggle (recommended)

Add `auto_xprompt_menu: true` under `ace.prompt_completion` in `src/sase/default_config.yml`, a matching field on
`PromptCompletionSettings` (`prompt_completion.py`) parsed by `parse_prompt_completion_settings`, and gate the new
auto-open block on it. Default **on**. Rationale: gives a clean opt-out without disabling the separate ghost-text "soft"
completion (`auto: soft`), and satisfies `memory/gotchas.md` (keep `default_config.yml` in sync). The `#+` feature
shipped without a toggle, so this is a judgment call — see Design decisions; if we prefer minimal surface area we can
make it always-on like `#+` and drop this step.

## Design decisions (please confirm)

1. **Open at `#<X>` (2 chars), not at a lone `#`.** Mirrors `#+` (which needs the `+`) and the user's literal `#<X>`
   phrasing; avoids firing on every stray `#`. _Recommended._ Alternative: also open on a bare `#` to surface the full
   list immediately.
2. **Only open when ≥1 candidate matches; no placeholder row.** Keeps it unobtrusive in prose (`# heading`, `#123` match
   no xprompt → no menu). _Recommended._
3. **Show-only semantics: no auto-accept / no auto-extend on the auto path.** Auto-committing a sole match while typing
   would be surprising. `<ctrl+t>` keeps its current auto-accept/extend behavior. _Recommended._
4. **Scope: `#`-prefixed xprompt tokens only.** `#foo` and `#!foo`. Leave `/skill` slash completion and `#foo(args)` /
   `#foo:arg` argument completion on their existing triggers (unchanged). _Recommended._
5. **Prompt mode only** (not feedback mode), matching `#+`. _Recommended;_ easy to extend to feedback later if desired.
6. **Add the `auto_xprompt_menu` config toggle (default on)** vs. always-on like `#+`. _Recommended: add the toggle._

## Rust core boundary analysis

No `../sase-core` changes. Litmus test (`memory/rust_core_backend_boundary.md`): the _data_ that another frontend would
need to match — the xprompt catalog and candidate set — is already produced in Python (`sase.xprompt.catalog` /
`loader`) and is **not** part of the Rust core (unlike `#+`, whose expansion algorithm is mirrored in Rust). What we're
adding is purely **when the TUI pops its menu** — presentation-only Textual behavior, explicitly allowed to live in this
repo. Selecting an xprompt just inserts `#name`; there is no cross-frontend expansion algorithm to keep in parity.
(Neovim's xprompt LSP completion already triggers as you type, the way LSP normally does — this change brings the TUI in
line with that. Confirming/adding a `#` LSP trigger in `sase-nvim` would be a separate, out-of-scope parity task.)

## Files to change

- `src/sase/ace/tui/widgets/_file_completion.py` — add `_try_auto_xprompt_completion()` and the warm-only candidate
  helper.
- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py` — add the auto-open block after the `#+` block in
  `_on_key`.
- `src/sase/ace/tui/widgets/prompt_completion.py` — add `auto_xprompt_menu` to `PromptCompletionSettings` + parser (if
  we keep the toggle).
- `src/sase/default_config.yml` — add `ace.prompt_completion.auto_xprompt_menu: true` (if we keep the toggle).
- Possibly a thin `TYPE_CHECKING` stub addition in the mixin protocol(s) for the new method, consistent with the
  existing pattern.

## Testing plan

Mirror `tests/ace/tui/widgets/test_vcs_project_completion.py` (the `#+` auto-open suite) in a new
`tests/ace/tui/widgets/test_auto_xprompt_completion.py`, using the `CompletionTestApp` pilot harness. Note
`CompletionTestApp` has no `get_prompt_completion_settings`, so warming is gated off there — tests seed the warm cache
directly (e.g. set `text_area._xprompt_arg_assist_entries_by_project[None] = [entries]`) to simulate a warmed catalog,
the realistic production state.

Cases:

- `#f` auto-opens the menu filtered to xprompts starting with `f`; `_completion_kind == "xprompt"`,
  `_file_completion_active`.
- `#!` auto-opens filtered to standalone (`#!`) xprompts only.
- Typing more narrows; deleting widens; a space dismisses.
- A lone `#` does **not** open.
- `#<X>` with no matching xprompt does **not** open (no placeholder).
- `#+` still routes to the project menu, not the xprompt menu (no double-trigger / no shadowing).
- `foo#bar` (no boundary) does **not** open.
- Cold catalog (no warm, no local): does **not** open and **does not** perform a synchronous build; schedules warm;
  opens on a subsequent keystroke once seeded.
- `<ctrl+t>` behavior unchanged (auto-accept single / auto-extend shared prefix still work).
- If the toggle is added: `auto_xprompt_menu: false` disables auto-open while `<ctrl+t>` still works.
- Regression: existing `#+`, Ctrl+T xprompt, xprompt-arg, jinja, directive, and soft-completion suites stay green.

## Edge cases & risks

- **Intrusiveness:** mitigated by "open only on a real prefix match" — most prose `#` usage matches no xprompt and shows
  nothing. The toggle is the escape hatch.
- **Ghost text vs. dropdown:** already mutually exclusive via `_soft_completion_blocked()` (`_file_completion_active`).
  Verify no flicker.
- **`#!` marker quirks:** reuse the existing `#!` token extraction so behavior matches `<ctrl+t>` exactly.
- **Warm-with-local-only window:** if the menu opens from local xprompts while the global warm is still cold, the
  existing narrowing path may do a one-shot synchronous global build (pre-existing `<ctrl+t>` behavior, not a new
  regression). Acceptable; note it.

## Verification

Run `just install` (ephemeral workspace) then `just check` before completing. Add/adjust tests above. Spot- check
interactively in `sase ace` that `#f`/`#!` feel as instant as `#+`, optionally with `SASE_TUI_PERF=1` to confirm no
keystroke-path regression.

## Out of scope

- Neovim `sase-nvim` LSP `#` trigger parity (separate task if needed).
- Slash `/skill` auto-trigger and `#foo(args)` argument-completion auto-trigger (keep current triggers).
- Any change to the shared `#+` expansion algorithm or its Rust mirror.
