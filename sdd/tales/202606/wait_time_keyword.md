---
create_time: 2026-06-24 15:49:19
status: done
prompt: sdd/prompts/202606/wait_time_keyword.md
---
# Plan: Migrate `%time` to a `time=` keyword on `%wait` (+ new `#t` xprompt)

## Goal & product context

Today there are two separate launch-deferral directives:

- `%wait:<agent>` — defer launch until named agent(s)/workflows complete (positional agent names only).
- `%time:<dur|abs>` — defer launch by a duration (`5m`, `1h30m`) or until an absolute wall-clock time (`1430`,
  `260415/0900`).

They already "combine freely" in a prompt (`%wait:planner %time:5m`), but they're spelled as two directives. This
migration unifies them: **the wall-clock deferral becomes a `time=` keyword input on `%wait`**, so a single directive
can carry both an agent dependency and a time floor:

- `%time:5m` → `%wait(time=5m)`
- `%wait(planner, time=5m)` → wait for `planner`, _then_ apply a 5-minute floor (one directive).

To keep the standalone time-wait ergonomic (the common `%time:5m`-alone case), add a **builtin `#t` xprompt** that
expands to `%wait(time=<time>)`. So `#t:5m` is the new short spelling for a pure time wait, while `%wait(...)` is the
general form that mixes positional agent names with the `time=` keyword.

**Key design constraint — storage/wire format is unchanged.** This is purely a _spelling/parsing_ change. The parsed
result still lands in the existing `PromptDirectives.wait` / `wait_duration` / `wait_until` fields, and the persisted
`waiting.json` / `agent_meta.json` fields (`wait_duration`, `wait_until`) are untouched. Everything downstream (TUI
display, the Rust agent scanner, axe runtime re-extraction) keeps working with no changes. This keeps the blast radius
at the parser + a thin editor-metadata mirror.

## Background: how the pieces fit today

- Directive parsing lives in `src/sase/xprompt/`:
  - `_directive_types.py` — `PromptDirectives` dataclass, the directive regex, `_KNOWN_DIRECTIVES`,
    `_MULTI_VALUE_DIRECTIVES` (currently `{"time", "wait"}`), and aliases (`w`→`wait`; there is deliberately no
    `t`/`time` alias).
  - `directives.py` — `extract_prompt_directives()` (the parser), plus the cheap `has_deferred_start_directive()`
    predicate.
  - `_directive_time.py` — `parse_duration()` / `parse_absolute_time()` (unchanged logic; only docstrings/error-message
    spellings need touch-ups).
  - `_parsing_args.py` — `parse_args()` already returns **both** positional and named args; the directive parser
    currently throws the named dict away (`positional_args, _ = parse_args(...)`).
- Processing order (confirmed in `llm_provider/preprocessing.py`): xprompt references are expanded **first**, then
  `extract_prompt_directives()` runs. So `#t:5m` → `%wait(time=5m)` is expanded before the directive parser sees it —
  the `#t` approach is sound.
- The combine/fold rules already exist in the current `%time` branch of `extract_prompt_directives` (durations fold to
  `max`; one absolute time allowed; duration+absolute is an error). We **reuse** these rules verbatim — just feeding
  them from the new `time=` keyword collection instead of `%time`.
- The Rust core mirrors directive _metadata_ for the editor/LSP (Neovim) in `crates/sase_core/src/editor/directive.rs`
  (the `DIRECTIVES` table + arg-candidate hints + tests). This must be updated to drop `time` and reflect the `time=`
  keyword, per the rust-core boundary rule (editor integration must match the TUI). The Rust agent _scanner_ only reads
  persisted `wait_duration`/ `wait_until` and needs **no** change.

## Scope of changes

### 1. Directive types — `src/sase/xprompt/_directive_types.py`

- Remove `"time"` from `_KNOWN_DIRECTIVES`.
- Change `_MULTI_VALUE_DIRECTIVES` to just `{"wait"}`.
- Add a small `_DEPRECATED_DIRECTIVES = frozenset({"time"})` used to raise a helpful migration error (see Decision D1).
- `PromptDirectives` dataclass is unchanged (still carries `wait`, `wait_duration`, `wait_until`). Update the field
  docstrings to note `wait_duration`/`wait_until` now come from the `%wait(time=...)` keyword.

