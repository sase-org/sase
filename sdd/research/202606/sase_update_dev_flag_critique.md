# `sase update --dev` — Plan Critique and Alternatives

Date: 2026-06-25
Status: Research / plan critique

## Question

The plan: once the **sase-58** epic (`sase update` + `sase plugin install/update`) lands, add a `--dev` option to
`sase update` that installs the `sase-dev` development version of sase, and make `sase update --dev` **the recommended
way of installing the development version of sase**.

Is this the right way to do it? If so, what are the alternatives, and which is recommended?

## Short Answer

`sase update --dev` is an attractive *convenience verb*, but it should **not** be "the recommended way of installing the
dev version," and it should not ship in the shape the one-liner plan implies. Three hard problems block that framing:

1. **Bootstrap paradox.** You cannot install sase from scratch with a sase subcommand. `sase update --dev` only works
   once `sase` is already installed, so it can *switch* an install to dev — it cannot be the primary *install* path. The
   honest "install the dev version" surface must be bootstrap-capable (curl installer, a `uv tool install --from git`
   one-liner, or `just install-sase-dev`).
2. **Verb/semantics + detection collision.** sase-58 defines `sase update` as `uv tool upgrade sase` and, per its
   detection rule **D4**, the command *refuses to run from anything but a `uv tool install sase` release install* (it
   rejects dev-checkout venvs by design). Grafting "install a different, dev build" onto a command whose contract is
   "upgrade the release I'm already running" overloads the verb and pushes against its own guardrail.
3. **No dev channel exists to install.** There is currently no `.devN`/pre-release stream (the TestPyPI dev-stream was
   explicitly deferred in `direct_master_pypi_releases_consolidated.md`). So `--dev` would have to mean "install from git
   master," which carries a real **Rust-core version-mismatch** caveat and is not reproducible the way a release is.

There is also a **naming collision** to resolve up front: prior research (`sase_dev_install_strategy.md`) already uses
`sase-dev` to mean a *second command / parallel runtime* installed beside stable `sase`. The new plan reuses the words
"sase-dev development version" to mean "the dev build of sase." If both ship, `sase-dev` (a command) and
`sase update --dev` (a flag) would mean different things. Pick one meaning for the term before building either.

The recommended path (detailed at the end) **splits install from switch**: keep a bootstrap-capable dev install surface
(curl `--dev` and/or `just install-sase-dev`), and add `sase update --dev` only as an *in-place channel switch* that
rides sase-58's existing "receipt is the source of truth" model — once a concrete dev source is defined.

## Verified Baseline

- **sase-58 builds `src/sase/uv_tool/`** (detect / receipt / commands / runner / errors / render) and `sase update`
  == `uv tool upgrade sase` (re-resolves core **and** all `--with` plugins in one shot).
- **Detection D4 is strict and intentionally exclusive.** "Installed via uv tool" ⇔ `uv` on `PATH` **and** the running
  interpreter's `sys.prefix` resolves to `<uv-tool-dir>/sase` **and** that dir holds `uv-receipt.toml`. The plan states
  this "correctly means the command **refuses when run from a dev workspace venv**." A naive `--dev` fights this rule.
- **The receipt round-trips whatever uv recorded**, including `editable = "/path/..."` and git/specifier sources. The
  reconstruction faithfully reproduces `--editable` / `--with-editable`. This is the key lever for a clean channel
  switch: if the dev source is recorded in the receipt, plain `sase update` re-resolves it for free.
- **No dev release channel today.** Stable PyPI is fed by Release Please; the `.devN`/TestPyPI pre-release stream was
  deferred (Option F in `direct_master_pypi_releases_consolidated.md`). `sase-dev` returns **404** on PyPI; `sase`
  returns 200.
- **uv has the mechanism but not the content.** Local `uv 0.11.24` `uv tool install` supports `--from`, `-e/--editable`,
  `--with-editable`, `--prerelease`, `--reinstall`, `--force`, `-U/--upgrade`, `-P/--upgrade-package`. So a git/editable
  or `--prerelease allow` install is mechanically possible; there is just nothing pre-release published to resolve.
- **The dev install today is `just install` from a source checkout** (README "Install from source": `uv venv` →
  `source` → `just install`), which also builds sibling `../sase-core` into the venv when present. `just
  rust-install-uv-tool` can inject the local Rust core into an existing `uv tool` sase venv. There is **no
  `install-sase-dev` target yet** — it is a recommendation in `sase_dev_install_strategy.md`, not shipped.
- **Prior dev-runtime research (`sase_dev_install_strategy.md`)** recommends `sase-dev` as a *first-class local runtime*:
  a repo-owned installer (`just install-sase-dev`) that creates a dedicated dev venv, installs the local Rust core, and
  writes a `~/.local/bin/sase-dev` launcher defaulting to `SASE_PROFILE=dev` for state isolation — so stable `sase` and
  dev `sase-dev` can run **side by side**. It explicitly rejects publishing a renamed `sase-dev` distribution as the
  first implementation (plugin misclassification, duplicate top-level package providers, dependency policy churn).

