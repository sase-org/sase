---
create_time: 2026-07-02 10:00:44
status: done
prompt: sdd/prompts/202607/daemon_only_run.md
---
# Plan: Make Detached Launch the Only `sase run` Behavior (remove `-d|--daemon`)

## Background

`sase run` currently has two launch modes:

1. **Foreground (default)**: `run_query()` in `src/sase/main/query_handler/_query.py` executes the prompt in-process
   through `WorkflowExecutor`, blocking the shell, streaming output to the terminal, and hand-maintaining TUI visibility
   markers (`workflow_state.json`, `agent_meta.json`, `done.json`, workspace claims).
2. **Daemon (`-d|--daemon`)**: `run_query_daemon()` in `src/sase/main/query_handler/_daemon.py` calls
   `launch_agent_from_cwd()` — the exact same launch machinery the TUI uses — and returns immediately. The agent appears
   in the ACE Agents tab.

In practice the daemon mode is the only mode used. Foreground running (keeping a shell window open) runs against SASE's
philosophy. This plan makes the detached launch the default and **only** behavior of `sase run`, removes the
`-d|--daemon` flag, and deletes the now-dead foreground machinery.

## Current-State Survey (what routes where today)

`handle_run_special_cases()` (`src/sase/main/query_handler/special_cases.py`) strips `-d/--daemon` up front and then
routes:

| Invocation shape                                                      | Today (no flag)                                | Today (`-d`)         |
| --------------------------------------------------------------------- | ---------------------------------------------- | -------------------- |
| `sase run "<prompt>"`                                                 | foreground `run_query`                         | `run_query_daemon`   |
| `sase run` (editor) / `sase run .` (picker) / `sase run "#vcs:ref ."` | foreground `run_query`                         | `run_query_daemon`   |
| `sase run "#multi --- prompt"`, `%{...}` alt/multi-model              | auto-redirects to daemon with a notice         | `run_query_daemon`   |
| `sase run "#ref"` (exact xprompt/workflow ref)                        | in-process `execute_workflow` (foreground)     | `run_query_daemon`   |
| `sase run -r [HISTORY] "<q>"`                                         | foreground resume (`_resume.py` → `run_query`) | error (incompatible) |
| `sase run -l`                                                         | list chat history basenames                    | error (incompatible) |

`dispatch_query(prompt, daemon_mode=...)` is the shared foreground/daemon switch, also used by
`sase prompt run|edit|select` (`src/sase/prompt/cli_run.py`), which each expose their own `-d/--daemon` flag.

External callers found for `sase run -d` (must not silently break):

- chezmoi bin scripts `home/bin/executable_sase_chop_sase_fix_just` and `home/bin/executable_sase_chop_gh_actions_fix`
  invoke `["sase", "run", "-d", prompt]` from automated axe chops.
- The generated `sase_agents_status` skill (source: `src/sase/xprompts/skills/sase_agents_status.md`) instructs agents
  to relaunch with `sase run -d "..."`; deployed copies exist for every runtime via chezmoi.
- `sase-telegram` and `sase-github` plugins do **not** reference the flag (verified).
- No external callers of `sase run -r` or `sase run -l` were found.

## Design

### Behavior after this change

Every `sase run` launch shape routes through the detached launch path (current `run_query_daemon` →
`launch_agent_from_cwd`), exactly as if launched from the TUI:

- `sase run "<prompt>"`, editor compose, `.` picker, `#vcs:ref .` picker → detached agent(s).
- Exact `#ref` / `#!standalone` references → detached workflow run (this already is the `-d` behavior; the runner script
  handles xprompt expansion and anonymous-workflow flattening). The `#sync` → `#!sync` standalone deprecation warning
  and the invalid-`#!`-marker error keep firing at the CLI before launch.
- Multi-prompt (`---`), multi-model, and alt-split prompts fan out detached as they do today; the special "detected —
  launching N agents in daemon mode" redirect notices become obsolete and are removed.

### Decisions (flagging explicitly for plan review)