### 2. Parser — `src/sase/xprompt/directives.py` (`extract_prompt_directives`)

- **Deprecation guard for `%time`:** in the match loop, after alias resolution, if the directive name is in
  `_DEPRECATED_DIRECTIVES`, raise `DirectiveError` with a migration hint pointing to `#t:<time>` / `%wait(time=<time>)`.
  (This mirrors the existing "`%wait:5m` is a time wait" guard pattern.)
- **Capture the `time=` keyword on `%wait`:** in the paren-form branch, stop discarding the named dict from
  `parse_args()`. When the directive is `wait`, pull a `time` named arg into a new accumulator
  (`wait_time_args: list[str]`) collected across _all_ `%wait` directives in the prompt. Reject any _other_ named key on
  `%wait` with a clear `DirectiveError` (only `time=` is supported). Positional args continue to be collected as agent
  names exactly as today.
- **Reuse the existing fold/combine logic:** repoint the current `%time` block (duration `max`-fold, single absolute
  time, duration+absolute conflict, empty-value error) to consume `wait_time_args` instead of `seen_multi["time"]`.
  Output still sets `wait_duration` / `wait_until`. The empty-value error message changes from "Bare '%time' requires…"
  to reference `%wait(time=…)`.
- **Update the positional time-shaped guard:** the `%wait:5m` / `%wait:1430` guard (which currently says "use `%time:5m`
  instead") must now point to `%wait(time=5m)` / `#t:5m`. Positional time-shaped args on `%wait` remain rejected
  (they're ambiguous with agent names); the `time=` keyword is the only way to express a time wait through `%wait`.
- **`has_deferred_start_directive()`:** remove the `%time` regex branch. Add detection of the `#t` xprompt reference so
  a standalone `#t:5m` still defers workspace allocation (parity with old `%time:5m`), mirroring the existing `#fork`
  special-case. See Decision D2.

### 3. Time-parsing helpers — `src/sase/xprompt/_directive_time.py`

- No logic change to `parse_duration` / `parse_absolute_time`.
- Update the module docstring and the user-facing error strings that currently embed `%wait:<s>` spelling to the new
  canonical `%wait(time=<s>)` form (or make them spelling-agnostic), so error messages match reality.

### 4. New builtin xprompt — `src/sase/xprompts/t.md`

A simple markdown (single `prompt_part`) xprompt, in the style of `coder.md`:

```markdown
---
name: t
description: Defer launch until a duration elapses or an absolute wall-clock time.
input:
  - name: time
    type: line
    description: Duration (e.g. 5m, 1h30m, 90s) or absolute time (e.g. 1430, 260415/0900).
---

%wait(time={{ time }})
```

This is auto-discovered by the internal-xprompt loader (no registry edit needed). It supports `#t:5m`, `#t(5m)`, and
`#t(time=5m)`. Validation of the actual time value still happens in the directive parser
(`parse_duration`/`parse_absolute_time`), so the xprompt just passes the token through. See Decision D3 for the input
`type`.

### 5. Rust editor metadata — sase-core linked repo (`crates/sase_core/src/editor/directive.rs`)

Access via `sase workspace open -p sase-core -r "<reason>" <workspace_num>` and edit only under that path.

- Remove the `time` entry from the `DIRECTIVES` table.
- Remove the `"time" => …` case from `directive_argument_candidates`. Optionally add `time=5m` / `time=1h` hints to the
  `wait` arg candidates and extend the `wait` `description` to mention the `time=` keyword.
- Fix the Rust unit tests that assert `time` metadata / `%t`→`time` completion
  (`auto_is_the_advertised_auto_approve_directive`, `directive_completion_t_prefix_yields_only_time`): after removal,
  `%t` directive completion yields nothing. Add coverage that `time` is no longer a directive.
- The agent scanner (`agent_scan/scanner.rs`, `agent_scan/wire.rs`) is **unchanged** — it reads persisted
  `wait_duration`/`wait_until`, whose format is unchanged. Verify, don't edit.
- Rebuild the `sase_core_rs` binding and run sase-core's own checks/tests.

### 6. Tests (Python) — `tests/`

- `test_directives_time.py`: migrate cases from `%time:5m` to `%wait(time=5m)` (consider renaming the file to reflect
  the new spelling). Add a case asserting `%time:5m` now raises the deprecation hint.
- `test_directives_time_repeat.py`: migrate `%time` → `%wait(time=…)` in the `%repeat` interaction tests.
- `test_directives_wait.py`: update the migration-guard tests (currently expect a `%time:…` hint) to expect the new
  hint. Add new coverage:
  - `%wait(time=5m)` sets `wait_duration` and leaves `wait` empty.
  - `%wait(agent_a, time=5m)` sets both `wait=["agent_a"]` and `wait_duration`.
  - `%wait(time=1430)` sets `wait_until`; absolute+duration and double-absolute conflicts still error.
  - `%wait(time=5m) %wait(time=10m)` folds to the max.
  - An unknown keyword on `%wait` (e.g. `%wait(foo=bar)`) raises.
- `test_directives_has_helpers.py`: update `has_deferred_start_directive` cases (drop `%time` ⇒ True; add
  `#t:5m`/`#t(5m)` ⇒ True, including fenced/disabled-region suppression). Keep the assertion that `%time`/ `%t` are not
  `%wait` matches.
- New `#t` xprompt integration test: `#t:5m` expands through preprocessing to a `wait_duration`, `#t(time=1430)` to a
  `wait_until`, etc.
- Run the existing `test_xprompt_catalog_*` suites; `#t` should classify as built-in automatically (the classification
  tests use mocked xprompts, so no enumeration edit is expected — verify).

### 7. Docs — `docs/xprompt.md`

- Rewrite the `%time` section to document the `%wait(time=…)` keyword and the `#t` shorthand, including the combine
  rules (agent waits first, then the time floor) and the duration/absolute formats.
- Update the migration note so the time-shaped-`%wait` error points at `%wait(time=…)` / `#t:…`.
- Blog posts under `docs/blog/posts/` mention `%time` historically — leave as-is or add a brief "now spelled
  `%wait(time=…)`/`#t`" note (Decision D4; low priority, non-blocking).

## Decisions to confirm (with recommendations)

- **D1 — What does `%time:5m` do after migration?** _Recommend:_ raise a `DirectiveError` with a migration hint
  (`use #t:5m or %wait(time=5m)`), consistent with the existing `%wait:5m` guard. Alternatives: leave `%time` as an
  unknown token (silently kept in the prompt — worse UX), or keep `%time` permanently as an alias (contradicts
  "migrate"). Going with the deprecation error.
- **D2 — Deferred-start parity for `#t`.** _Recommend:_ teach `has_deferred_start_directive()` to recognize a top-level
  `#t` reference (like `#fork`) so standalone `#t:5m` defers workspace allocation just as `%time:5m` did. If we skip
  this, `#t:5m` is still _correct_ (it waits) but claims its workspace immediately instead of after the wait — a minor
  efficiency regression vs. the old `%time`. Including the parity fix.
- **D3 — `#t` input `type`.** _Recommend:_ `line` (a single whitespace-free token like `5m` or `260415/0900`; the parser
  does the real validation). `word` is an acceptable stricter alternative.
- **D4 — Blog-post mentions of `%time`.** _Recommend:_ out of scope for behavior; optionally add a one-line migration
  note. Non-blocking.

## Risks & verification

- **Breaking change** (`feat!`): `%time` stops working. This matches the repo's recent directive-migration style (e.g.
  the unify-auto-approval change). The deprecation error makes the break self-documenting.
- **Cross-repo parity:** the Python parser and the Rust editor metadata must agree. Run both `just check` in the primary
  repo and sase-core's checks/tests after rebuilding the binding.
- **Verification:** `just install` then `just check` in the primary repo; rebuild + test sase-core; spot-check in the
  TUI that `%wait(planner, time=5m)`, `%wait(time=1430)`, and `#t:5m` all parse and that `%time:5m` surfaces the
  migration error.

## Out of scope

- Renaming or changing the persisted `wait_duration`/`wait_until` fields or `waiting.json` format.
- Any change to how waits are _evaluated_ at launch time (this is purely a parse/spelling migration).
- Changing `%wait`'s positional agent-name / template / bare-resolution behavior.
