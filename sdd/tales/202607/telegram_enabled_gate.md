---
create_time: 2026-07-03 14:02:57
status: wip
prompt: sdd/prompts/202607/telegram_enabled_gate.md
---
# Gate Telegram Chops on `~/.sase/telegram_is_enabled` + Move Chop Config to `sase.yml`

## Problem / Motivation

The `tg_inbound` and `tg_outbound` chops (provided by the `sase-telegram` plugin) are currently configured in the
chezmoi repo's `home/dot_config/sase/sase_athena.yml`, which — per `home/.chezmoiignore` — is only deployed on the
athena host. We want the telegram chop configuration to live in the global `home/dot_config/sase/sase.yml` (deployed to
**all** machines), with a per-machine opt-in flag file deciding whether the chops actually do any work:

- If `~/.sase/telegram_is_enabled` does **not** exist, both chops must exit quietly (no output) and quickly (no heavy
  imports, no network, no locks), with exit code 0.
- If the file exists, the chops behave exactly as they do today.

This makes the telegram lumberjack safe to configure globally: every machine runs the chop scripts on the lumberjack's
5-second interval, but only machines that have been explicitly enabled (currently just athena) talk to Telegram.

## Scope

Two repos change; the primary `sase` repo needs **no code changes**:

1. **`sase-telegram`** (linked repo — open with `sase workspace open -p sase-telegram -r "<reason>" <workspace_num>`):
   add the flag-file gate.
   - NOTE: If `sase workspace open` fails with
     `Primary workspace directory does not exist: ~/projects/github/sase-org/sase-telegram`, the primary clone is
     missing on this machine. Re-clone it
     (`git clone git@github.com:sase-org/sase-telegram.git ~/projects/github/sase-org/sase-telegram`) and retry, and
     mention the repair in your final summary.
2. **`chezmoi`** (linked repo at `~/.local/share/chezmoi`, workspace strategy `none` — edit it directly): move the
   telegram lumberjack block from `sase_athena.yml` to `sase.yml`.

## Part 1: Flag-file gate in `sase-telegram`

### How the chops are invoked (context)

The sase axe lumberjack resolves the chop names `tg_inbound`/`tg_outbound` to the console scripts
`sase_chop_tg_inbound`/`sase_chop_tg_outbound` (see `discover_chop_script()` in the sase repo's
`src/sase/axe/chop_script_runner.py`). Those console scripts are declared in sase-telegram's `pyproject.toml` and point
at the thin wrappers in `src/sase_telegram/scripts/__init__.py`:

```python
def inbound_main(*args: Any, **kwargs: Any) -> int:
    from sase_telegram.scripts.sase_tg_inbound import main
    return main(*args, **kwargs)
```

The wrappers already lazy-import the real entry-point modules, and `sase_telegram/__init__.py` is empty — so a gate
placed in the wrappers **before** the lazy import skips all heavy imports (`python-telegram-bot`, `sase.*`, etc.). This
is the "quickly" half of the requirement.

### Changes

1. **New helper module** `src/sase_telegram/enabled.py` (stdlib-only imports — keep it light):

   ```python
   """Machine-level enable flag for the sase-telegram chops."""

   from pathlib import Path


   def telegram_enabled_path() -> Path:
       """Return the opt-in flag path (computed at call time for testability)."""
       return Path.home() / ".sase" / "telegram_is_enabled"


   def is_telegram_enabled() -> bool:
       return telegram_enabled_path().exists()
   ```

   Compute the path inside a function rather than as a module-level constant so tests can monkeypatch `HOME` after
   import.

2. **Gate both wrappers** in `src/sase_telegram/scripts/__init__.py`:

   ```python
   def inbound_main(*args: Any, **kwargs: Any) -> int:
       from sase_telegram.enabled import is_telegram_enabled

       if not is_telegram_enabled():
           return 0
       from sase_telegram.scripts.sase_tg_inbound import main
       return main(*args, **kwargs)
   ```

   (Same for `outbound_main`.) Design points:
   - **Print nothing** on the disabled path. Other early-exit paths in these chops print a `tg_outbound: ... reason=...`
     summary line, but the requirement here is a _quiet_ exit — on a disabled machine this fires every ~5 seconds
     forever, and any output would be pure log noise.
   - **Exit code 0** so the lumberjack does not record failures.
   - Gate only the wrappers (the chop/console-script entry points), not the underlying `main()` functions. This keeps
     the existing `main()`-level tests untouched and keeps direct programmatic invocation (tests, debugging) working
     without the flag.

