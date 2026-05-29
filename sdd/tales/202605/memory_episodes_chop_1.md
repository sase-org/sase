---
create_time: 2026-05-29 09:36:57
status: done
prompt: sdd/prompts/202605/memory_episodes_chop_1.md
---
# Plan: Configure Athena memory_episodes chop

## Context

The chezmoi source is `/home/bryan/.local/share/chezmoi/home`, and the target file is `dot_config/sase/sase_athena.yml`.

SASE AXE config uses `axe.lumberjacks.<name>` entries with:

- `interval`: the lumberjack tick frequency in seconds.
- `chop_timeout`: optional default timeout for script chops.
- `chops`: configured chop names.
- per-chop `run_every`: a duration string parsed as seconds, minutes, or hours.

Script chops are discovered as executables named `sase_chop_<chop name>`. The memory episode script entry point is
`sase_chop_memory_episodes`, so the configured chop name should be `memory_episodes`.

The memory episodes design note recommends this opt-in scheduled script chop:

```yaml
axe:
  lumberjacks:
    memory:
      interval: 300
      chop_timeout: "10m"
      chops:
        - name: memory_episodes
          description: "Build private connected memory episodes from completed agents"
          run_every: "15m"
```

## Implementation

1. Add a new `memory` lumberjack under `axe.lumberjacks` in
   `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`.
2. Use `interval: 300` so the lumberjack wakes every five minutes.
3. Use `run_every: "15m"` so the `memory_episodes` chop runs at most once every fifteen minutes.
4. Set `chop_timeout: "10m"` to match the design note and prevent a stuck build from lingering indefinitely.
5. Keep this as a script chop by omitting `agent`; AXE will resolve `memory_episodes` to `sase_chop_memory_episodes`.
6. Preserve existing Athena lumberjacks and ordering, placing `memory` near other periodic background maintenance.

## Verification

1. Parse `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` with Python's YAML loader to catch
   syntax errors.
2. Load the file through `sase.axe.config._parse_lumberjacks` in the local SASE checkout and assert:
   - `memory` exists.
   - `memory.interval == 300`.
   - `memory.chop_timeout == 600`.
   - the only new chop is `memory_episodes`.
   - `memory_episodes.run_every == 900`.
3. Run a script-discovery check for `memory_episodes` in the current SASE environment if possible. If the entry point is
   missing because the workspace has not been installed, report that clearly rather than changing unrelated setup.
4. Show the chezmoi diff for the target file.

## Non-Goals

- Do not modify SASE memory files.
- Do not change SASE default config.
- Do not start or restart the AXE daemon unless explicitly requested.
- Do not commit changes unless explicitly requested.