## Why the One-Liner Plan Is Risky (the four cracks)

### 1. Bootstrap paradox — install vs. switch
"The recommended way of *installing* the dev version" via `sase update --dev` presupposes `sase` already exists on
`PATH`. For a brand-new machine the user still needs `git clone + just install`, a curl installer, or
`uv tool install ... --from git`. `sase update --dev` is therefore a *channel switch for existing users*, not an install
path. Marketing it as the install path will mislead first-time dev users.

### 2. It either replaces stable in place, or it isn't a `update` at all
A uv tool is keyed by name (`sase`). If `sase update --dev` re-points `<uv-tool-dir>/sase` at a dev source, it
**overwrites the stable install in place** — you now have one install running dev code, and the "stable + dev side by
side" story from `sase_dev_install_strategy.md` is gone. If instead `--dev` provisions the *separate* parallel runtime
(dev venv + `~/.local/bin/sase-dev` launcher + `SASE_PROFILE=dev`), then it is **not a uv-tool upgrade at all** and none
of sase-58's `uv_tool` engine (receipt parse, `uv tool upgrade`) applies — the flag would do something wholly outside
the command's own machinery. The plan conflates these two very different products.

### 3. The Rust-core mismatch for git-source dev installs
A git-master `uv tool install --from git+...@master sase` still pulls `sase-core-rs` from PyPI per `pyproject.toml`'s
pinned range. But the dev build of sase frequently depends on **unreleased** `sase-core` Rust API. So a pure
git/PyPI dev install can be subtly broken whenever master's Python is ahead of the published Rust core — exactly the
case the source-checkout flow avoids by building sibling `../sase-core` into the venv. `sase update --dev` over git/PyPI
cannot do that; only an editable/source-aware installer can.

### 4. No profile isolation
`sase_dev_install_strategy.md`'s central value is a dev runtime that defaults to `SASE_PROFILE=dev` so it does not
collide with stable state, config, workspaces, and axe daemons. An in-place `--dev` re-point gives dev code over
**stable** state — no isolation, no side-by-side — which is a regression against that design.

## Options

### Option A — Ship `sase update --dev` as the install path (the plan as stated)
Re-point the existing uv-tool sase at a dev source.

- **Pros:** one memorable command; reuses sase-58 engine.
- **Cons:** all four cracks above. It is not actually an install path (bootstrap paradox), overwrites stable in place,
  hits the Rust mismatch, and loses isolation. **Not recommended as the primary surface.**

### Option B — `sase update --dev` as a pure *channel switch* over a defined dev source (reuse the receipt)
`--dev` runs `uv tool install sase --from <dev-source> --force --reinstall`; `--stable` re-points to PyPI. Because
sase-58 already treats the **receipt as the source of truth**, the channel becomes *self-sticky*: after `--dev`, the
receipt records the git/editable source, so a later plain `sase update` (`uv tool upgrade sase`) re-resolves the dev ref
automatically — no new persisted state needed. Plugins reconstruct correctly because the receipt round-trips their
sources too.

- **Pros:** tiny addition to sase-58 (one argv builder + a `--dev/--stable` flag); rides existing machinery; respects
  D4 (you must already be a uv-tool install); stays Python-only per D6; no new state store.
- **Cons:** still in-place (no side-by-side); still git/PyPI Rust mismatch unless the dev source is editable-aware;
  needs a concrete `<dev-source>` definition. Verify with a real-uv harness that `uv tool upgrade` on a moving git
  **branch** actually advances (may need `--refresh`/`--reinstall`).
- **Verdict:** the right shape *for a switch*, not for first install.

### Option C — Bootstrap-capable dev install via the curl installer's `--dev` flag
`sase_curl_install_script_consolidated.md` already designs an installer with a flag set. Add `--dev` there to perform
the git/editable dev bootstrap (and optionally wire the sibling Rust core). The installer is the natural "install the dev
version" surface precisely because it does **not** require sase to exist first.

- **Pros:** solves the bootstrap paradox honestly; one documented public command; can handle Rust core; secondary to the
  stable `uv tool install` per existing install research.
- **Cons:** depends on the curl installer actually shipping; shell-side complexity for the Rust-core path.

### Option D — The parallel `sase-dev` runtime (prior research), surfaced via `just install-sase-dev`
Keep dev as a *separate, profile-isolated runtime* (`~/.local/share/sase-dev/venv` + `~/.local/bin/sase-dev` launcher,
`SASE_PROFILE=dev`), installing the local Rust core. `sase update` stays purely "upgrade the stable uv-tool install."

