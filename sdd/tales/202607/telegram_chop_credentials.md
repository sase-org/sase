---
create_time: 2026-07-04 13:57:46
status: wip
prompt: sdd/prompts/202607/telegram_chop_credentials.md
---
# Fix tg_inbound / tg_outbound Telegram Chop Errors (Credentials, Not Executables)

## Problem

The user is seeing AXE error-digest notifications about the `tg_inbound` and `tg_outbound` chop scripts "not existing"
on this machine, even after installing the `sase-telegram` plugin from the Updates tab of the SASE Admin Center. The
working hypothesis was that plugin installs are missing `uv tool install --with-executables-from`.

## Diagnosis (completed — evidence below)

The hypothesis is **disproved**, and the plugin install from the Updates tab **worked correctly**. There are two
distinct error populations that look alike in the digests:

### 1. The literal "Chop script not found: tg_inbound / tg_outbound" errors are stale

- On 2026-07-03 the telegram lumberjack config was moved from the athena-only overlay into the global
  `~/.config/sase/sase.yml` (agent commit "feat: gate telegram chops behind ~/.sase/telegram_is_enabled flag"). From
  that moment this machine's AXE started scheduling `tg_inbound`/`tg_outbound`.
- The `sase-telegram` plugin install completed at **2026-07-03 14:15:37** (uv receipt + venv script mtimes). The only
  "Chop script not found" errors on record are from **14:15:13–14:15:14** — the short window when the chops were
  configured but the plugin was not yet installed.
- Since the install completed there are **zero** "not found" occurrences in `~/.sase/axe/recent_errors.json`, the
  telegram lumberjack log, or any later error digest.

### 2. `--with-executables-from` is not needed for chops

- `uv tool install` exposes only the primary package's entrypoints on `~/.local/bin`, so
  `sase_chop_tg_inbound`/`sase_chop_tg_outbound` live only inside the tool venv (`~/.local/share/uv/tools/sase/bin/`).
  This is by design.
- Chop resolution (`src/sase/axe/chop_script_runner.py::discover_chop_script`) explicitly falls back to the bin
  directory **beside the running Python interpreter** before trying `$PATH`. Since AXE runs from the sase tool venv, the
  tg chops resolve fine — `sase axe chop doctor` currently reports all 15 configured chops as OK, with the tg chops
  resolved to the tool venv paths (source `python_bin`).
- This venv-internal discovery is the documented packaging contract
  (`sdd/research/202605/preferred_plugins_chops_install_strategy.md`). No change to the uv install command shape is
  needed, and none is proposed.

### 3. The _ongoing_ errors are a credentials crash-loop

- `~/.sase/telegram_is_enabled` exists on this machine (created 2026-07-03 14:03), so the chops do real work. (The
  installed `sase-telegram==0.2.0` predates the enable-flag gating anyway — the gating commit is at repo HEAD but
  unreleased.)
- `sase_telegram/credentials.py::get_bot_token()` hard-requires the `pass` CLI (`pass show telegram_sase_bot_token`).
  **`pass` is not installed on this machine**, so every `tg_inbound` run (every ~13s) dies with
  `FileNotFoundError: [Errno 2] No such file or directory: 'pass'` → "exit code 1" → hourly error digests with 100
  errors each.
- `sase axe chop doctor` already warns about this ("pass was not found") but only as a WARN, and it also emits a _false_
  WARN that `SASE_TELEGRAM_BOT_CHAT_ID` / `SASE_TELEGRAM_BOT_USERNAME` are missing — the doctor checks `os.environ`,
  while the chops actually receive those variables from per-chop `env:` blocks in `sase.yml` (which are correctly
  configured).

**Root cause:** this machine opted into Telegram (flag file present, plugin installed, lumberjack configured) but has no
way to obtain the bot token: `pass` is not installed and there is no alternative token source. The generic "exit code 1"
digests bury the actionable error, and the one truly matching "not found" digest was stale — together they made it look
like an install/executables problem.

