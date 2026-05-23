---
create_time: 2026-05-23 12:03:29
status: done
prompt: sdd/prompts/202605/validate_command.md
---
# Plan: Add `sase validate`

## Goal

Add a top-level `sase validate` command that runs the existing initialization and SDD checks:

- `sase init --check`
- `sase sdd validate`

The command should run both checks every time, report which checks passed or failed, surface the child command output
for failures, and exit nonzero if either check fails. Successful output should be concise enough for humans and for
`just lint`.

## Technical Approach

1. Add a new top-level parser entry for `validate`.
   - Keep the command in the same argparse registration flow as the rest of the CLI.
   - Dispatch it from `src/sase/main/entry.py` alongside the other top-level commands.

2. Add a small validate handler.
   - Run the two child commands as CLI subprocesses, using the current Python interpreter with `python -m sase` so the
     command works from editable installs and tests.
   - Capture stdout/stderr from each child command.
   - Always run both checks even if the first one fails.
   - Print a compact status block such as:

     ```text
     SASE validation
       ok     init --check
       fail   sdd validate
     ```

   - Suppress child command output when a check passes.
   - For failed checks, print a short failure header and the captured output so the user can see the actionable error.
   - Return exit code `0` only when both checks pass; otherwise return `1`.

3. Replace the Justfile target.
   - Rename the public target from `sdd-validate` to `validate`.
   - Make `validate` run `{{ venv_bin }}/sase validate`.
   - Update `just lint` to call `just validate`.
   - Update `just check`'s silent lint stage to call `just validate` and label it as SASE validation rather than
     SDD-only validation.

4. Add focused tests.
   - Parser test for `sase validate`.
   - Handler tests covering:
     - both child checks passing;
     - one or both checks failing while both are still executed;
     - captured child stdout/stderr is only shown for failures.
   - Entry dispatch test if needed to prevent the new parser from becoming disconnected from `main()`.

5. Verify.
   - Run targeted pytest for the new/updated CLI tests.
   - Run formatting/linting for changed Python files if needed.
   - Because this repo requires it after file changes, run `just install` and then `just check` before reporting
     completion, unless blocked by an environment issue.
