---
create_time: 2026-05-01 12:47:17
status: done
prompt: sdd/prompts/202605/bead_work_naming_timeout.md
---
# Fix `sase bead work` Multi-Prompt Naming Timeouts

## Problem

`sase bead work <epic_id>` can pause for 30 seconds between phase launches and print:

```text
Agent 1/10 naming timed out, continuing
```

For a 10-agent epic, the parent CLI can spend several minutes in naming waits even though the child agents may have
already started and written their metadata. This makes the command look flaky and can interact badly with user-side
timeouts or retries.

## Root Cause

The timeout is caused by an artifacts project mismatch in the multi-prompt launcher.

The launch path is:

1. `sase bead work` renders a `---`-separated multi-prompt in `src/sase/bead/work.py`.
2. `handle_bead_work()` calls `launch_agent_from_cwd(query)` in `src/sase/bead/cli_work.py`.
3. `launch_agent_from_cwd()` normalizes bare multi-prompt segments to `#cd:~`.
4. `launch_multi_prompt_agents()` resolves each segment independently.
5. `#cd:~` segments are launched as home-mode agents, so the runner writes artifacts under:

   ```text
   ~/.sase/projects/home/artifacts/ace-run/<timestamp>/
   ```

6. After each segment, `_spawn_segments_into()` polls for `agent_meta.json` using the outer `project_name` captured from
   the original cwd, typically `sase`:

   ```python
   artifacts_dir = create_artifacts_directory(
       "ace-run",
       project_name=project_name,
       timestamp=last_timestamp,
   )
   agent_name = _wait_for_agent_naming(artifacts_dir)
   ```

   That polls:

   ```text
   ~/.sase/projects/sase/artifacts/ace-run/<timestamp>/agent_meta.json
   ```

   while the actual child wrote:

   ```text
   ~/.sase/projects/home/artifacts/ace-run/<timestamp>/agent_meta.json
   ```

## Evidence

For a recent failed/slow `sase-1r` launch, timestamp `20260501124456` had:

```text
~/.sase/projects/home/artifacts/ace-run/20260501124456/agent_meta.json
```

with:

```json
{
  "pid": 606670,
  "workspace_dir": "/home/bryan",
  "name": "sase-1r.1",
  "model": "gpt-5.5",
  "llm_provider": "codex",
  "approve": true
}
```

The paired directory:

```text
~/.sase/projects/sase/artifacts/ace-run/20260501124456/
```

was empty. That empty directory was created by the parent-side polling helper while looking in the wrong project.

## Implementation Plan

1. Fix the naming poll to use the project resolved for the segment that was actually spawned.
   - In `src/sase/agent/multi_prompt_launcher.py`, track the project name associated with the last spawned sub-prompt in
     the current segment.
   - Use that segment project name when computing the artifacts directory for `_wait_for_agent_naming()`.
   - This should use `segment_ctx.project_name`, or a value derived from the returned launch result if that becomes
     available in the local structure.

2. Prefer avoiding accidental empty artifact directories during polling.
   - Today `create_artifacts_directory()` is used as a path calculator, but it also creates directories.
   - The minimal fix can keep this behavior but point it at the correct project.
   - A better follow-up is to add a pure artifact-path helper or include `artifacts_dir` in `AgentLaunchResult`, then
     poll the exact launched path without side effects.

3. Add regression coverage for home-mode multi-prompt naming waits.
   - Add a test in `tests/test_cd_launch_resolution.py` or `tests/test_multi_prompt_launcher.py` where:
     - the outer launch project is `base` or `sase`;
     - bare segments default to `#cd:~`;
     - segment resolution produces `project_name="home"`;
     - the naming wait receives the home artifacts directory, not the original cwd project.
   - Assert `create_artifacts_directory(..., project_name="home", timestamp=<segment timestamp>)` for the inter-segment
     wait.

4. Add regression coverage for mixed project segments.
   - Use a two-segment launch where segment 1 is `#cd:<dir>` and segment 2 is a workspace/VCS segment, or vice versa.
   - Verify the inter-segment wait follows the immediately preceding segment's project context.

5. Confirm bead behavior.
   - Keep `sase bead work --dry-run` unchanged.
   - For live launch behavior, verify a synthetic bead-work multi-prompt containing explicit `%name` and `%w:<name>`
     does not wait against the wrong project.
   - Existing rollback behavior should remain unchanged because this fix is isolated to post-spawn naming observation.

## Validation

Run targeted tests first:

```bash
just install
pytest tests/test_multi_prompt_launcher.py tests/test_cd_launch_resolution.py tests/test_bead/test_cli_work.py
```

Then run the required repo check after code changes:

```bash
just check
```

## Expected Outcome

For normal `sase bead work` epics whose segments run through `#cd:~`, the CLI should stop spending 30 seconds per
segment in false naming timeouts. The parent should find the already-written `agent_meta.json` under the `home` project
and print the actual name promptly, or skip/complete the wait without creating empty artifact directories under the
wrong project.
