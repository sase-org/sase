---
create_time: 2026-06-01 08:28:22
status: done
prompt: sdd/prompts/202606/memory_episodes_chop_project_root_1.md
---
# Fix memory_episodes Chop Project Targeting

## Context

The `memory_episodes` chop is configured in the chezmoi-managed Athena config at
`/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` under `axe.lumberjacks.memory`. The configured
chop has no explicit project or repo-root inputs.

Scheduled chop history shows the chop is running successfully as a process, but its output is:

```text
memory_episodes: status=idle project=.sase built=0 changed=0 checkpoint=-
```

That means v2 episode generation is not currently being driven for the real `sase` project by this chop. The script
entry point `sase_chop_memory_episodes` derives both `project` and `repo_root` from `Path.cwd()`. Script chops are
intentionally executed from the lumberjack state directory, so this fallback resolves to the internal `.sase` area
instead of the SASE repository. Existing `sase` v2 episodes in `~/.sase/projects/sase/episodes` prove that the v2
builder can create episodes, but the configured Athena chop has not advanced `sase` episode state recently and is
silently scanning the wrong target.

There are completed `sase` agent markers newer than the latest stored `sase` episode files, so after the fix the builder
should find real work instead of reporting idle for `.sase`.

## Plan

1. Make the chop script explicit about its target project and source repository.
   - Add environment-backed inputs to `src/sase/scripts/sase_chop_memory_episodes.py`, likely
     `SASE_MEMORY_EPISODES_PROJECT` and `SASE_MEMORY_EPISODES_REPO_ROOT`.
   - Keep `-p|--project` as the highest-priority project override for manual use.
   - Add a CLI/env repo-root override, with `Path.cwd()` only as a manual fallback.
   - Preserve current output shape, but include enough target information to diagnose future misconfiguration.

2. Update the Athena chezmoi config so the scheduled chop targets `sase` deliberately.
   - In `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`, add chop `env` values for:
     - `SASE_MEMORY_EPISODES_PROJECT: "sase"`
     - `SASE_MEMORY_EPISODES_REPO_ROOT: "/home/bryan/projects/github/sase-org/sase"`
   - Avoid changing unrelated lumberjack cadence or other chops.

3. Add regression coverage.
   - Add a focused unit test for the chop script that simulates script-chop execution from a non-repo state directory.
   - Assert the script passes the env-configured project and repo root into `run_episode_auto_build`.
   - Add a fallback test for manual invocation from a repo cwd if the existing code shape makes it cheap.

4. Validate behavior without creating accidental episode state first.
   - Run targeted tests for the new chop-script behavior and existing auto-builder tests.
   - Run `just check` after SASE repo changes, per project instructions.
   - Use a small dry-run or manually invoked chop run only after the code/config fix is in place, and verify it reports
     `project=sase` rather than `project=.sase`.

5. If validation confirms the fixed target, optionally run one real `memory_episodes` chop cycle to catch up the `sase`
   project backlog.
   - This step writes episode state, so do it only after the dry-run output proves the target project/root are correct.
   - Confirm `sase memory episodes status -p sase --json` shows a real checkpoint/metrics update and recent v2 episodes.
