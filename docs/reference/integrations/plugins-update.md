---
title: Installing and updating plugins
description: Look up sase update and plugin install, update, and uninstall.
---

# Installing and updating plugins

This page describes `sase update` and plugin install, update, and uninstall.

## Updating sase and plugins (`sase update`)

`sase update` updates `sase` **and every installed sase plugin together** from the
canonical uv-tool environment. For a managed install it delegates to
`uv tool upgrade sase`, re-resolving SASE core and injected plugins in one shot so they
move forward as a coherent set. Receipt-owned editable / dev components of the same uv
tool environment are detected from the receipt, updated from git, and reconciled so
Python entry points, dependencies, and compiled Rust artifacts match the checked-out
source (see [Dev / editable installs](#dev-editable-installs) below). Dev-update timing
baselines can be summarized from the local journal with `tools/dev_update_timings`.

```bash
sase update            # update sase + all plugins
sase update -n         # dry run: preview the uv or dev-update plan, change nothing
sase update -q         # quiet: print only a one-line summary
sase update -j         # stable machine-readable JSON
sase update -v         # stream full output of every step (git, uv, cargo)
sase update -t dev     # switch the install to dev (editable) mode; see below
sase update -t pypi    # switch the install back to managed PyPI mode
```

While it runs, `sase update` shows a live timeline of steps on your terminal: every step
is visible up front as a pending row, the running step shows its elapsed clock plus a
short tail of its live output, and finished steps collapse to a one-line result. A
failed step expands to its last output lines:

```text
╭─ sase update · dev install ─────────────────────────────────╮
│ ✓ Inspect install        uv tool · 1 editable · 2 managed  0.4s │
│ ✓ Check for updates      1 behind · 2 current              2.1s │
│ ✓ Fast-forward sase      a1b2c3d → 9f8e7d6 · 1 commit       0.9s │
│ ⠼ Rebuild Rust core into uv-tool venv                       0:31 │
│     │    Compiling sase_core v0.14.2                            │
│ ○ Restart scheduler                                             │
╰──────────────────────────────────────────────────────── 0:44 ─╯
```

When the run finishes, the live region is replaced by a static final frame (no spinner,
no tails), followed by the result panels highlighting what changed, what was already
current, and reminding you to restart long-running agents:

```text
✓ sase           0.5.0 → 0.6.1
✓ sase-github    0.3.2 → 0.4.0
· sase-telegram  0.1.0   (already current)

Updated sase + 1 plugin in 4.2s · 1 already current
↻ service proc scheduler restarted: pid 41210 -> pid 41388 to load the updated code.
```

When stderr is not a terminal (or `TERM=dumb`), progress is append-only plain lines
instead of a live region:

```text
sase update · dev install
[00:00] → Inspect install
[00:00] ✓ Inspect install — uv tool · 1 editable · 2 managed (0.4s)
```

- **Progress goes to stderr; results stay on stdout.** The live timeline and plain lines
  are written to stderr, while the final summary panels stay on stdout, so
  `sase update > out.txt` still shows live progress on the terminal and pipes stay
  clean. `-j|--json` disables progress entirely.
- **`-v|--verbose`** streams the full output of every step (git, uv, cargo) as it runs
  instead of just the short tail. With `-j` or `-q` it is accepted but has no effect,
  because the log always records full output.
- **Every run leaves a log file** at `~/.sase/logs/update/update-<UTC>-<pid>.log` with
  the full transcript (steps, commands, and all output). The newest 20 logs are kept.
  The JSON payloads also carry a `log_path` key with the transcript path (or `null`),
  without changing the schema version. Dry runs write no log.
- **Ctrl-C exits `130`.** The running step's process group is interrupted, the final
  frame prints, and the command exits `130` with no traceback. Checkouts are never left
  mid-merge beyond what git itself guarantees.
- **Mode switches (`-t/--to dev|pypi`) run in the same live session** after the
  confirmation prompt and plan preview, with restart and completion rows, the same final
  frame, and the same interrupt handling. A `--dry-run` preview shows a transient
  timeline on terminals only while it plans its fetches; the dry-run panel remains the
  only persistent output.

- **Install method is required.** `sase update` only works when sase was installed with
  `uv tool install sase` (the canonical install path). When it is run from a pip/pipx
  install or from a dev checkout's virtualenv, it **fails fast with an actionable
  message** and a non-zero exit code instead of touching the environment. The check is
  strict: `uv` must be on `PATH`, the running interpreter's `sys.prefix` must resolve to
  `<uv tool dir>/sase`, and that directory must contain a `uv-receipt.toml`.
- **Managed installs** use `uv tool upgrade sase`, re-resolving sase core and all
  injected plugins in a single shot so they move forward as a coherent set rather than
  drifting out of sync.
- **Editable checkouts** update only when they are clean and strictly behind their
  upstream tracking branch. SASE fetches the upstream, fast-forwards the checkout,
  reconstructs the uv-tool install from the receipt for editable Python packages, and
  rebuilds `sase-core-rs` into the uv-tool venv when the Rust core checkout changed.
  Before advancing the host checkout, SASE checks that its target
  `sase-core-revision.txt` pin is contained in the core checkout target. If the core
  checkout or its upstream lacks that revision, the host root is skipped with the
  missing pin and core checkout reason; plugin roots remain independent. Multiple
  packages in one git root are deduped.
- **Blocked editable states are non-destructive.** Dirty, diverged, detached-HEAD,
  no-upstream, offline, and fetch-failed checkouts are skipped with a reason. Commit or
  stash local changes, resolve divergence manually, check out a branch with an upstream,
  or rerun online; `sase update` never rebases, merges non-fast-forward, stashes, or
  discards local work.
- **Mixed installs** update editable packages through the dev path and managed packages
  through uv in one run, with one combined result. This includes the common contributor
  layout where `sase` and every plugin are editable but `sase-core-rs` remains a
  published wheel: the comprehensive update reconstructs the editable receipt and
  explicitly re-resolves the compatible core wheel without replacing or dropping those
  editable sources.
- **Restart behavior is automatic after real code changes.** In the CLI, SASE restarts
  the scheduler when it is running so it loads the new code. In the Admin Center Updates
  tab, SASE restarts sase's TUI and the service host through the same restart path as
  the `Q` restart action. After a Rust rebuild, SASE checks that `sase-core-rs` exposes
  every binding required by the host checkout. A failed check reports the missing
  bindings and remedy, and neither the CLI nor the TUI restarts onto the incompatible
  extension. No-op updates do not restart anything.
- **The Admin Center mirrors the split.** On a highlighted **Plugins** row in the
  Updates tab, `U` updates that installed plugin and `m` switches install mode.
  Pane-wide `u` still runs only the SASE core + plugins update, while pane-wide `A`
  deliberately targets the current supported agent-CLI inventory. Global `,U` opens the
  Update panel from cached snapshots, with a providers row that lists each captured
  provider's version transition and flags manual-only providers by name. Lowercase `e` /
  `s` / `p` choose Everything, SASE, or providers and then confirm with `y`/`n`; capital
  `E` / `S` / `P` plan the same scopes and skip only that confirmation after a runnable
  preview succeeds. Global `,E` is the direct alias for `,U` then capital `E`, with the
  same preview/no-op/error guarantees. The providers leg is still snapshot-gated: it
  includes only provider names from the latest completed automatic check, revalidates
  them live, and never guesses or privileges manual-only providers.
- **`-n|--dry-run`** prints the exact `uv` command or editable-checkout plan that would
  run and exits `0` without changing anything. uv itself has no dry-run, so sase
  resolves and prints the managed plan itself.
- **`-j|--json`** emits `schema_version: 4` with a stable, sorted payload. Managed
  outcomes are reported under `managed`; editable-checkout plans/results are reported
  under `dev`; `mode` is `managed`, `dev`, or `mixed`; `restart` reports whether the
  scheduler was restarted, skipped, or failed, including `skipped_core_bindings` when
  the extension failed verification. Dev results include `core_bindings_verified` as
  true, false, or null when no check ran. The dry-run JSON reports `dry_run: true`, the
  planned command or dev plan, and each package's current version.
- **Installed shell-completion scripts are refreshed after a successful upgrade**, so a
  stamped script does not drift behind the CLI it completes. A successful update
  regenerates, `zcompile`s, and re-stamps every previously installed script, adds a
  `completion_refresh` object to the JSON payload, and reports failures without failing
  the update itself. See [Shell Completion](completion.md#refresh-existing-installs).
- A no-op run (nothing to upgrade) renders a clean "Already up to date" state and still
  exits `0`.
- The authoritative record of what is in sase's environment is uv's own
  `uv-receipt.toml`, not anything sase stores. `sase update` moves the whole environment
  forward at once; to install or upgrade individual plugins, use
  [`sase plugin install` / `sase plugin update`](#installing-and-updating-plugins-sase-plugin-install-sase-plugin-update).

### Dev / editable installs

When sase or a plugin is present in the uv tool environment as an **editable / dev
install** (for example `uv tool install -e` against a local git checkout),
`uv tool upgrade` cannot move it forward. `sase update` detects those editable
requirements from the receipt and upgrades each one in place from git instead:

- The run computes a mode of `managed` (only registry packages), `dev` (only editable
  checkouts), or `mixed` (both), and handles each part with the matching backend.
- For every editable checkout it runs `git fetch`, then a preflight: a checkout is
  **actionable** only when it is clean and strictly behind its upstream. Checkouts that
  are dirty, diverged, detached, ahead, or have no upstream are skipped with a printed
  reason instead of being touched.
- Actionable checkouts are advanced with `git merge --ff-only`, then reconciled into the
  environment — `uv tool install` for Python packages and `just rust-install-uv-tool`
  for the Rust core (`sase-core-rs`).
- A wheel-installed `sase-core-rs` is reconciled as managed work even though it is a
  transitive dependency rather than a top-level uv receipt requirement. Current or
  safely skipped editable checkouts stay visible in the plan but do not block that
  core-wheel update.
- After any changed update (managed or dev), `sase update` restarts the scheduler so the
  new code is picked up by background work.

A normal `uv tool install sase` user is unaffected by this path, while a contributor
running editable installs gets the same one-command update. `-n|--dry-run` previews the
planned git/uv commands for both modes, and the `-j|--json` payload (schema version `2`)
reports per-root dev outcomes alongside the managed package outcomes.

#### The code-swap lock

Fast-forwarding an editable checkout swaps the source tree out from under anything
already importing from it. A process that has imported some modules and not yet imported
others can end up mixing pre-swap and post-swap code. SASE guards that with an advisory
lock at `~/.sase/locks/code-swap.lock`, with per-holder records under
`~/.sase/locks/code-swap.holders/`. It has two kinds of holder, and the distinction
matters:

- **Blocking readers.** `sase bead work` takes a shared lock for its whole run. While it
  holds one, `sase update` cannot take the exclusive lock its editable swap needs, so
  the update stops before touching anything. Each actionable editable package is
  reported with status `failed` and a reason that begins `deferred:`, and the command
  exits non-zero without having changed anything — re-run it later rather than treating
  it as a broken checkout:

  ```text
  deferred: <holder> is running against this checkout; re-run `sase update` when it finishes
  ```

  In the Admin Center's Updates tab the same condition disables the update instead:

  ```text
  A sase bead work is running against this checkout (<holder>). Re-run the update after it finishes.
  ```

  A direct `sase bead work` started while a swap is already in progress exits non-zero
  without starting any work, rather than importing a torn tree. The host-owned launcher
  used after an approved epic is the deliberate exception: a package-free bootstrap
  waits for the swap to finish before importing SASE, then hands its shared lock to
  `sase bead work` for launch orchestration. It prints
  `sase: waiting for the source-tree swap to finish before launching` while queued.

- **Advisory readers.** A long-lived agent runner registers as advisory for the lifetime
  of its execution loop. Advisory holders never take the shared lock, so they can never
  defer a swap and are never counted as blocking one. Instead, `sase update` and the
  Admin Center's update preview print an informational line —
  `N agent runner(s) are running from this checkout and a swap now can break their deferred imports.`
  — so you can decide whether to wait. A runner is deliberately not allowed to block an
  update indefinitely.

Ordinary readers and the writer remain non-blocking and fail fast rather than queueing:
a waiting reader may already hold pre-swap imports, and a waiting writer would stall
sase's TUI. The approved-epic bootstrap can wait safely because it has not imported the
editable package yet. Set `SASE_DISABLE_CODE_SWAP_LOCK=1` to bypass the mechanism
entirely (both the barrier and the warning). Direct readers still have one accepted
residual race: one that starts while a swap is already underway can import torn modules
before it reaches the lock. The guarded approved-epic path closes that race for its own
launch.

### Install mode switching

`sase update -t/--to dev|pypi` switches the whole install between the two modes instead
of updating within one:

- **`--to dev`** establishes the dev (editable) state for you: it clones (or
  fast-forwards) the SASE checkouts, runs the editable reinstall, and rebuilds the local
  `sase-core-rs` extension. Dev checkouts materialize owner-nested under the
  `update.dev_root` config key (default `~/projects/github`) as
  `<dev_root>/<owner>/<repo>` — for example `~/projects/github/sase-org/sase` — cloned
  via SSH URLs. Legacy flat `~/projects/git/<repo>` checkouts are no longer reused; SASE
  warns about them, and you can either set `update.dev_root` or move the tree into the
  owner-nested layout.
- **`--to pypi`** returns the install to managed mode, reinstalling published wheels
  through `uv`.
- Switching to the mode you are already in is a no-op. `-n|--dry-run` previews the plan;
  without `-y|--yes` an interactive confirmation is required, and cancelling exits
  non-zero. A changed switch restarts the scheduler (and sase's TUI plus the service
  host when driven from the Updates tab) through the shared restart path.
- **In the Admin Center Updates tab, highlight a Plugins row and press `m`** to switch
  mode interactively: it shows the current mode and dev root, confirms, runs the switch
  as a proc, and shows a restart toast.

## Installing and updating plugins (`sase plugin install` / `sase plugin update`)

`sase plugin install <plugin>` adds a plugin to the **same** uv tool environment as
`sase`, so its entry points are discovered the next time `sase` runs.
`sase plugin update <plugin>` upgrades one already-installed plugin (and `-a|--all`
upgrades every installed plugin), leaving `sase` core pinned. Both build on the same
`uv tool` engine as `sase update` and share its install-method requirement and
beautiful, copy-pasteable output.

```bash
# Install (resolved through the GitHub catalog)
sase plugin install github          # `github` -> the `sase-github` distribution
sase plugin install sase-github     # repo name also works
sase plugin install github -g       # install from the plugin's git repository
sase plugin install github -n       # dry run: preview the uv command, change nothing
sase plugin install 'sase-foo==1.2' # a raw requirement / git URL / path is passed through verbatim

# Update
sase plugin update github           # upgrade one installed plugin (sase core stays pinned)
sase plugin update -a               # upgrade every installed plugin
sase plugin update github -n        # dry run
sase plugin install github -j       # stable machine-readable JSON (also on update)
```

- **Name resolution.** A bare `<plugin>` is resolved through the catalog (`github` →
  `sase-github`), so the short name, repo, or `owner/repo` full name all work. A value
  that already looks like a requirement, git URL, or local path (`==`, `git+…`, `…://…`,
  `/path`) is passed through to uv verbatim. An unknown name prints ranked
  `did you mean…?` suggestions and exits non-zero.
- **Index-first resolution with a definitive git fallback.** By default a catalog hit is
  installed from its published distribution (PyPI). It automatically falls back to
  `git+<repository>` only when public PyPI gives a definitive "not found" (an HTTP 404)
  for that distribution — an unreachable index, a timeout, or any other transient
  failure keeps resolving from the index instead of silently switching source on an
  outage. Pass `-g|--git` to force the repository install regardless of index state; a
  forced `--git` never probes PyPI. The resolved `source` (`catalog`, `git`, or
  `passthrough`) is reported in `-j|--json` output and sase's TUI install confirmation.
- **The receipt is the source of truth.** uv's `--with X` _replaces_ the injected set
  rather than appending to it, so both commands reconstruct the **full** `--with` set
  from sase's `uv-receipt.toml` — faithfully preserving existing plugins, editable/dev
  installs, version specifiers, and extras — before re-running `uv tool install`.
  `update` additionally passes `--upgrade-package <name>` per target so only those
  plugins move while everything else is pinned; this is why "update plugins" never
  silently bumps `sase` core (use the comprehensive `sase update`, which also
  re-resolves a managed core wheel in editable/dev mode, for that).
- **Install method is required**, exactly as for `sase update`: the commands only work
  when sase was installed with `uv tool install sase`, and otherwise fail fast with an
  actionable message instead of touching the environment.
- **Idempotent install.** Installing a plugin that is already injected prints "already
  installed" and points at `sase plugin update <plugin>` rather than re-running uv.
  Updating a plugin that is **not** installed points at `sase plugin install <plugin>`
  instead.
- **`-n|--dry-run`** prints the exact `uv` command (and, for install, the resulting
  plugin set) and exits `0` without changing anything. **`-j|--json`** emits a stable,
  sorted payload with `schema_version`, the resolved `command`, and per-package
  outcomes; **`-r|--refresh`** refetches the catalog before resolving a name.
- **Restart after real package changes.** Like `sase update`, `sase plugin install`,
  `update`, and `uninstall` restart the scheduler from the CLI when uv actually changed
  installed packages, and show an operation-specific post-restart toast when driven from
  sase's TUI. The JSON payload carries the same restart status shape as `sase update`.
- **Command-aware lifecycle.** Every install, update, and uninstall diffs the mounted
  `sase <name>` command set around the `uv` mutation. Added commands are announced in
  the result panel with a `❯ sase <name>` chip, their summary, and a
  `Try it: sase <name> --help` hint; removed commands are announced with the chip and a
  removal note. When the command set changed, shell completion is refreshed in a fresh
  child process (best-effort, like `sase update`: a failure never fails the mutation and
  prints a `sase completion refresh` retry). The `-j|--json` payload carries
  `command_changes` (`added`/`removed`/`updated`, each with `name`, `distribution`, and
  `version`) and `completion_refresh`.

### Removing a plugin (`sase plugin uninstall`)

`sase plugin uninstall <plugin>` removes one installed plugin from the **same** uv tool
environment as `sase`, so its entry points are no longer discovered the next time `sase`
runs. It reconstructs uv's `--with` set from the receipt with the target omitted, so
sase core and every other plugin (including editable/dev installs) are preserved.

```bash
sase plugin uninstall github        # resolve the target straight from the receipt
sase plugin uninstall sase-github   # repo name also works
sase plugin uninstall github -n     # dry run: preview the uv command, change nothing
sase plugin uninstall github -j     # stable machine-readable JSON
```

- **Receipt-first resolution.** Unlike `install`, the target is resolved straight from
  sase's `uv-receipt.toml`, so an installed community plugin that is absent from the
  catalog still resolves with no network call. (Pass `-r|--refresh` to refetch the
  catalog when you want catalog-based name resolution.) There is no `-g|--git` flag.
- **No-op success.** Uninstalling a plugin that is **not** installed is a no-op that
  still exits `0` — explicitly unlike `update`, which points a not-installed target at
  `sase plugin install`. An unknown name still prints ranked `did you mean…?`
  suggestions and exits non-zero.
- **Install method is required**, exactly as for `sase update` and the other
  `sase plugin` mutations: it only works when sase was installed with
  `uv tool install sase`, and otherwise fails fast with an actionable message.

## Related

- [Plugins](plugins.md) — groups, catalog, and disable switches.
- [Command plugins](plugins-commands.md) — mounted `sase <name>` commands.
- [Integrations](index.md) — other integration pages.
