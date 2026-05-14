---
create_time: 2026-05-14 19:36:23
status: done
prompt: sdd/prompts/202605/agent_starting_refresh.md
---
## Problem

Agents can remain in `STARTING` on the Agents tab until the user presses `y`. The launch path and loader intentionally
show `STARTING` before the runner records `run_started_at` in `agent_meta.json`. The UI must refresh again when that
marker write lands.

## Root-Cause Hypothesis

The event-driven refresh path depends on `ArtifactWatcher` seeing artifact changes. Startup currently watches each
project's `artifacts/` directory shallowly plus the project directory. If a workflow directory such as
`artifacts/ace-run/` already exists before the TUI starts, inotify on `artifacts/` does not see later writes under
`artifacts/ace-run/<timestamp>/agent_meta.json`. Those missed marker writes leave the row at `STARTING` until a slow
sanity refresh or a manual `y`.

The fix must not replace this with frequent polling or a recursive historical tree walk at startup, because both would
harm performance.

## Plan

1. Add a targeted watcher-startup expansion for one level of existing workflow artifact directories under each watched
   `artifacts/` root, such as `ace-run`, `workflow-review`, or other workflow names.
2. Keep startup bounded: do not walk timestamp directories or historical marker trees. Watching the existing workflow
   directory is enough for inotify to see new timestamp child directories; the existing recursive add-on-create path
   will then watch the fresh timestamp directory and its marker writes.
3. Preserve current coalescing and dirty-flag behavior, so a burst of marker writes still schedules at most the existing
   coalesced refresh work.
4. Add a regression test covering the missed case: `artifacts/ace-run/` exists before watcher startup, then a new
   timestamp directory and `agent_meta.json` write should dispatch.
5. Keep the existing “no recursive startup walk” performance guard intact and strengthen it if necessary so the change
   cannot regress into a full historical scan.
6. Run the focused watcher/refresh tests, then run `just install` if needed and `just check` because code files changed.
