# `curl | sh` Install Script for SASE — Research & Recommendation

Date: 2026-06-25
Status: Research

## Question

Should SASE ship a one-line `curl ... | sh` installer backed by an `install.sh` script to give users a better
first-run experience? The script could, for example, make sure `uv` is installed and, if not, offer to install it or
abort. What else should such a script do, and **should it exist at all**?

> Terminology note: the request mentions making sure "UB" is installed. This note reads that as **`uv`** (the Astral
> package manager) — SASE's documented prerequisite and the keyboard-neighbor typo of `uv`. If "UB" meant something
> else, the conclusions about prerequisite bootstrapping still apply; only the specific tool name changes.

## Short Answer (Recommendation)

**Yes — but keep it thin, and be clear about what it is.** Ship a small, auditable `install.sh` served from the SASE
domain whose job is *bootstrapping prerequisites and handing off to `sase doctor`*, not reimplementing installation.

The honest tension: SASE already has a genuinely good one-liner — `uv tool install sase --python 3.12` — and `uv`
itself already has a good one-liner. So an install script does **not** make installation meaningfully shorter. Its real
value is collapsing the **three-part cold start** (Python 3.12+, `uv`, one authenticated provider CLI) into a single
guided command that ends at the existing readiness gate. That is a real new-user win, but it is an *orchestration and
handoff* win, not an *installation* win. Build it for that, and resist letting it grow into a parallel installer.

A prior research note already considered this and chose to **defer**: "Defer. Revisit only if users fail before they
reach `uv tool install`." (`sdd/research/202605/preferred_plugins_chops_install_strategy.md:325`). The recommendation
here is a *narrowed* revisit: not a full bootstrapper that owns plugin/extras policy, but a thin prerequisite-and-doctor
launcher. If the team is not yet seeing real users stall before `uv tool install`, deferring again is defensible.

Recommended scope, in one sentence: **detect/offer to install `uv`, run `uv tool install sase --python 3.12`, then
exec `sase doctor` and print the next command** — with everything beyond that delegated to tools that already exist.

## Verified Baseline (what already exists)

### Installation today

- Canonical user install is a single command: `uv tool install sase --python 3.12`, followed by `sase version` and
  `sase doctor` (`README.md:27-31`). Prerequisites listed: Python 3.12+, `uv`, one authenticated provider CLI
  (`README.md:18-22`).
- Package metadata: distribution `sase`, version `0.5.0`, `requires-python = ">=3.12"`, hard dependency
  `sase-core-rs>=0.2.0,<0.3.0`, console script `sase` (`pyproject.toml`). Classifiers declare `Operating System ::
  POSIX` — Windows is not currently a first-class target.
- The required Rust core ships as a prebuilt wheel for normal installs; only source installs build it from a sibling
  `../sase-core` checkout (`README.md:271-276`, `docs/rust_backend.md`). So a normal install has **no Rust toolchain
  requirement** — important, because it means the install script does not need to handle `cargo`.
- Source/contributor install is a separate, heavier path (`uv venv`, `just install`) and is correctly kept under
  "Development" (`README.md:226-242`). An install script must not blur these two audiences.

### Readiness is already a first-class, machine-readable gate

`sase doctor` is the existing readiness command and is exactly what an install script should hand off to:

- Implemented under `src/sase/doctor/` (registry in `runner.py`); check groups include `runtime.version`,
  `runtime.core` (loads/probes the `sase_core_rs` extension), `runtime.environment` (Python 3.12+), `state.paths`,
  `vcs.git`, `config.*`, `plugins.*`, and provider checks.
- Provider readiness lives in `src/sase/doctor/checks_providers.py` (`llm.registry`, `llm.default`); it already encodes
  **per-provider install hints** (`checks_providers.py:19-45`), e.g. `claude` → `npm install -g
  @anthropic-ai/claude-code`, `agy` → `curl -fsSL https://antigravity.google/cli/install.sh | bash`, etc.
- Structured output via `-j`; status levels are `OK | WARN | ERROR | SKIP` with an aggregated process exit code. This
  means a script can branch on `sase doctor -j` instead of re-deriving any checks.
