---
create_time: 2026-05-15 15:58:22
status: done
prompt: sdd/prompts/202605/ace_tab_cli_option_implementation.md
---
# Plan: Implement the `--tab` CLI option on `sase ace`

## Background — investigation finding

A previous tale at `sdd/tales/202605/ace_tab_cli_option.md` proposed adding a `--tab` option (default `agents`) to
`sase ace` and removing the old startup heuristic that auto-switched to the Agents tab. That tale was marked
`status: done`, but the corresponding code change was never made:

- `src/sase/main/parser_ace.py` does not register `--tab` (grep for `tab` returns no matches).
- `src/sase/main/ace_handler.py` does not pass any `initial_tab` kwarg into `AceApp`.
- `src/sase/ace/tui/app.py:137` still declares `current_tab: reactive[TabName] = reactive("changespecs", ...)` and
  `AceApp.__init__` has no `initial_tab` parameter.
- `src/sase/ace/tui/actions/startup.py:177-181` still contains the old "no results → fall back to saved queries; if
  still empty, jump to Agents tab" heuristic, and `_try_startup_fallback_async` still lives in
  `src/sase/ace/tui/actions/changespec/_query.py:74`.

Consequence today: when the startup query has results (the common case), `sase ace` stays on the class-level default
`"changespecs"` tab — which is the symptom the user observed (CLs tab focused on startup despite the user expecting
Agents).

The user's mental model — "we already added `--tab` defaulting to `agents`" — is grounded in the fact that the plan
exists and was marked done. The fix is to actually implement that plan now. The plan content below is unchanged in
spirit from the prior tale; this document captures what still needs to happen and re-confirms the user-visible decisions
before the implementation step.

## Goal

Make initial tab selection on `sase ace` deterministic and user-controlled:

- Add CLI option `--tab <tab_name>` accepting `changespecs`, `agents`, `axe`. Default: `agents`.
- Remove the existing startup auto-switch heuristic so behavior is governed solely by `--tab` (or its default).
- Drop the now-orphaned saved-query fallback (`_try_startup_fallback_async`) since its only caller was that heuristic.

## User-visible behavior changes

| Scenario                                                             | Before                                   | After                                         |
| -------------------------------------------------------------------- | ---------------------------------------- | --------------------------------------------- |
| `sase ace` (no flag), startup query has matches                      | Opens on CLs tab                         | **Opens on Agents tab** ← fixes user's report |
| `sase ace` (no flag), startup query empty, a saved query has matches | Loads that saved query, opens on CLs tab | Opens on Agents tab; startup query used as-is |
| `sase ace` (no flag), no matches anywhere                            | Opens on Agents tab                      | Opens on Agents tab                           |
| `sase ace --tab changespecs`                                         | n/a                                      | Opens on CLs tab regardless of result counts  |
| `sase ace --tab agents`                                              | n/a                                      | Opens on Agents tab                           |
| `sase ace --tab axe`                                                 | n/a                                      | Opens on AXE tab                              |
| `sase ace --tab bogus`                                               | n/a                                      | argparse exits with `invalid choice`          |

## Implementation outline

1. **Parser** — `src/sase/main/parser_ace.py`
   - Add `-t / --tab` to `register_ace_parser` with `choices=["changespecs", "agents", "axe"]` and `default="agents"`.
   - Insert into the existing alphabetical block of long-option names (between `--restart-axe` and `--vcs-provider`).

2. **Handler** — `src/sase/main/ace_handler.py`
   - Read `args.tab` and forward as a new `initial_tab` kwarg to `AceApp` (alongside the other kwargs in the existing
     `AceApp(...)` call at line ~84).

3. **App constructor** — `src/sase/ace/tui/app.py`
   - Add `initial_tab: TabName = "agents"` parameter to `AceApp.__init__`.
   - Pass it through to `_init_app_state(... initial_tab=initial_tab)`.
   - Update the docstring.

