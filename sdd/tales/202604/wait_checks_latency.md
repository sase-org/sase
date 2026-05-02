---
create_time: 2026-04-07 22:56:27
status: done
prompt: sdd/prompts/202604/wait_checks_latency.md
---

# Plan: Fix wait_checks latency by moving it to a dedicated lumberjack

## Problem

When an agent with `%w:sase-d.1` is waiting for `sase-d.1` to complete, the dependency resolution takes ~2+ minutes even
though `sase-d.1` has already written `done.json`. The user observed `sase-d.2` stuck in WAITING state for over a minute
after `sase-d.1` finished.

## Root Cause

The `wait_checks` chop is the **8th (last)** of 8 sequential chops in the `hooks` lumberjack
(`src/sase/default_config.yml:178`). Despite having a 1-second interval, each cycle takes ~142 seconds on average
(19,157s uptime / 135 cycles), primarily due to `mentor_checks` processing hundreds of agent profiles. Since chops run
sequentially within a lumberjack cycle, `wait_checks` is starved - it only executes every ~2.4 minutes.

Evidence:

- `sase-d.1` wrote `done.json` at 22:40:19 ET
- `sase-d.2` wait resolved at 22:42:04 ET (~105 second delay)
- `hooks` lumberjack: 135 cycles in 19,157 seconds = 141.9s per cycle

## Fix

Move `wait_checks` out of the `hooks` lumberjack into a new dedicated `waits` lumberjack with a 2-second interval. This
is a config-only change.

### Step 1: Update `src/sase/default_config.yml`

- Remove `wait_checks` entry from `hooks.chops` list (line 178-179)
- Add new `waits` lumberjack after `housekeeping`:

```yaml
waits:
  interval: 2
  chops:
    - name: wait_checks
      description: "Resolve agent wait dependencies and write ready.json when satisfied"
```

No code changes needed - the lumberjack infrastructure and `wait_checks` chop script already support this. The
orchestrator auto-spawns all configured lumberjacks as separate processes.