- Provider detection is registry-driven: `importlib.metadata.entry_points(group="sase_llm")` + `shutil.which()` for the
  autodetect CLI, with `SASE_<PROVIDER>_PATH` overrides (`src/sase/llm_provider/registry.py`). Five providers are wired
  via entry points in `pyproject.toml`: `agy`, `claude`, `codex`, `opencode`, `qwen`.
- `sase init` provides project onboarding (`src/sase/main/init_onboarding.py`); `sase version` and `sase core health`
  are the install-integrity inventory/probe commands.

**Implication:** every substantive "is this environment ready?" question is already answered by a SASE command. The
install script should *call* these, never *duplicate* them. The script owns only the gap *before* `sase` exists on
`PATH`.

### A clean-machine install harness already exists

`smoke/pypi/` already proves the one-liner works on a clean machine: `entrypoint.sh` runs `uv tool install --force
--refresh sase --python 3.12` and `smoke_check.sh` then exercises `sase version -j`, `sase doctor -j`, chop inventory,
and a scratch `bead` workflow inside Docker. This is effectively a *tested reference implementation* of "install + verify"
and should be the install script's source of truth and its regression guard (the install script and the smoke entrypoint
should not drift apart).

### Ecosystem precedent

- `uv`'s own installer is the model to mirror: `curl -LsSf https://astral.sh/uv/install.sh | sh` (and a PowerShell
  variant). The script can simply *delegate* `uv` bootstrapping to it.
- A SASE-supported provider already ships a `curl ... | bash` installer (`agy`:
  `curl -fsSL https://antigravity.google/cli/install.sh | bash`), so the pattern is already familiar to the target
  audience.

## What problem would the script actually solve?

Map the genuine cold-start failure points, and what closes each:

| Cold-start gap | Closed by `uv tool install sase` alone? | Closed by an install script? |
|---|---|---|
| `uv` not installed | No (user must read prereqs, install `uv` separately) | **Yes** — detect, offer, delegate to uv's installer |
| Python 3.12+ absent | Partially — `--python 3.12` makes `uv` fetch a managed Python | Yes, plus a clear message when it happens |
| `~/.local/bin` not on `PATH` | Partially — `uv` warns/manages this | Yes — detect and print the exact line to add |
| No provider CLI / not authenticated | No — surfaced only later by `sase doctor` | Partially — script ends at `sase doctor`, which already prints provider hints |
| "Did it work? what now?" | `sase version` / `sase doctor` exist but user must know to run them | **Yes** — script runs them and prints the next command |

The two rows where the script adds something a plain `uv tool install` does not are: **(1) bootstrapping `uv` for users
who don't have it, and (2) guaranteeing the run ends at the readiness gate with an explicit next step.** Everything else
is marginal. That is the real, narrow case for the script — and it is enough to justify a *thin* one.

## Should it exist? Decision

**Build it if** any of these are true: blog/launch traffic is imminent and cold readers are the target; telemetry or
anecdotes show users stalling on "install `uv` first"; or you want a single memorable URL (`https://sase.sh/install.sh`)
for marketing parity with `uv`/rustup/Starship.

**Defer again if** none of the above hold yet. `uv tool install sase` is already short, and a script you must maintain
across shells, distros, and CI is real surface area. The prior deferral logic still applies: revisit only when users
actually fail before reaching `uv tool install`.

The recommendation leans **build a thin one**, because a public launch is the explicitly stated context elsewhere in the
research corpus (onboarding, quickstart, blog), and the marginal maintenance cost of a *thin delegating* script is low.

## If it exists: what the script SHOULD do

Ordered responsibilities, each delegating to something that already exists:

1. **Be safe to pipe.** Wrap the entire body in a `main` function invoked on the last line, so a truncated download
   cannot execute a partial command (the rustup/uv idiom). Use `set -eu`; detect `bash` vs POSIX `sh` and re-exec if a
   needed feature is missing.
