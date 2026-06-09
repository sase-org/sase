# `sase doctor` Command Research

Date: 2026-06-09

## Question

Would a new top-level `sase doctor` command be useful for troubleshooting SASE? If so, what should it check for, and
what should it output? This note ends with a recommended solution.

## Bottom Line

**Yes — but the value is consolidation, not net-new checks.** SASE already ships at least seven diagnostic-ish
commands scattered across the CLI (`core health`, `plugin doctor`, `validate`, `telemetry health`, `telemetry status`,
`bead doctor`, `memory episodes doctor`, plus `version`). No single command answers the question a confused user
actually asks: *"Is my SASE install healthy, and if not, what do I fix?"* A user today has to know which of seven
commands to run, and each has a different output format and exit-code convention.

`sase doctor` should be a **single, aggregating, environment-first entry point** that runs the highest-value checks,
reuses the existing per-domain diagnostics as sections, prints a human-readable traffic-light report with concrete
next-step remediation, supports `-j/--json` for scripting, and exits non-zero when something is broken. It should be
the command the docs, the README, and error messages point people to first.

This directly fulfills an open recommendation from
[`sase_install_use_understand_readiness_consolidated.md`](./sase_install_use_understand_readiness_consolidated.md),
which called for "a single readiness path that reports versions, Rust-core status, init drift, provider CLI
availability, and plugin environment guidance." That *is* `sase doctor`.

## Why It Is Useful

### 1. The diagnostic surface is already fragmented

SASE has grown a number of overlapping health/diagnostic commands, each scoped to one subsystem and each with its own
output style and exit-code policy:

| Command | Scope | Output | Exit codes | Source |
| --- | --- | --- | --- | --- |
| `sase core health` | `sase_core_rs` Rust binding import + 4 probe fns, Python/platform | plaintext / `-j` | 0 ok, 1 error | `src/sase/core/health.py` |
| `sase plugin doctor` | plugin entry points, chop scripts, `gh` auth, Telegram env/`pass` | rich panels / `-j` | 0 ok/warn, 1 error | `src/sase/plugins/doctor.py` |
| `sase validate` | runs `init --check` + `sdd validate` as subprocesses | plaintext | 0 pass, 1 fail | `src/sase/main/validate_handler.py` |
| `sase telemetry health` | Prometheus subsystem error rates | rich table / `-j` | 0/1/2 | `src/sase/telemetry/cli_health.py` |
| `sase telemetry status` | telemetry enabled? gateways reachable? | rich panel | always 0 | `src/sase/telemetry/cli_status.py` |
| `sase bead doctor` | bead project state (`proj.doctor()`) | plaintext | — | `src/sase/bead/cli_admin.py` |
| `sase memory episodes doctor` | episode index lock/build/orphans, `-R` repair | `-j` | — | `src/sase/memory/episodes/_auto_build_doctor.py` |
| `sase version` | runtime package inventory (host, Rust core, plugins) | rich table / `-j` | always 0 | `src/sase/main/version_handler.py` |

There is **no** top-level `sase doctor` today (only `plugin doctor`, `bead doctor`, `memory episodes doctor` exist as
nested subcommands). Confirmed against every `register_*_parser` in `src/sase/main/parser_*.py`.

This fragmentation is the core problem. A user hitting "agents won't launch" or "my changespec won't load" has no
obvious first command. They must already know that changespec parsing lives behind `core health`, that provider CLIs
aren't checked anywhere, and that `validate` only covers init/SDD drift.

### 2. SASE has many runtime preconditions that silently fail

SASE shells out to and depends on a wide set of external tools, env vars, and on-disk state. When any are missing the
failure usually surfaces deep inside an agent run (a `FileNotFoundError`, a stale wheel `AttributeError`, a parse
error) rather than at a friendly check point. Concretely:

- **Rust core binding** `sase_core_rs` (`>=0.1.1,<0.2.0`, `pyproject.toml`). If it is missing or stale, changespec
  read/write is completely broken. Stale wheel → `AttributeError`; ABI/Python mismatch → `ImportError`. This is the
  single highest-value check and already exists as `core health`.
- **Provider CLIs** — `claude`, `gemini`, `codex`, `qwen`, `opencode`, each resolved via `SASE_<X>_PATH` or `PATH`
  (`src/sase/llm_provider/*.py`). If the configured runtime's CLI is absent, agent launch fails. **Nothing checks this
  today.**
- **`git`** — pervasive subprocess use across the VCS provider; broken/missing git or unset `user.name`/`user.email`
  breaks workspace and commit flows.
- **`gh`** (GitHub CLI) auth — already checked by `plugin doctor` when the GitHub plugin is present.
- **Optional render tools** — `tmux`, `bat`, `pandoc`, `pdftoppm`, `kitten`, a PDF engine
  (`wkhtmltopdf`/`xelatex`/`pdflatex`), `prettier`. Missing → graceful degradation, so these are WARN-level at most.
