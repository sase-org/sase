---
create_time: 2026-05-15 13:46:58
status: done
prompt: sdd/prompts/202605/ace_tab_cli_option.md
---

# Plan: Replace auto-tab-focus logic with explicit `--tab` option on `sase ace`

## Goal

Make initial tab selection on `sase ace` deterministic and user-controlled.

- Remove the existing startup heuristic that auto-switches to the Agents tab (and the saved-query fallback that fed into
  that decision).
- Add a new CLI option `--tab <tab_name>` that accepts exactly three values — `changespecs`, `agents`, `axe` — and
  defaults to `agents` when omitted.

## Background — what exists today

When `sase ace` mounts, after loading ChangeSpecs for the startup query, the following logic runs in
`src/sase/ace/tui/actions/startup.py:177-181`:

```python
# If no results, try saved queries as fallback; if none work, open
# the Agents tab instead
if not self.changespecs:
    if not await self._try_startup_fallback_async():
        self.current_tab = "agents"
```

`_try_startup_fallback_async` (defined in `src/sase/ace/tui/actions/changespec/_query.py:74-123`) iterates saved query
slots 1-9 then 0, swaps to the first slot that returns results, and reports success/failure. The boolean result is
consumed only at the call site above — its purpose is to decide whether to remain on the CLs tab or switch to Agents.

The class-level default of `AceApp.current_tab` is `"changespecs"` (`src/sase/ace/tui/app.py:137`). With the new `--tab`
flag, this default is overridden at construction time before `on_mount` runs.

The tab names are defined in `src/sase/ace/tui/widgets/tab_bar.py:12-24`: `"changespecs"`, `"agents"`, `"axe"` (labelled
`CLs`, `Agents`, `AXE`).

`sase ace` argparse lives in `src/sase/main/parser_ace.py`; the handler that constructs `AceApp` lives in
`src/sase/main/ace_handler.py:47-104`; `AceApp`'s constructor calls into `_init_app_state` in
`src/sase/ace/tui/actions/_state_init.py:43`.

## Behavior changes the user sees

| Scenario                                                             | Before                                   | After                                            |
| -------------------------------------------------------------------- | ---------------------------------------- | ------------------------------------------------ |
| `sase ace` (no flag), startup query has matches                      | Opens on CLs tab                         | Opens on Agents tab                              |
| `sase ace` (no flag), startup query empty, a saved query has matches | Loads that saved query, opens on CLs tab | Opens on Agents tab; startup query is used as-is |
| `sase ace` (no flag), no matches anywhere                            | Opens on Agents tab                      | Opens on Agents tab                              |
| `sase ace --tab changespecs`                                         | n/a                                      | Opens on CLs tab regardless of result counts     |
| `sase ace --tab axe`                                                 | n/a                                      | Opens on AXE tab                                 |
| `sase ace --tab agents`                                              | n/a                                      | Opens on Agents tab                              |
| `sase ace --tab bogus`                                               | n/a                                      | argparse rejects with `invalid choice`           |

The default of `agents` matches the user's stated preference and aligns with the old "no results anywhere" fallback, so
the most common empty-results experience is unchanged.

## Implementation outline

1. **Parser** — `src/sase/main/parser_ace.py`
   - Add `-t / --tab` option to `register_ace_parser` with `choices=["changespecs", "agents", "axe"]` and
     `default="agents"`.
   - Insert in the existing alphabetical block of options.

2. **Handler** — `src/sase/main/ace_handler.py`
   - Read `args.tab` and forward it as a new `initial_tab` kwarg to `AceApp`.

3. **App constructor** — `src/sase/ace/tui/app.py`
   - Add `initial_tab: TabName = "agents"` parameter to `AceApp.__init__`.
   - Pass through to `_init_app_state(... initial_tab=initial_tab)`.

4. **State init** — `src/sase/ace/tui/actions/_state_init.py`
   - Accept `initial_tab` and set `self.current_tab = initial_tab` during init.
   - This runs before `on_mount`, so the reactive starts on the requested tab and downstream wiring (footer, info
     panels) renders the correct tab on first paint.

5. **Remove the startup auto-switch** — `src/sase/ace/tui/actions/startup.py`
   - Delete the `if not self.changespecs: ...` block (lines 177-181).

6. **Delete the now-orphaned fallback** — `src/sase/ace/tui/actions/changespec/_query.py`
   - Remove `_try_startup_fallback_async`. The only caller was the block above; no other code references the method
     (verified via grep — remaining hits are tests and docs).

7. **Tests**
   - Update `tests/ace/tui/test_startup_stopwatch_live_update.py` and
     `tests/ace/tui/test_changespec_query_corpus_routing.py`, which currently reference `_try_startup_fallback_async`.
     Either rewrite to cover the new `initial_tab` path or remove the assertions that depend on the deleted fallback
     (decision deferred to implementation; the simplest fix is to drop the now-irrelevant assertions and add a dedicated
     test below).
   - Add `tests/main/test_ace_handler.py` cases (or new file) verifying:
     - `--tab` is forwarded as the `initial_tab` kwarg.
     - Each of the three values round-trips.
     - Omitting `--tab` produces `initial_tab="agents"`.
     - An invalid `--tab` value causes argparse to exit with non-zero.
   - Add a lightweight `AceApp` construction test that asserts `app.current_tab == initial_tab` immediately after init
     for each of the three tab names. (Real `on_mount` does not need to run.)

8. **Docs** — `docs/ace.md`
   - Insert `--tab` row in the CLI Options table (alphabetical: between `--restart-axe` and `--vcs-provider` if we sort
     by long name) with description: `Tab to focus on startup (changespecs, agents, axe; default: agents)`.
   - No `?` help-modal update is needed — that modal documents keybindings, not CLI flags.

9. **Sanity** — run `just check` from the workspace once changes are in.

## Decisions worth flagging in review

- **Removing the saved-query fallback entirely.** The current saved-query fallback existed only to avoid the auto-switch
  to Agents. With explicit `--tab`, the user is responsible for tab choice and for the query, so the fallback's purpose
  disappears. Removing `_try_startup_fallback_async` outright is the simplest and clearest change, but it is a behavior
  change beyond strict tab-focus removal. Flag for confirmation.
- **Default value `agents`.** Per the user's request. Worth noting this means fresh installs without any saved CL query
  no longer drop the user onto an empty CLs tab — a small but visible UX shift.
- **Short flag.** Proposed `-t` for `--tab`. The remaining unused short letters in the existing ace parser are `-t`,
  `-T`, `-i`, etc. `-t` reads naturally. Drop the short flag entirely if you'd rather keep the surface terse.

## Files touched

- `src/sase/main/parser_ace.py`
- `src/sase/main/ace_handler.py`
- `src/sase/ace/tui/app.py`
- `src/sase/ace/tui/actions/_state_init.py`
- `src/sase/ace/tui/actions/startup.py`
- `src/sase/ace/tui/actions/changespec/_query.py`
- `tests/main/test_ace_handler.py` (and possibly new test file)
- `tests/ace/tui/test_startup_stopwatch_live_update.py`
- `tests/ace/tui/test_changespec_query_corpus_routing.py`
- `docs/ace.md`