4. **State init** — `src/sase/ace/tui/actions/_state_init.py`
   - Accept `initial_tab` and assign `self.current_tab = initial_tab` during `_init_app_state`.
   - This runs before `on_mount`, so the reactive is correct on first paint (footer / info panels / tab bar all render
     against the right tab).

5. **Remove startup auto-switch** — `src/sase/ace/tui/actions/startup.py`
   - Delete the `if not self.changespecs: if not await self._try_startup_fallback_async(): self.current_tab = "agents"`
     block at lines 177-181.

6. **Delete orphaned fallback** — `src/sase/ace/tui/actions/changespec/_query.py`
   - Remove `_try_startup_fallback_async` (defined at line 74). The only production caller is the block deleted in
     step 5.

7. **Tests**
   - `tests/ace/tui/test_startup_stopwatch_live_update.py:30` — `test_try_startup_fallback_async_is_coroutine`
     references the deleted method. Drop that test.
   - `tests/ace/tui/test_changespec_query_corpus_routing.py:211` — calls `await app._try_startup_fallback_async()`. Drop
     or rewrite the assertion to exercise the new `initial_tab` plumbing instead.
   - Extend `tests/main/test_ace_handler.py`:
     - `--tab agents`, `--tab changespecs`, `--tab axe` each round-trip into the `initial_tab` kwarg.
     - Omitting `--tab` yields `initial_tab="agents"`.
     - `--tab bogus` causes argparse to exit non-zero.
   - Add a lightweight construction-level test that asserts `AceApp(initial_tab=<name>).current_tab == <name>`
     immediately after `__init__`, for each of the three values. (No mount required.)

8. **Docs** — `docs/ace.md`
   - Add a `--tab` row to the CLI Options table at line ~19, alphabetical by long-option name (insert between
     `--restart-axe` and `--vcs-provider`): description
     `Tab to focus on startup (changespecs, agents, axe; default: agents)`.
   - Per `src/sase/ace/AGENTS.md`, the help modal documents keybindings, not CLI flags — so no `?`-modal update.

9. **House cleanup**
   - Update the old tale's frontmatter? It was marked `status: done` prematurely. Worth flagging in review whether to
     amend it, leave a note, or supersede with a new tale referencing this implementation. Decision deferred to user.

10. **Sanity** — run `just check` from the workspace once changes are in.

## Decisions worth flagging in review

- **Default `agents`.** Matches the user's expectation and the prior plan. Side effect: users with no saved CL queries
  no longer get the "fall back to a saved query" behavior — startup uses the literal query argument (or its
  previous-last / first-saved / `!!!` default already resolved by argparse). The CLs tab is reachable in one keystroke
  via the tab-switch binding.
- **Removing `_try_startup_fallback_async` outright.** Its sole production caller is the auto-switch block; nothing else
  in `src/` references it. The two test references (above) are the only other callers. Removing it is the simplest path
  and avoids carrying dead behavior. Flag for confirmation.
- **Short flag `-t`.** Available in the current ace parser. Read naturally as "tab." Drop the short alias if preferred.
- **Old tale's `status: done`.** The plan file is misleading because it claims completion. Worth either appending a note
  ("not implemented in this branch — see new plan") or just letting the new implementation supersede it. User call.

## Files touched

- `src/sase/main/parser_ace.py`
- `src/sase/main/ace_handler.py`
- `src/sase/ace/tui/app.py`
- `src/sase/ace/tui/actions/_state_init.py`
- `src/sase/ace/tui/actions/startup.py`
- `src/sase/ace/tui/actions/changespec/_query.py`
- `tests/main/test_ace_handler.py`
- `tests/ace/tui/test_startup_stopwatch_live_update.py`
- `tests/ace/tui/test_changespec_query_corpus_routing.py`
- `docs/ace.md`
- (optional) `sdd/tales/202605/ace_tab_cli_option.md` — annotate stale `status: done`