- **Config** — merged from bundled `default_config.yml`, plugin defaults, `~/.config/sase/sase.yml`, overlays, and a
  local `./sase.yml` (`src/sase/config/core.py`). Malformed YAML is swallowed and silently falls back to defaults,
  which is exactly the kind of "looks fine but isn't" failure a doctor should surface.
- **Filesystem state** — `$SASE_HOME` (default `~/.sase`) and `$SASE_WORKSPACE_ROOT` (default `~/.sase_workspaces`)
  must exist and be writable; orphaned `sase_<N>` workspaces accumulate; stale agent `running.json` and broken memory
  symlinks cause zombie/aborted states.
- **Python** — `requires-python = ">=3.12"`.
- **Ephemeral-workspace tax** — per `memory/short/build_and_run.md`, a reused workspace can have a stale `.venv`;
  `just install` must run before other commands. A doctor that detects an out-of-date environment closes a real,
  recurring footgun.

The breadth above is *why* a doctor is useful, not a checklist to implement wholesale. The recommended scope below is
deliberately tiered.

## What `sase doctor` Should Check

Organized into tiers by value. Each check should carry a status (`OK` / `WARN` / `ERROR` / `SKIP`), a one-line
summary, optional detail lines, and concrete `next_steps` — the exact shape of the existing `DoctorCheck` dataclass in
`src/sase/plugins/doctor.py:18`.

### Tier 1 — Core install integrity (ERROR if broken; these block real work)

1. **Python version** ≥ 3.12.
2. **`sase_core_rs` binding** — import succeeds, version satisfies `>=0.1.1,<0.2.0`, probe functions callable. (Wrap
   the existing `core health` logic.)
3. **Environment freshness** — detect the stale-`.venv` / "run `just install`" condition for ephemeral workspaces
   (e.g. installed `sase`/`sase-core-rs` versions vs. what the checkout expects).
4. **`git`** available and runnable; `user.name` / `user.email` configured.
5. **Active provider CLI present** — for the configured/default agent runtime(s), the resolved CLI binary exists on
   `PATH` or via `SASE_<X>_PATH`. ERROR for the default runtime, WARN for non-default ones.
6. **`$SASE_HOME` and `$SASE_WORKSPACE_ROOT`** exist and are writable.

### Tier 2 — Config & init drift (WARN/ERROR; degrade silently today)

7. **Config loads cleanly** — `~/.config/sase/sase.yml` and overlays parse as valid YAML (surface the swallowed-parse
   case explicitly); report which layers are active.
8. **Init / SDD drift** — fold in `sase init --check` and `sase sdd validate` (what `sase validate` already does).
9. **Plugin environment** — fold in `plugin doctor`: entry-point load failures (ERROR), unresolved configured chops
   (ERROR), `gh` auth, Telegram env/`pass` (WARN).

### Tier 3 — Optional tooling & hygiene (WARN/SKIP; nice-to-have)

10. **Optional render tools** — `tmux`, `bat`, `pandoc`, `pdftoppm`, `kitten`, a PDF engine, `prettier`. WARN with the
    feature that degrades; never ERROR.
11. **Workspace hygiene** — count of orphaned `sase_<N>` workspaces; point at `sase workspace cleanup`.
12. **Telemetry reachability** — only if telemetry is enabled in config; otherwise SKIP. (Wrap `telemetry status`.)
13. **State integrity** — stale agent `running.json`, broken memory-episode symlinks (point at the existing
    `memory episodes doctor -R`).

A guiding principle from the existing code: **scope checks to what is actually in use.** `plugin doctor` only runs the
GitHub/Telegram checks when those plugins/chops are present (`_has_github_plugin`, `_has_telegram_chop_scripts`). Doctor
should likewise SKIP, not WARN, on subsystems the user hasn't opted into — otherwise the report cries wolf.

## What `sase doctor` Should Output

Mirror the conventions already established by `plugin doctor` (`src/sase/plugins/doctor.py`) since it is the cleanest
existing model and already has a serializable data structure:

- **Default (human):** a rich, traffic-light report grouped by section (Core, Config, Plugins, Tooling, Hygiene). Each
  check is one line: a colored status glyph, the summary, and — for non-OK checks — indented `details` and a
  **"→ next step"** remediation line. End with a one-line overall verdict and a count (`3 OK · 2 WARN · 1 ERROR`).
  Show only failing/notable checks by default; gate the full pass list behind `-v/--verbose`.
- **`-j/--json`:** a stable, versioned object — reuse the `doctor_report_to_dict` shape (`schema_version`, overall
  `status`, and a `checks` array of `{id, status, summary, details, next_steps}`). This is what CI, the docs smoke
  test, and any future "readiness" tooling consume.
