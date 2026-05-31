---
create_time: 2026-05-31 16:33:09
status: wip
prompt: sdd/prompts/202605/obsidian_datetime_snippets_1.md
---
# Add Obsidian Date/Time Snippets

## Context

The active Obsidian vault is `~/bob`. The current vault already has a local plugin at
`~/bob/.obsidian/plugins/bob-ledger-tools/main.js` that registers a high-priority Tab keymap and expands the existing
`se...` ledger time-range snippet at the cursor. That is the best integration point because it already handles Obsidian
editor access, cursor replacement, single-cursor guarding, and helper exports.

The NeoVim references are in `~/.local/share/chezmoi/home/dot_config/nvim/luasnippets/all.lua`:

- `d(-?[0-9]+)` expands to a local date offset by N days in `YYYY-MM-DD`.
- `t(-?[0-9]+)` expands to a local time offset by N minutes in `HHMM`.

Old zorg snippets also used full datetimes in `YYYY-MM-DD HH:MM`, so I will use that as the Obsidian datetime format.

`~/bob/.obsidian/plugins/bob-ledger-tools/main.js` is already modified in the worktree before this task; the existing
diff changes completed-pomodoro lookup to use the last completed item. I will preserve that change and layer the snippet
work on top of the current file.

## Behavior

Add Tab expansion for these cursor-local snippets in Markdown editors:

- `t<N>` / `t-<N>`: current local time plus N minutes, formatted `HHMM`.
- `d<N>` / `d-<N>`: current local date plus N calendar days, formatted `YYYY-MM-DD`.
- `dt<N>` / `dt-<N>`: current local datetime plus N minutes, formatted `YYYY-MM-DD HH:MM`.

For `dt`, using minutes is intentional: LuaSnip has no existing `dt` snippet, and minute offsets make datetime behave
like the time snippet while naturally rolling the date across midnight. A day-level datetime offset is still available
as `dt1440`, `dt-1440`, etc. If plan feedback prefers `dtN` to mean N days, that is the one decision to change before
implementation.

The new snippets will use the same safety boundaries as the existing `se` snippet: expand only when the trigger is
preceded by start-of-line or a non-word character, and not when the next character is a word character. This keeps
snippets usable in normal prose while avoiding expansion inside ordinary words.

The new date/time snippets will replace only the trigger text and will not add an implicit trailing space, matching the
NeoVim snippet output. Existing `se...` behavior, including its trailing-space behavior and parenthesized replacement
special case, should remain unchanged.

## Implementation Plan

1. Generalize the existing trigger parser in `~/bob/.obsidian/plugins/bob-ledger-tools/main.js`.
   - Keep the current `se...` parser behavior intact.
   - Add parsing for `t(-?[0-9]+)`, `d(-?[0-9]+)`, and `dt(-?[0-9]+)`.
   - Match `dt` before `d` so `dt5` is not parsed as `d...`.

2. Add small local date/time helpers.
   - Format compact times as `HHMM`.
   - Format dates as `YYYY-MM-DD`.
   - Format datetimes as `YYYY-MM-DD HH:MM`.
   - Use local `Date` methods so output matches Obsidian/browser local time.
   - Use calendar-day arithmetic for `dN` so DST transitions do not turn a date offset into a wall-clock-hour surprise.

3. Route `findExpansion()` through a snippet-specific expansion function.
   - `se...` continues to call the existing `computeRange()` path.
   - `t...`, `d...`, and `dt...` compute their replacement text from the parsed offset.
   - Keep the existing single-cursor, CodeMirror, and editor replacement code.

4. Update command/user-facing labels only where useful.
   - Keep existing command IDs stable so any hotkeys or command palette state do not break.
   - Broaden command names/notices from "ledger time range snippet" to "Bob snippet" if needed.
   - Update the plugin manifest description only if it is misleading after the new snippets.

5. Preserve helper exports for verification.
   - Keep existing exported helpers.
   - Export any new helper functions that make deterministic testing practical.

## Verification

Because the vault plugin does not have a package-level test harness, use a focused Node smoke harness with stubbed
`obsidian` and CodeMirror requires to load `main.js` and exercise `module.exports.helpers`.

Run deterministic checks against a fixed local date such as `2026-05-31T15:46:00`:

- `t0` -> `1546`
- `t-5` -> `1541`
- `t20` -> `1606`
- `d0` -> `2026-05-31`
- `d-1` -> `2026-05-30`
- `dt0` -> `2026-05-31 15:46`
- `dt20` -> `2026-05-31 16:06`
- midnight rollover cases for `t...` and `dt...`
- unchanged `se`, `se2`, and `se2-3` behavior
- boundary cases that must not expand inside words or before a word character

Then do a manual Obsidian smoke test after reloading the plugin: in a scratch note, type representative snippets and
press Tab to confirm replacement and cursor placement.

## Files Expected To Change

- `~/bob/.obsidian/plugins/bob-ledger-tools/main.js`
- Possibly `~/bob/.obsidian/plugins/bob-ledger-tools/manifest.json` if the description should be broadened.

No note content or SASE memory files should be modified.
