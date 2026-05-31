---
create_time: 2026-05-31 08:47:46
status: done
prompt: sdd/prompts/202605/fix_running_agents_tests.md
---
# Fix `just test` Running Agent Snapshot Failures

## Context

`tests/test_running_agents_snapshot.py` expects `list_running_agents()` and `list_all_agents()` to report three active
fixture agents when `sase.ace.hooks.processes.is_process_running` is patched to return `True`. In this workspace, only
the retried child is reported.

The snapshot scan itself returns all expected `ace-run` records. The missing rows are filtered by
`sase.agent.names._common.is_process_alive()`: after the patched liveness check says the PID is alive, the PID-reuse
guard reads `/proc/<pid>/cmdline` and rejects processes whose command line does not look like SASE/Python. The synthetic
fixture PIDs `11111` and `22222` currently belong to real non-SASE processes on this machine, while `33333` does not
exist, so the test outcome depends on host process state.

## Plan

1. Keep production liveness behavior intact. The PID-reuse guard is useful behavior and should not be weakened to make
   tests pass.

2. Make the affected running-agent snapshot tests deterministic by extending their liveness patch to cover the
   `/proc/<pid>/cmdline` guard. For tests that model live agents, return a SASE/Python-like command line for proc
   cmdline reads while preserving normal `Path.read_bytes()` behavior for any other path.

3. Reuse a small local context manager in `tests/test_running_agents_snapshot.py` so each test declares whether fixture
   processes are alive or dead without repeating patch details.

4. Re-run the targeted test module through the repo venv, then run `just check` as required after repository file
   changes.

## Expected Outcome

The snapshot tests will no longer depend on whether arbitrary fixture PIDs are currently assigned on the host.
`just test` should stop failing on the three reported assertions while preserving the production PID-recycling guard.
