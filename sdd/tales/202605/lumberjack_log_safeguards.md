---
create_time: 2026-05-13 10:08:47
status: done
prompt: sdd/prompts/202605/lumberjack_log_safeguards.md
---
# Plan: Remove Runaway Logs and Cap Lumberjack Logging

## Context

The immediate disk pressure comes from three very large log files:

- `/var/log/syslog` at about 153 GiB
- `/var/log/user.log` at about 153 GiB
- `/home/bryan/.sase/axe/logs/lumberjack-hooks.log` at about 85 GiB

Additional SASE lumberjack logs are not root-cause scale, but are large enough to clean with the same pass:

- `/home/bryan/.sase/axe/lumberjacks/hooks/logs/output.log` at about 343 MiB
- `/home/bryan/.sase/axe/logs/lumberjack-checks.log` at about 172 MiB
- `/home/bryan/.sase/axe/lumberjacks/checks/logs/output.log` at about 170 MiB

`gvfsd-trash` and axe were reported stopped by the user, but `rsyslogd` still has the two `/var/log` files open. The
cleanup must release open file descriptors, not just unlink directory entries.

The SASE-specific failure mode is unbounded aggregate lumberjack logging. `Lumberjack._log()` appends to the per-
lumberjack aggregate log with no rotation or byte cap. The hooks lumberjack runs every 5 seconds and several scheduler
paths emit low-value per-ChangeSpec diagnostic lines, especially mentor matching lines. With thousands of ChangeSpecs,
that becomes large per-cycle output multiplied by a short interval.

## Immediate Cleanup

1. Delete the confirmed huge system logs:
   - `sudo rm -f /var/log/syslog /var/log/user.log`
2. Restart or signal `rsyslogd` so it closes deleted inodes and recreates fresh log files as needed:
   - Prefer `sudo systemctl restart rsyslog`
   - Fallback to `sudo service rsyslog restart`
   - Fallback to `sudo kill -HUP $(pidof rsyslogd)`
3. Delete the oversized SASE aggregate lumberjack logs:
   - `/home/bryan/.sase/axe/logs/lumberjack-hooks.log`
   - `/home/bryan/.sase/axe/logs/lumberjack-checks.log`
   - `/home/bryan/.sase/axe/lumberjacks/hooks/logs/output.log`
   - `/home/bryan/.sase/axe/lumberjacks/checks/logs/output.log`
4. Verify:
   - `find /var/log -maxdepth 2 -type f -size +1G`
   - `find /home/bryan/.sase/axe -type f -size +100M`
   - `sudo lsof +L1` filtered for deleted log files
   - `df -h /`

## Product Fixes

1. Add bounded append semantics for lumberjack aggregate logs.
   - Introduce a small helper in `src/sase/axe/_state_lumberjack.py`, for example `append_lumberjack_log(name, text)`.
   - Enforce a default maximum aggregate log size, for example 50 MiB per lumberjack.
   - When the file would exceed the cap, keep a bounded tail and prepend a short truncation marker.
   - Use binary tail reads and atomic replacement so multi-GiB existing files do not get read into memory.

2. Route `Lumberjack._flush_log_to_file()` through the bounded helper.
   - Keep the current Rich console capture behavior.
   - Change only the final append step so all current lumberjack log producers inherit the cap.

3. Cap orchestrator child stdout logs too.
   - `src/sase/axe/orchestrator.py` redirects each child to `~/.sase/axe/logs/lumberjack-{name}.log`.
   - That legacy/outer log path was the 85 GiB `lumberjack-hooks.log`.
   - Replace direct append file handles with a bounded writer strategy or redirect child output to the same bounded
     per-lumberjack log mechanism.
   - If direct streaming must remain, rotate/truncate before spawn and periodically on restart checks.

4. Reduce hot-loop mentor logging.
   - Remove or gate per-ChangeSpec dim lines such as:
     - `Phase 2: N mentor profile(s) loaded from config`
     - `Mentor matching: N profile(s) loaded for '<changespec>'`
     - `Mentor matching: 0 new profiles matched for '<changespec>'`
   - Keep logs for state changes and anomalies: profiles added, mentors started, runners killed, notifications sent,
     errors, and tick overruns.
   - Emit a per-cycle summary instead of one line per unchanged ChangeSpec.

5. Add configuration knobs with conservative defaults.
   - Add `axe.lumberjack_log_max_bytes` or per-lumberjack `max_log_bytes`.
   - Add `axe.verbose_lumberjack_diagnostics` defaulting to false for per-ChangeSpec debug chatter.
   - Update `src/sase/default_config.yml` and config parsing tests.

6. Add regression tests.
   - State helper test: appending beyond the cap leaves the file under the cap and preserves the newest content.
   - Lumberjack test: repeated `_log()` calls cannot grow the aggregate log beyond the configured/default cap.
   - Orchestrator test: child stdout log handling does not leave unbounded `lumberjack-{name}.log` files.
   - Mentor logging test: a no-op mentor check across many ChangeSpecs does not emit per-ChangeSpec "0 matched" lines.

## Validation

After implementation:

1. Run `just install` because this workspace may have stale dependencies.
2. Run focused tests for lumberjack state/config/tick/orchestrator/mentor logging.
3. Run `just check` before handing off, per repo instructions.