- **Pros:** true side-by-side stable+dev; correct Rust core; isolated state; matches the existing, more thorough
  `sase_dev_install_strategy.md` design.
- **Cons:** more upfront work (launcher, current-runtime helper, profile path derivation in Python *and* Rust core); not
  a one-flag add to sase-58.
- **Verdict:** the right answer for "run stable and dev simultaneously"; orthogonal to `sase update`.

### Option E — Stand up a real dev channel first (deferred Option F), then `--prerelease allow`
Publish `.devN`/`rcN` pre-releases (TestPyPI or PyPI) on master pushes, then `sase update --dev` ==
`uv tool install sase --prerelease allow --upgrade`.

- **Pros:** reproducible, index-backed dev versions; cleanest long-term `--dev` semantics; no git/source build on the
  user's machine.
- **Cons:** requires release-pipeline work before any `--dev` flag is meaningful; still pulls Rust core from an index
  (so the dev Python and dev Rust must be released in lockstep, which the cross-repo coordination notes flag as
  non-trivial).

## Recommended Approach

**Split "install the dev version" from "switch an existing install to dev," and define the dev source before adding any
flag.** Concretely, in priority order:

1. **Decide what "the dev version" *is*, and disambiguate the name.** Choose one:
   - *Cheapest, reproducible-ish:* git master (`--from git+https://github.com/sase-org/sase@master sase`), documented
     with the Rust-core caveat; or
   - *Best long-term:* the deferred `.devN` pre-release channel (Option E), enabling `--prerelease allow`.

   Separately, stop overloading "sase-dev": let `sase-dev` keep meaning the *parallel runtime* (Option D) and describe
   the new flag's target as "the **dev channel** of sase," not "the sase-dev version."

2. **Make the bootstrap surface the honest "recommended way to install dev"** — not `sase update`. Prefer the curl
   installer's `--dev` (Option C) and/or keep `just install-sase-dev` (Option D) for the source/side-by-side path.
   Document `uv tool install --from git+...@master sase` as the no-frills one-liner.

3. **Add `sase update --dev` only as an in-place channel switch (Option B), layered on sase-58.** Implement it as a new
   pure argv builder in `src/sase/uv_tool/commands.py` (e.g. `build_install_dev(source)` →
   `uv tool install sase --from <source> --force --reinstall`, faithfully re-adding the reconstructed `--with` plugin
   set from the receipt), plus a `--stable` inverse that re-points to PyPI. Let the **receipt** carry the channel so
   plain `sase update` stays correct after a switch — no new state file. Keep D4 (must already be a uv-tool install) and
   D6 (Python-only) intact. Render it with the same `✓ · ⚠` grammar as the rest of sase-58, including a one-line "now
   tracking the dev channel — `sase update --stable` to go back."

4. **Keep the parallel, profile-isolated `sase-dev` runtime separate (Option D).** `sase update --dev` must **not**
   silently provision the parallel runtime; the in-place switch and the side-by-side runtime are two different products.

5. **Gate on a real-uv harness** (sase-58 Phase 4 style, throwaway tool): confirm that switching the recorded source and
   then `uv tool upgrade sase` advances a moving git branch (likely needs `--refresh`/`--reinstall`), and that the
   reconstructed `--with` plugin set survives the switch.

This keeps the shipped artifact identity stable, reuses sase-58's engine almost entirely, tells the truth about install
vs. switch, and preserves the more thorough parallel-runtime design already on record — at the cost of one prerequisite
the one-liner plan hides: **a defined dev source must exist before `--dev` means anything.**

## Sources

Internal:

- `sdd/epics/202606/sase_update_and_plugin_install.md` (sase-58 design; D4 detection, receipt-as-source-of-truth)
- `sdd/research/202606/sase_dev_install_strategy.md` (parallel `sase-dev` runtime; profile isolation; rejected options)
- `sdd/research/202606/sase_curl_install_script_consolidated.md` (installer flag set; install-path layering)
- `sdd/research/202606/direct_master_pypi_releases_consolidated.md` (release pipeline; deferred `.devN` dev stream)
- `sdd/research/202606/automated_semver_releases_consolidated.md` (Release Please; cross-repo Rust/Python coordination)
- `README.md` (source install via `just install`), `Justfile` (`install`, `rust-install-uv-tool`), `pyproject.toml`
  (`sase-core-rs` pinned range)

External:

- uv tools: https://docs.astral.sh/uv/concepts/tools/ ; `uv tool install` reference:
  https://docs.astral.sh/uv/reference/cli/#uv-tool-install (verified `--from`, `--editable`, `--prerelease`,
  `--reinstall`, `--force`, `-U`, `-P` on local uv 0.11.24)
- PyPI checks 2026-06-25: `sase` 200, `sase-dev` 404 (`https://pypi.org/pypi/sase-dev/json`)
- pip pre-release behavior: https://pip.pypa.io/en/stable/cli/pip_install/