1. **`-d|--daemon` becomes a hidden, ignored back-compat shim (recommended)**: `handle_run_special_cases()` already
   strips the flag pre-argparse; keep a 3-line strip that prints a one-line stderr notice ("-d/--daemon is deprecated:
   detached launch is now the default") and otherwise behaves identically. This keeps the user's automated chezmoi chop
   scripts working until they are updated (follow-up below). The flag disappears from the parser, `--help`, and all
   docs. Alternative: hard-remove and let argparse error — rejected because scheduled automation would fail with no
   grace period. The shim is removable once the chezmoi scripts are updated.
2. **Remove `-r/--resume` and `-l/--list` entirely (recommended)**: both exist to serve the foreground resume flow.
   Resume capability is fully preserved — and already documented in `docs/llms.md` — via the `#fork` /
   `#fork_by_chat(path)` xprompts, which work through the detached path (e.g. `sase run "#fork(agent_name) follow-up"`).
   Chat transcripts are listed by the richer `sase chat list`. `_resume.py` dies with `run_query` either way, since it
   is foreground-only. Alternative if the flag should survive: reimplement `-r [HISTORY] "<q>"` as a thin rewrite to
   `#fork_by_chat(<resolved path>) <q>` + detached launch. Default is removal; say the word during review to keep the
   rewrite variant instead.
3. **`sase prompt run|edit|select` lose `-d/--daemon` with no shim**: they always launch detached now. These are
   interactive commands with no discovered automation callers.

### Naming: retire "daemon" vocabulary

With only one launch mode, the "daemon" name (which now collides conceptually with the axe daemon) goes away:

- Rename `src/sase/main/query_handler/_daemon.py` → `_launch.py`, and `run_query_daemon()` → `launch_query()`.
- `dispatch_query(prompt, daemon_mode=...)` is deleted; callers use `launch_query(prompt)` directly.
- Export `launch_query` from `sase.main.query_handler.__init__` in place of `dispatch_query`.

### Pre-launch guard worth carrying over

`run_query` has one useful pre-flight check the daemon path lacks: `missing_required_input_names()` fails fast with a
clear message when a prompt declares required (default-less) `input:` frontmatter that only the TUI's Input Collection
Modal could satisfy. Move this guard into `launch_query()` (CLI-side, **not** into `launch_agent_from_cwd`, which the
TUI also uses after collecting inputs) so the error still surfaces synchronously in the terminal instead of dying inside
the detached runner.

### Small polish while touching `launch_query`

`run_query_daemon` prints only the first PID even when a multi-prompt fans out several agents. Switch it to
`launch_agents_from_cwd()` and print one `Agent started (PID ...)` line per launched agent.

## Changes

### 1. CLI surface

- `src/sase/main/parser_commands.py` (`register_run_parser`): drop `-d/--daemon`, `-l/--list`, and `-r/--resume`; usage
  becomes `sase run [-h] [PROMPT]`. Rewrite help/description to say the prompt launches a detached background agent
  visible in the ACE Agents tab. Replace the `-d` epilog example with a flagless one and mention
  `#fork`/`sase chat list` where resume/list guidance used to live.
- `src/sase/main/parser_prompt.py`: remove the `-d/--daemon` argument from `prompt run`, `prompt edit`, and
  `prompt select` (note: `prompt prune -d/--dry-run` is unrelated — leave it).
- `src/sase/main/query_handler/special_cases.py`:
  - Keep stripping `-d`/`--daemon` (back-compat shim) but only to warn; there is no `daemon_mode` variable anymore.
  - Delete the `-l/--list` and `-r/--resume` branches and their daemon-incompatibility errors.
  - All `_run_query`/`dispatch_query` call sites → `launch_query`.
  - In the exact-`#ref` branch, delete the in-process `create_artifacts_directory` + `execute_workflow` fallback and
    always `launch_query(potential_query)` (keeping the standalone deprecation warning / invalid-marker error).
  - `run_parsed_prompt()`: drop the `daemon` attr read; dispatch via `launch_query`.
  - Unused imports (`create_artifacts_directory`, `list_chat_histories`, `handle_run_with_resume`, `run_query`) go.
- `src/sase/prompt/cli_run.py`: drop the `daemon` parameter threading in `handle_prompt_run/edit/select` and
  `_replay_record`; dispatch through `launch_query`. Update the module docstring (no more "foreground/daemon").

### 2. Delete dead foreground machinery

- Delete `src/sase/main/query_handler/_query.py` (`run_query`, `_resolve_vcs_cwd`) — its TUI-visibility bookkeeping,
  workspace claiming, and VCS-cwd resolution all have daemon-path equivalents in `sase/agent/launch_cwd*` and the runner
  scripts (independently tested by `tests/test_cd_launch_from_cwd*.py` and friends).
- Delete `src/sase/main/query_handler/_resume.py` (`handle_run_with_resume`).
- Rename `_daemon.py` → `_launch.py` / `launch_query()` per Design; add the required-inputs guard and per-agent PID
  output there.
- `_editor.py`, `_embedded_workflows.py`, `_standalone_steps.py` stay (used by editor/picker flows, mentor/crs/fix
  hooks, and the xprompt handler).

### 3. Docs

- `docs/cli.md`: rewrite the "`sase run` can run in the foreground, launch detached background agents with `--daemon`,
  resume previous conversations…" paragraph — `sase run` always launches detached background agents; ACE uses the same
  machinery.
- `docs/configuration.md`: `sase run` flag table — remove the `-d/--daemon`, `-l/--list`, `-r/--resume` rows; keep
  `[query]`; adjust the trailing prose ("launched as sequential daemon agents" → detached background agents).
- `docs/prompt.md`: update the shared-machinery paragraph (drop "foreground, `--daemon`") and the two `-d` examples
  (`sase prompt run … -d`, `sase prompt select … -e -d`).
- `docs/llms.md`: "as if `sase run -d` had been invoked" (×2) → "as if `sase run` had been invoked"; rewrite the "Resume
  Support" section around `#fork`/`#fork_by_chat` (removing `--resume` as the entry point).
- Comment/docstring sweep for the same phrase: `src/sase/llm_provider/retry_config.py`,
  `src/sase/axe/run_agent_exec_retry.py`, `src/sase/axe/run_agent_retry_spawn.py`, `src/sase/agent/repeat_launcher.py`
  ("the CLI `sase run` daemon path" → "the CLI `sase run` path").
- Do not touch CHANGELOG.md (generated) or historical sdd/ plan files.

### 4. Generated skill source + regeneration

- `src/sase/xprompts/skills/sase_agents_status.md`: change `sase run -d "$rewritten_prompt"` →
  `sase run "$rewritten_prompt"`.
- Then run `sase skill init --force` and `chezmoi apply` to regenerate and deploy the per-runtime `SKILL.md` copies
  (they are generated files; never hand-edit the deployed copies).

### 5. Tests

Update (behavior now always-detached):

- `tests/test_special_cases.py`: retarget `run_query` mocks to the launch function; the standalone-workflow tests
  (`#!sync`, legacy `#sync` warning, invalid `#!` marker) now assert detached routing + unchanged warnings/errors. Add a
  test that `-d` is stripped, warned about, and still launches.
- `tests/test_multi_prompt_e2e.py`: the auto-daemon-redirect tests collapse (everything routes detached — keep them as
  routing assertions); delete the resume+multi-prompt error test with `-r`.
- `tests/test_partial_launch_cleanup.py`: follow the `_daemon` → `_launch` rename.
- `tests/prompt_command/test_parser.py` / `tests/prompt_command/test_replay.py`: drop `-d`/`daemon=` cases; replay tests
  assert the launch function is called (prefix/edit behavior unchanged).
- `tests/main/test_parser_command_help.py`: new usage line (`sase run [-h] [PROMPT]`) and flagless epilog example.
- `tests/test_prompt_inputs.py` (run_query missing-inputs test): retarget to the guard's new home in `launch_query`.
- `tests/perf/bench_phase7_e2e.py`: swap the `run_query` import-cost probes to the new `_launch` module so the
  dispatch-import benchmark keeps measuring the real path.

Delete (foreground-implementation-specific; daemon-path equivalents already exist):

- `tests/test_run_workflow_visibility.py`: only the `run_query`-driven tests (initial `workflow_state.json`, inline
  marker index refresh, failed-claim cleanup); the loader/executor tests in that file stay.
- `tests/test_run_cwd_no_project_creation.py`: the two `run_query` tests; the two daemon-path tests stay.
- `tests/test_cd_vcs_cwd_resolution.py` and `tests/test_xprompt_processor_workflow_vcs.py`: exercise the deleted
  `_resolve_vcs_cwd`; launch-path VCS resolution keeps its own coverage in `tests/test_cd_launch_from_cwd*.py`.

### 6. Follow-ups outside this repo (coordinated, not blocking)

- chezmoi: update `home/bin/executable_sase_chop_sase_fix_just` and `home/bin/executable_sase_chop_gh_actions_fix` to
  drop `-d` from their `sase run` invocations. Once done (plus skill redeploy), the back-compat shim from Decision 1 can
  be removed in a later change.

## Out of Scope

- No `sase-core` (Rust) changes: launch dispatch is CLI-side Python glue; the shared launch machinery
  (`launch_agent_from_cwd`) is untouched.
- No changes to `#fork`/`#fork_by_chat`, `sase chat`, or the prompt-history store.
- No TUI changes.

## Verification

1. `just install`, then `just check` (lint, mypy, tests, `sase validate`).
2. Targeted suites:
   `pytest tests/test_special_cases.py tests/test_multi_prompt_e2e.py tests/prompt_command tests/main/test_parser_command_help.py tests/test_partial_launch_cleanup.py tests/test_prompt_inputs.py`.
3. Smoke: `sase run --help` (no `-d/-l/-r`; new examples), `sase run -d "noop prompt"` prints the deprecation notice and
   still launches, `sase run "<prompt>"` launches detached and appears in the ACE Agents tab, and
   `sase run "#fork(<agent>) <follow-up>"` resumes detached.
4. Since this is a breaking CLI change, land it as a `feat!:`/BREAKING CHANGE commit so release-please versions it
   correctly.