## Fix Plan

### Part A — sase-telegram repo: robust, flexible credential lookup

1. Extend `src/sase_telegram/credentials.py::get_bot_token()` to try token sources in order:
   1. `SASE_TELEGRAM_BOT_TOKEN` environment variable (works with per-chop `env:` config, same as the chat-id/username
      vars);
   2. token file `~/.sase/telegram_bot_token` (strip whitespace; warn or refuse if group/other-readable);
   3. existing `pass show telegram_sase_bot_token` (keep as-is for machines that use pass, e.g. athena).
2. When every source fails (including `pass` binary missing — catch `FileNotFoundError` and `CalledProcessError`), raise
   a single-line, actionable error naming all three options instead of a raw traceback, and have the chop entry wrappers
   (`scripts/__init__.py`) print it to stderr and exit 1 cleanly. The chop must still fail (the machine opted in, so
   silence would hide misconfiguration), but the digest line should read like "Telegram bot token unavailable: install
   pass / set SASE_TELEGRAM_BOT_TOKEN / create ~/.sase/telegram_bot_token", not a subprocess traceback.
3. Tests for the source order, the permissions check, and the clean-failure path; README/docs update for the new token
   sources.

### Part B — sase repo: make chop doctor tell the truth about Telegram

In `src/sase/axe/chop_doctor.py` (tests in `tests/test_axe_chop_doctor.py`):

1. **Fix the env false positive:** treat a required `SASE_TELEGRAM_*` variable as satisfied when any configured telegram
   chop provides it via its `env:` mapping (available on the parsed `ChopConfig.env`; plumb it through
   `chop_inventory.ConfiguredChopRecord` as needed), not just when it is in `os.environ`.
2. **Check token availability, not just `pass`:** replace the pass-only check with a "bot token source" check mirroring
   Part A's chain (env var — including per-chop config env —, token file, `pass` binary).
3. **Escalate severity when it is a real outage:** if `~/.sase/telegram_is_enabled` exists AND telegram chops are
   configured AND no token source is available → ERROR (this is exactly the current crash-loop); otherwise keep WARN/OK.
   Next-step text lists the three token options from Part A.

### Part C — release and machine remediation (rollout)

1. Release `sase-telegram` (release-please): next release ships both the already-merged enable-flag gating and Part A.
   Then upgrade the plugin on affected machines via the Updates tab.
2. On this machine, to actually stop the errors, pick one (user decision — see Open Questions):
   - **Enable properly:** provision the bot token via any Part A source (e.g. copy the token from athena's pass store
     into `~/.sase/telegram_bot_token`, chmod 600 — no need to install pass/gpg), or
   - **Opt out:** `rm ~/.sase/telegram_is_enabled` (effective once the gated release from C1 is installed; the currently
     installed 0.2.0 ignores the flag).
3. Verify: `sase axe chop doctor` goes green (or ERROR with the new actionable message if the token is still missing),
   `~/.sase/axe/recent_errors.json` stops accumulating tg_inbound errors, and a test notification round-trips when
   enabled.

## Open Questions

1. Should this machine actually run the Telegram chops? `tg_inbound` polls the bot's `getUpdates` API; if athena (which
   owns `sase_athena_bot` and the pass store) is also polling, two inbound pollers will compete for updates (offset
   contention) and messages will be processed by whichever machine polls first. If athena is the intended Telegram host,
   the right fix here is C2's opt-out path.
2. Token-file location/name (`~/.sase/telegram_bot_token`) — happy to adjust to an existing secrets convention if one is
   preferred.

## Out of Scope

- No change to the uv install command shape (`--with-executables-from` is unnecessary for chops; plugin chop scripts are
  intentionally resolved from inside the tool venv).
- AXE error-digest rate limiting/dedup for repeated identical failures (would reduce noise from any future crash-loop,
  but is a separate concern).