2. **Detect the platform.** OS/arch; bail with a clear message on unsupported platforms. Given the POSIX classifier,
   target Linux + macOS; explicitly tell Windows users to use `uv` directly (or a future `.ps1`).
3. **Ensure `uv`.** If `uv` is on `PATH`, use it. If not, **prompt** ("uv is required and not found — install it now via
   the official Astral installer? [Y/n]") and on assent delegate to `curl -LsSf https://astral.sh/uv/install.sh | sh`.
   On decline, abort with the manual instructions. Honor a non-interactive mode (see flags) that assumes yes.
4. **Install SASE.** Run `uv tool install sase --python 3.12` (pass `--force` only when an explicit reinstall flag is
   set). Let `uv` own Python provisioning, the isolated tool venv, and the prebuilt `sase-core-rs` wheel — do not
   second-guess any of it.
5. **Fix `PATH` visibility, don't silently rewrite it.** If the `uv` tool bin dir is not on `PATH`, print the exact
   `export PATH=...` / shell-rc line. Only edit a shell profile when the user explicitly opts in; never edit rc files
   silently.
6. **Hand off to the readiness gate.** Exec `sase version` then `sase doctor`. Surface doctor's own output verbatim —
   including its built-in provider install hints — rather than re-implementing provider detection. Optionally parse
   `sase doctor -j` to print a one-line PASS/WARN/next-step summary.
7. **End with the next command, not silence.** Print the safe first run from the README/quickstart, e.g.
   `sase run "#cd:$(pwd) summarize what this repository does; do not change files"`.

### Behavior, flags, and contracts

- **Idempotent**: re-running upgrades/no-ops cleanly; detect an existing install and offer upgrade vs. reinstall.
- **Non-interactive / CI mode**: `--yes`/`-y` (or `SASE_INSTALL_YES=1`) to assume yes for the `uv` prompt; required so
  the script is usable in Dockerfiles and CI, and so it can share logic with `smoke/pypi/entrypoint.sh`.
- **Version pinning**: `SASE_INSTALL_VERSION` / `--version` to install a specific `sase` version (and a documented
  channel story if a pre-release/dev stream ever exists — cross-reference `sase_dev_install_strategy.md`).
- **Plugin passthrough**: optional `--with sase-github` style passthrough to `uv tool install ... --with ...`, matching
  the extras/`--with` policy in `preferred_plugins_chops_install_strategy.md`. Keep this opt-in; do not make the default
  path opinionated about plugins.
- **`--help`, `--dry-run`, `NO_COLOR`**: table stakes for a script people are asked to pipe into a shell.
- **Clear exit codes**: propagate `uv` and `sase doctor` failures; don't exit 0 on a broken install.

## What it should NOT do

- **Not** reimplement Python/`uv`/`sase-core-rs` installation — delegate to `uv` entirely (no manual venvs, no `cargo`,
  no wheel fetching).
- **Not** reimplement readiness checks — `sase doctor` already owns runtime, core, provider, config, and git checks
  with structured output and exit codes.
- **Not** auto-install provider CLIs (`claude`, `codex`, etc.). Provider auth is interactive and provider-owned; the
  script should *point* to `sase doctor`'s hints, not run `npm install -g ...` behind the user's back.
- **Not** become the contributor/source install path (`uv venv` + `just install`) — keep that separate and clearly
  labeled.
- **Not** silently mutate shell rc files or global state.
- **Not** own plugin/extras policy as a default — that belongs to the `uv tool install --with` story already designed.

## Security & trust considerations (`curl | sh`)

The pattern is widely accepted for trusted vendors (rust, uv, Homebrew's bootstrap, Starship), and there is no known
real-world attack using it against a reputable HTTPS-served script. To stay on the safe side of the criticism:

- **Serve over HTTPS from a domain you control** (`https://sase.sh/install.sh` or `get.sase.sh`); the existing
  `sase.sh` site (`README.md:14`) makes this straightforward.
- **Truncation safety**: the `main`-function-at-the-end idiom prevents a partially downloaded script from running a
  half-command.
- **Auditability**: keep the script in-repo (e.g. `install.sh` at the root or under `tools/`), publish the served copy
  from that exact file, and document a "read first" path: `curl -LsSf https://sase.sh/install.sh -o install.sh; less
  install.sh; sh install.sh`.
- **Offer the auditable alternative prominently**: `uv tool install sase --python 3.12` is itself the
  "package-manager" alternative reviewers will want, so the README should keep it as the primary, with the curl line as
  the convenience option — not the reverse.
- Consider checksums/signing only if/when a self-hosted binary is ever distributed; today everything downloaded is
  fetched by `uv`/PyPI, which already provides its own integrity, so the script itself is the only new trust surface.

## Recommended rollout (thin MVP first)

1. **MVP**: `install.sh` that does steps 1, 3, 4, 6, 7 above (platform check, ensure `uv`, `uv tool install sase`, run
   `sase doctor`, print next command) with `--yes`/`--help`. Reuse `smoke/pypi/entrypoint.sh` logic; add a CI job that
   runs the script on a clean Linux + macOS image and asserts `sase doctor` passes (extends the existing smoke harness).
2. **Polish**: PATH guidance (step 5), `--version` pinning, `--with` passthrough, `--dry-run`, `NO_COLOR`.
3. **Docs**: add the curl line to the README *after* the `uv` one-liner (convenience, not replacement); wire it into the
   15-minute quickstart. Do not demote `uv tool install`.
4. **Maybe later**: a `.ps1` Windows variant — only if/when Windows support is declared (the POSIX classifier says it is
   not today).

## Open questions for Bryan

- Is the launch/blog timing close enough that cold-reader onboarding is the priority now, or is deferring (per the 2026-05
  note) still correct until there's evidence of users stalling pre-`uv`?
- Hosting: serve from `sase.sh/install.sh` (Cloudflare Pages, per the blog-launch research) vs. GitHub raw vs.
  `get.sase.sh`?
- Should the curl path ever default to any plugins/extras, or stay strictly core `sase` with `--with` opt-in?
- Confirm "UB" = `uv`. If it meant a different prerequisite, adjust step 3.

## Source References

Internal:
- `README.md` (prereqs + canonical `uv tool install` one-liner; sase.sh domain; source-install separation)
- `pyproject.toml` (distribution name/version, `requires-python`, `sase-core-rs` dep, `sase_llm` provider entry points,
  POSIX classifier)
- `docs/rust_backend.md` (prebuilt `sase-core-rs` wheel for normal installs; no Rust toolchain needed)
- `src/sase/doctor/runner.py`, `src/sase/doctor/checks_runtime.py`, `src/sase/doctor/checks_providers.py` (readiness
  checks, status levels, JSON output, per-provider install hints)
- `src/sase/llm_provider/registry.py` (provider autodetection via `sase_llm` entry points + `shutil.which`)
- `src/sase/main/init_onboarding.py` (`sase init` onboarding)
- `smoke/pypi/entrypoint.sh`, `smoke/pypi/smoke_check.sh` (existing clean-machine install + `sase doctor` verification
  harness — reuse as the install script's reference + regression guard)
- `sdd/research/202605/preferred_plugins_chops_install_strategy.md:325` (prior decision to **defer** `curl | sh`)
- `sdd/research/202606/sase_dev_install_strategy.md` (parallel dev install / runtime identity — relevant to version
  channels)
- `sdd/research/202606/new_user_onboarding_recommendations_consolidated.md` (onboarding priorities; install path must be
  true before launch)

External:
- uv installer pattern: `curl -LsSf https://astral.sh/uv/install.sh | sh` — https://docs.astral.sh/uv/
- "Curl to shell isn't so bad" — https://www.arp242.net/curl-to-sh.html
- Rust/rustup rationale (HTTPS + signed manifests, `main`-function truncation safety) —
  https://users.rust-lang.org/t/why-official-rust-sites-asks-to-pipe-curl-to-bash/36230
- Auditable alternative discussion — https://blog.nicholas.clooney.io/posts/setting-up-rust/