3. **Tests** (new file, e.g. `tests/test_enabled.py`):
   - `is_telegram_enabled()` false when the file is absent, true when present (point `HOME` at `tmp_path` via
     `monkeypatch.setenv("HOME", ...)`; on macOS also unset/patch as needed so `Path.home()` resolves to the temp dir).
   - `inbound_main()`/`outbound_main()` with the flag absent: return 0, produce no stdout (assert via `capsys`), and do
     **not** invoke the underlying `main` (monkeypatch `sase_telegram.scripts.sase_tg_inbound.main` /
     `...sase_tg_outbound.main` with a sentinel that fails the test if called — note the wrappers import lazily, so
     patch the module attribute, then call the wrapper).
   - With the flag present: wrapper delegates to the (patched) underlying `main` and returns its value.

4. **Docs**: `README.md`, `docs/inbound.md`, `docs/outbound.md` (and `docs/architecture.md` if it describes chop
   startup) should get a short note: the chops are no-ops unless `~/.sase/telegram_is_enabled` exists, and enabling a
   machine is `touch ~/.sase/telegram_is_enabled`.

5. Run the sase-telegram repo's `just check` (lint + tests) before finishing.

## Part 2: Move the telegram lumberjack config in chezmoi

In `~/.local/share/chezmoi/home/dot_config/sase/`:

1. **Delete** the entire `telegram:` lumberjack block from `sase_athena.yml` (the last block under `axe.lumberjacks`,
   containing `interval: 5` and the `tg_inbound`/`tg_outbound` chops with their
   `SASE_TELEGRAM_BOT_USERNAME`/`SASE_TELEGRAM_BOT_CHAT_ID` env vars). The remaining lumberjacks (`run_every`,
   `code_quality`, `refresh_docs`, `github_actions`) stay in `sase_athena.yml` unchanged.

2. **Add** the block verbatim to `sase.yml`, which currently has no `axe:` section — add one:

   ```yaml
   axe:
     lumberjacks:
       telegram:
         interval: 5
         chops:
           - name: tg_inbound
             description: "Process Telegram inline keyboard responses and text messages"
             env:
               SASE_TELEGRAM_BOT_USERNAME: sase_athena_bot
               SASE_TELEGRAM_BOT_CHAT_ID: "8990449281"
           - name: tg_outbound
             description: "Send unread notifications to Telegram"
             env:
               SASE_TELEGRAM_BOT_USERNAME: sase_athena_bot
               SASE_TELEGRAM_BOT_CHAT_ID: "8990449281"
   ```

   Move the block **wholesale** — do not split it (e.g. chop list in `sase.yml`, env overrides in `sase_athena.yml`).
   The sase config loader (`src/sase/config/core.py` in the sase repo) deep-merges `sase.yml` with every
   `~/.config/sase/sase_*.yml` overlay and **concatenates lists** by default, so a `telegram.chops` list left in both
   files would register each chop twice.

3. Commit both file edits in the chezmoi repo and apply them (`chezmoi apply` or the user's normal chezmoi workflow) so
   the live `~/.config/sase/` files on athena pick up the change.

## Rollout order (matters!)

1. **First**, create the flag on athena: `touch ~/.sase/telegram_is_enabled`. This is a no-op with today's code, and it
   guarantees telegram keeps working on athena the moment the gate lands. Do this as part of implementation.
2. **Then** land the sase-telegram gate change and get it released/installed on athena (the repo publishes to PyPI via
   release-please; athena updates via the normal SASE update flow).
3. **Last**, land + apply the chezmoi config move. If the config move were applied on another machine that has an _old_
   (ungated) sase-telegram installed, its chops would actually start talking to Telegram — landing the gate first avoids
   that window.

## Accepted consequences / out of scope

- On machines without the sase-telegram plugin installed, the globally-configured `tg_*` chops will show
  `status="missing"` in the chop inventory and `sase doctor`'s `configured_chop_scripts` / telegram env/pass checks may
  warn. That is pre-existing behavior for configured-but-uninstalled chops and is acceptable; fixing doctor noise is out
  of scope.
- The athena-specific bot identity env vars intentionally move into the global `sase.yml`; they are inert on machines
  where the flag file is absent.
- No changes to the primary `sase` repo or to `sase-core` (the gate is plugin-local chop behavior, not shared domain
  logic).

## Verification

- `just check` passes in the sase-telegram repo.
- Manual smoke test in the sase-telegram repo venv, with `HOME` pointed at a scratch dir (no flag file):
  `sase_chop_tg_outbound --dry-run` prints nothing and exits 0 immediately; after
  `touch $HOME/.sase/telegram_is_enabled` it prints the usual `tg_outbound: ... reason=...` summary.
- `python -c "from sase.config import load_merged_config; c = load_merged_config(); print(c['axe']['lumberjacks']['telegram'])"`
  (run on athena after `chezmoi apply`) shows exactly one `tg_inbound` and one `tg_outbound` chop — confirming the move
  introduced no duplicate list entries.
