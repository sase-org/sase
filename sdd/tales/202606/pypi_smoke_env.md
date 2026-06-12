---
create_time: 2026-06-12 12:52:07
status: done
prompt: sdd/prompts/202606/pypi_smoke_env.md
---
# PyPI Release Smoke-Test Environment

## Problem

We recently published `sase`, `sase-github`, and `sase-telegram` to PyPI (plus the Rust core, which is published as the
**`sase-core-rs`** binary wheel — there is no `sase-core` distribution on PyPI; it is pulled in automatically as a
dependency of `sase`). We need to verify that what's actually on PyPI installs and works for a _fresh user_ — not for a
developer with an editable checkout, a populated `~/.sase`, and an existing `~/.config/sase`.

This needs to be **replicable**: one command should re-run the same verification next month against whatever is on PyPI
then (or against explicitly pinned versions).

Current published state (2026-06-12):

| Package         | Latest | Uploaded   |
| --------------- | ------ | ---------- |
| `sase`          | 0.1.6  | 2026-06-12 |
| `sase-core-rs`  | 0.1.2  | 2026-06-09 |
| `sase-github`   | 0.1.1  | 2026-06-11 |
| `sase-telegram` | 0.1.0  | 2026-06-09 |

## Why Docker (Compose)

A plain `uv venv` on the host is not a fresh environment: sase hardcodes `~/.config/sase` and `~/.sase` (only
`SASE_HOME` is overridable, there is no XDG override for config), local `./sase.yml` files leak into the config merge
chain, and the host already has provider CLIs, git config, and shell state. A container gives us:

- A guaranteed first-run experience (empty home, no stale config/state).
- A pinned, documented base (Python 3.12 image + uv + git + node/claude CLI) that still works the same in a month.
- Easy "wipe everything and start over" semantics (`docker compose down -v`).

Compose (vs. raw `docker run`) buys us: named volumes for persisting provider auth between interactive sessions, a
bind-mounted `results/` directory for smoke reports, env-file driven version pinning, and one-word service invocations.

## Design Overview

New directory `smoke/pypi/` containing a self-contained harness:

```
smoke/pypi/
├── Dockerfile            # toolchain only — NO sase packages baked in
├── docker-compose.yml    # one service, two usages: automated check + interactive shell
├── entrypoint.sh         # wipes sase state, fresh-installs from PyPI, dispatches mode
├── smoke_check.sh        # the automated assertion suite
├── .env.example          # optional version pins (SASE_SPEC=sase==0.1.6, etc.)
├── README.md             # how to run now, how to replicate next month
└── results/              # gitignored; timestamped smoke reports land here
```

### Image (build once, reusable for months)

`python:3.12-slim` base with: `git`, `curl`, `ca-certificates`, `tmux` (ACE has tmux integration), UTF-8 locale + sane
`TERM` (Textual TUI), Node.js + `@anthropic-ai/claude-code` (so `sase doctor` has a provider executable to find and
interactive runs are possible), the `gh` CLI (for exercising `sase-github` against a real repo interactively), and `uv`.
Runs as a non-root `tester` user. **The sase packages are deliberately NOT installed at build time** — the image is just
the toolchain, so a cached image still tests _current_ PyPI state on every run.

### Fresh install at container start (entrypoint)

Every container start:

1. Wipe sase-owned state only: `~/.sase`, `~/.config/sase`, and any previous sase uv-tool venv. Provider auth
   (`~/.claude*`, `gh` auth) is intentionally preserved — it lives in a named `home` volume so you authenticate once per
   "season" and `docker compose down -v` resets even that when you want absolute zero.
2. Install exactly the way the README tells users to, with plugins injected into the same venv (required for entry-point
   discovery):
   `uv tool install --force --refresh "$SASE_SPEC" --python 3.12 --with "$SASE_GITHUB_SPEC" --with "$SASE_TELEGRAM_SPEC"`.
   Specs default to unpinned names (test "latest"); `.env` can pin exact versions for reproducing a past test.
3. Dispatch on the compose command: `check` runs `smoke_check.sh`; `shell` drops into bash for manual use.

### Automated checks (`docker compose run smoke check` — no LLM auth required)

Staged, fail-fast, with a timestamped report (full command output + resolved versions) written to `results/`:

1. **Install** — the `uv tool install` above succeeds; `sase` is on PATH.
2. **Versions** — `sase version -j` parses; asserts `sase` and `sase-core-rs` are present (and equal to pins when
   pinned). This is the explicit `sase-core-rs` coverage.
3. **Rust core import** — `python -c "import sase_core_rs"` inside the tool venv, proving the abi3 wheel loads on the
   container's platform.
4. **Plugin discovery** — `sase plugin list -j` / `sase plugin doctor -j` show `sase-github` and `sase-telegram` entry
   points loaded (catches the classic "plugin published but entry points broken" failure).
5. **Doctor** — `sase doctor -j` runs; pass criteria = no hard errors (provider _auth_ gaps are tolerated in check mode
   since the container is unauthenticated by default; exact criteria finalized during implementation against the doctor
   JSON schema).
6. **Provider-independent usage** — in a scratch git repo inside the container, exercise a handful of local, no-LLM
   flows (final list chosen during implementation): `sase --help` + key subcommand helps, bead create/list, xprompt
   listing, config dump. This is the "use it a bit" floor that needs no credentials.
7. **Second install flavor (cheap)** — `uv venv && uv pip install sase sase-github sase-telegram` + repeat stages 2–4,
   covering the `pip install` path the plugin docs advertise.

Exit code reflects overall pass/fail so this can later be cron'd or CI'd as-is.

### Interactive "use it a bit" (`docker compose run smoke shell`)

The README walks through the documented 15-minute flow inside the container: authenticate `claude` once (persisted in
the `home` volume; an optional compose override file can instead bind-mount host `~/.claude` for convenience), then
`sase doctor` → `sase run "#cd:... summarize ..."` → `sase agents status` → `sase ace`. Optional `GH_TOKEN` / Telegram
bot token pass-through env vars enable real `sase-github` / `sase-telegram` end-to-end testing when desired.

### Replication story (the "next month" requirement)

- `just pypi-smoke` — build image if needed, run the automated suite against current PyPI, report in `results/`.
- `just pypi-smoke-shell` — interactive container.
- `just pypi-smoke-clean` — `docker compose down -v` + remove image: full factory reset.

Because installation happens at runtime with `--refresh`, re-running next month needs no rebuild and automatically tests
the then-current releases; pinning via `.env` reproduces any historical combination.

## Non-Goals / Risks

- **Not** testing unpublished/local builds — this harness is strictly about PyPI artifacts. (A future `--index`/local
  wheel mode is an easy extension but out of scope.)
- Real agent runs, GitHub PR flows, and Telegram chat flows require credentials and stay interactive/manual; the
  automated suite proves install + discovery + provider-independent CLI behavior only.
- `sase doctor` pass criteria in an unauthenticated container needs tuning during implementation (tolerate auth
  warnings, fail on structural errors).
- Host needs Docker + Compose v2; the README states this prerequisite.

## Verification

1. Run `just pypi-smoke` end-to-end on this machine; confirm all stages pass against the versions in the table above and
   a report lands in `results/`.
2. Sanity-check the pinning path (`.env` with `SASE_SPEC=sase==0.1.6`).
3. Spot-check `just pypi-smoke-shell` boots into a usable shell with `sase` installed.
4. `just install && just check` (repo rule for any file changes).