- **Exit codes:** `0` when overall is OK (or only SKIP), non-zero when any ERROR (and optionally a distinct code for
  WARN-only, matching how `telemetry health` uses 0/1/2). Pick **one** convention and apply it — the current
  inconsistency (some commands always exit 0, some 0/1, telemetry 0/1/2) is itself a papercut worth fixing here.
- **Always actionable:** every WARN/ERROR must name the fix (`just install`, `gh auth login`, "set `SASE_CLAUDE_PATH`
  or install the `claude` CLI", `sase workspace cleanup`). The existing `next_steps` field already enforces this habit.

Optional flags worth considering: `-q/--quiet` (verdict + exit code only), and a `--section <name>` filter so power
users can run just one group. Per `memory/short/gotchas.md`, every option needs both a short and long form.

## Design Considerations / Trade-offs

- **Aggregate, don't duplicate.** The biggest risk is re-implementing checks that already live in `core/health.py`,
  `plugins/doctor.py`, `validate_handler.py`, etc., and letting them drift. Recommended: extract the `DoctorCheck` /
  `DoctorReport` / `CheckStatus` / `aggregate_check_status` / `*_to_dict` machinery (currently private to
  `src/sase/plugins/doctor.py`) into a shared module (e.g. `sase.diagnostics`), then have both `plugin doctor` and the
  new `doctor` build `DoctorCheck`s into it. `doctor` becomes an orchestrator that calls each domain's check-builder
  and renders the union.
- **Backend boundary.** Per `memory/short/rust_core_backend_boundary.md`, ask the litmus question for each check: would
  a web UI / editor integration want the same health verdict? Environment/CLI-presence checks are arguably
  presentation-adjacent and can live in Python, but the *Rust core* probe and any changespec/state-integrity logic
  belong in `sase-core` with a thin Python adapter. At minimum, don't reimplement core logic in the doctor handler.
- **Speed.** Doctor must be fast and never hang. Subprocess probes (`gh auth status`, provider `--version`) need short
  timeouts — `plugin doctor` already uses `timeout=5` on `gh auth status`. Network checks (telemetry, PyPI) should be
  opt-in or strictly bounded.
- **Don't re-test the world.** `validate` shells out to `python -m sase init --check` as a subprocess; doing that for
  every section would be slow. Prefer calling the underlying functions directly within one process where practical.
- **Doctor as the documented front door.** Once it exists, point the README quickstart, docs troubleshooting page, and
  agent-launch error messages at `sase doctor` so it becomes the reflexive first step.

## Recommended Solution

Add a single top-level **`sase doctor`** command that aggregates SASE's existing, scattered diagnostics into one
traffic-light report with actionable remediation, plus the few high-value checks that exist nowhere today (provider CLI
presence, env freshness, writable state dirs, config-parse validity).

Concretely:

1. **Promote the diagnostics primitives.** Move `DoctorCheck`, `DoctorReport`, `CheckStatus`, `aggregate_check_status`,
   and the `*_to_dict` serializers out of `src/sase/plugins/doctor.py` into a shared `sase.diagnostics` module.
   Refactor `plugin doctor` to import them (no behavior change).
2. **Build the orchestrator.** New `src/sase/main/parser_doctor.py` (`register_doctor_parser`) and
   `src/sase/main/doctor_handler.py`, wired in `parser.py` (import + register, alphabetical) and `entry.py` (dispatch,
   alphabetical) — the standard top-level-command boilerplate. Both `-j/--json` and `-v/--verbose`; pick a single
   exit-code convention (`0` OK/SKIP, `1` WARN, `2` ERROR is a reasonable choice given `telemetry health` precedent).
3. **Scope to tiers.** Implement Tier 1 (core integrity) first — it delivers most of the value and largely wraps
   `core health` plus new provider-CLI / git / env-freshness / writable-dir checks. Then fold in Tier 2
   (`validate` + `plugin doctor` as sections) and Tier 3 (optional tooling, workspace/state hygiene, telemetry) as
   additional check-builders. Each subsystem contributes `DoctorCheck`s; SKIP cleanly when not in use.
4. **Make it the front door.** Point docs, README, and agent-launch error paths at `sase doctor`.

This is a high-leverage, low-risk addition: most of the hard logic already exists and is well-factored; the work is
mostly consolidation, a handful of new environment checks, and a consistent report/exit-code contract. It closes the
"what do I even run?" gap for new users and directly satisfies the readiness recommendation from prior research.

### Suggested follow-ups (out of scope for the first cut)

- `sase doctor --fix` / `-R/--repair` for safe auto-remediation (e.g. create missing state dirs, run `just install`),
  mirroring `memory episodes doctor -R`.
- A clean-environment CI smoke test that runs `sase doctor -j` and asserts an OK verdict, guarding the release funnel.
