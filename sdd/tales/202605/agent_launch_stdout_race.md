---
create_time: 2026-05-08 13:38:12
status: done
prompt: sdd/prompts/202605/agent_launch_stdout_race.md
---
# Plan: Fix Agent Launch Output Test Race

## Context

GitHub Actions is failing in:

`tests/test_core_agent_launch_wire.py::test_spawn_prepared_agent_process_redirects_output_and_env`

The observed output file contains only:

```text
stderr-line
```

while the test expects both `env-ok` from stdout and `stderr-line` from stderr. The test program prints `env-ok` to
stdout first, then prints `stderr-line` to stderr. Because stdout is redirected to a file, Python may buffer stdout,
while stderr is unbuffered or flushed earlier. The helper `_wait_for_output(..., "stderr-line")` returns as soon as
stderr appears, so the assertion can read the file before stdout has been flushed by the child process. That makes the
CI failure consistent with a test race rather than evidence that environment propagation or output redirection is
broken.

## Goals

- Diagnose whether this is a flaky test synchronization issue or an actual Rust-backed launcher bug.
- Fix the test so it waits for the subprocess output contract it asserts.
- Preserve the production launch behavior unless investigation shows the launcher itself is faulty.
- Add focused coverage that prevents this race from returning.

## Implementation Plan

1. Refresh the local editable environment with `just install` if needed so pytest imports match the repository.
2. Re-run the single failing test locally and, if useful, a small repeat loop to characterize the race.
3. Update the test synchronization in `tests/test_core_agent_launch_wire.py` so it waits for both expected output
   markers before asserting. The most direct fix is to replace the single-substring wait with a helper that waits until
   all required substrings are present.
4. Keep the child command representative of the production contract: stdout and stderr both redirected into the same
   output file, and custom env passed into the child.
5. Run the targeted test file or at least the failing test after the change.
6. Because source files will have changed in this repo, run `just check` before the final response, per repo
   instructions.

## Expected Root Cause

The failing assertion is caused by `_wait_for_output` returning on the stderr marker before buffered stdout is visible
in the redirected output file. The launcher likely did pass the environment correctly; the test read the output file too
early.

## Risk

Low. The planned change is test-only and narrows synchronization to the exact behavior under assertion. It should reduce
CI flakiness without masking real failures: if either stdout env propagation or stderr redirection is broken, the helper
will time out and the assertion will still show the collected output.
