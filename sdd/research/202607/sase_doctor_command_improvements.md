---
create_time: 2026-07-08
updated_time: 2026-07-08
status: research
---

# `sase doctor` Improvement Research: New Diagnostics for Unfulfilled Requirements

## Research Question

`sase doctor` is the first-line support command for a system with many required and optional
prerequisites. What **new diagnostics** should it surface that genuinely reveal *missing
functionality caused by an unfulfilled requirement* — i.e. cases where a user's SASE install
silently loses a capability (or hard-fails late) because something is not installed, not
authenticated, not configured, or the host lacks a resource? This note ends with a ranked set of
recommended improvements.

## Method

1. Read the entire `src/sase/doctor/` module (20 check files + `runner.py` + the shared
   `src/sase/diagnostics/` framework) to inventory current coverage.
2. Read the original MVP design note
   (`sdd/research/202606/sase_doctor_command_consolidated.md`) to recover the design constraints the
   command must keep honoring.
3. Ran five parallel code-exploration passes over the highest-value gap areas (provider auth,
   tmux/terminal, notifications/integrations, skills/tooling deployment, system resources), each
   returning file:line evidence and a severity judgment.
4. Spot-verified the most consequential claims directly against source (agent spawn path,
   `git clone` failure path, tmux hard-exit, FCM flag handling, `fzf` editor gate).

All findings below cite source. Nothing was modified.

---

## 1. What `sase doctor` Already Covers

The command is a fast, read-only aggregator. Checks are registered in
`src/sase/doctor/runner.py:53-83` and produce a `DiagnosticCheck` with a status of
`OK | WARN | ERROR | SKIP` (`src/sase/diagnostics/models.py:13`). `--deep` adds slower read-only
checks; `-C/--check` selects a check id or group.

**Default checks**

| Group | Check id | What it verifies |
| --- | --- | --- |
| runtime | `runtime.version` | Host/core/plugin package inventory + package warnings |
| runtime | `runtime.core` | `sase_core_rs` loads; backend probes pass |
| runtime | `runtime.environment` | Python ≥ 3.12; editable install / source-root drift |
| state | `state.paths` | `sase_home`, config dir, projects dir, workspace root exist / writable |
| vcs | `vcs.git` | `git` on PATH; repo `user.name` / `user.email` set |
| config | `config.layers` | Config layers load; unsupported/deprecated keys |
| config | `config.init` | Init planner drift (memory, sdd, **skills**) |
| config | `config.sdd` | SDD link validation (when an SDD tree exists) |
| config | `config.model_aliases` | Stale/mis-nested model-alias config that silently reroutes to default |
| config | `config.model_xprompts` | `%model` preset tokens that silently fall back to the default provider |
| config | `config.xprompt_definitions` | XPrompt definition problems |
| llm | `llm.registry` | Provider plugin metadata loads; ≥ 1 provider registered |
| llm | `llm.default` | Effective default provider resolves; **CLI executable found on PATH** |
| plugins | `plugins.resources` | Resource entry-point load failures / disabled-by-env |
| plugins | `plugins.github` | `gh` present + `gh auth status` (only if a GitHub plugin is installed) |
| axe | `axe.chops` | Chop diagnostics — **includes Telegram env / bot-token / `pass`** |
| project | `project.current` | Current project state / launchable / claims |
| workspace | `workspace.registry` | Workspace registry integrity vs. on-disk checkouts |
| state | `state.agent_index` | Agent artifact index health (lightweight) |
| project | `project.beads` | Bead store health + git sync cleanliness |
| ops | `ops.telemetry_status` | Telemetry enablement + endpoint reachability |

**Deep checks**: `state.agent_index_verify`, `ops.axe` (lumberjack state), `providers.cli_version`
(`--version` probes), `ops.telemetry_health` (Prometheus), `tools.optional` (tmux, bat, kitten, mpv,
pdftoppm, pandoc, a PDF engine, prettier).

**Notable existing strengths relevant to this research.** The config checks already catch two
*silent-degradation* classes precisely: a removed model alias that reroutes every `#agy_*` preset to
the default provider (`checks_config_model_xprompts` at
`src/sase/doctor/checks_config_xprompts.py:24-71`) and stale alias config that "silently falls
through at launch" (`checks_config_model_aliases.py:12-30`). Telegram notification prerequisites
(bot token via env / `~/.sase/telegram_bot_token` / `pass`) are fully covered via the `axe.chops`
check, which even escalates WARN → ERROR when Telegram is marked enabled but no token resolves
(`src/sase/axe/chop_doctor.py:169-317`). These are the *pattern to copy* for the gaps below.

## 2. Design Constraints Any New Check Must Respect

From the MVP note (`sdd/research/202606/sase_doctor_command_consolidated.md`) and the repo
conventions:

- **Read-only and fast.** No LLM calls, no API-consuming smoke prompts, no state mutation. Bounded
  subprocesses with short timeouts only where no in-process API exists.
- **Quiet about opt-outs.** Optional integrations should `SKIP` when unused, `WARN` when configured
  but degraded, and `ERROR` only when a required workflow is actually blocked.
- **Actionable.** Every `WARN`/`ERROR` names an exact next-step command or config key.
- **No secrets.** The report is a support artifact; redaction already exists
  (`src/sase/diagnostics/models.py:180-199`). New checks must pass booleans/paths, never token
  contents.
- **Uniform runtimes** (`CLAUDE.md` gotcha). Do **not** hard-code per-runtime special cases. Any new
  provider-auth check must be driven by provider-declared metadata (registry/hookspec), not an
  `if provider == "claude"` ladder.
- **Rust-core boundary.** Verdicts another frontend would need to match belong in provider metadata
  / `sase-core`, with Python orchestrating and presenting. A read-only local filesystem `stat` is
  fine to do in Python; the *knowledge of which path to stat* should be provider-declared.

## 3. Gap Analysis — New Diagnostics That Reveal Missing Functionality

Each gap below is a place where a real capability is lost when a requirement is unmet, and where
`sase doctor` is currently silent. Ordered by theme; ranked in §4.

### 3.1 Provider authentication is never verified (biggest gap)

`llm.default` deliberately checks only that the provider CLI is *on PATH*. It stamps every result
with `auth: not verified (doctor is read-only and does not call provider APIs)`
(`src/sase/doctor/checks_providers.py:47-49`, `:177`, `:267`).

**How this fails today — hard, late, and cryptic.** Agents are launched by spawning the provider
CLI via `subprocess.Popen` (e.g. `claude.py:223-315`, `codex.py:342-468`). An installed-but-
unauthenticated CLI runs, exits non-zero, and the error is wrapped into an `LLMInvocationError`
inside a *failed agent run's* artifacts — not at doctor time. So a user whose `claude`/`codex`/`qwen`
login expired sees a broken run, not a clear "you are logged out" signal. **Installed-but-
unauthenticated is a hard blocker for every `sase run`.**

**A read-only, offline check is feasible for every provider** by stat-ing well-known credential
files (or detecting an API-key env var), with no network and no subprocess:

| Provider | Offline credential evidence |
| --- | --- |
| claude | `~/.claude/.credentials.json` (OAuth) **or** `ANTHROPIC_API_KEY` |
| codex | `~/.codex/auth.json` (`CODEX_HOME` confirmed at `codex.py:131,194`) **or** `OPENAI_API_KEY` |
| opencode | `~/.local/share/opencode/auth.json` (or `opencode auth list`, which is offline) |
| qwen | `~/.qwen/oauth_creds.json` / `~/.qwen/settings.json` **or** API-key env |
| agy | `~/.gemini/oauth_creds.json` / `~/.gemini/antigravity-cli/antigravity-oauth-token` |

There is precedent for verifying auth read-only in doctor: `plugins.github` already runs
`gh auth status` (`checks_plugins.py:138-196`).

**Proposed — `llm.auth` (group `llm`, default mode).** For the resolved default provider (reuse
`get_default_provider_name()` and `_provider_readiness`), test
`credential_file_exists OR api_key_env_set`.
- `OK` — CLI present and a credential file or API-key env var is present.
- `WARN` (not ERROR) — CLI present but no credential evidence. WARN is correct: env-var keys,
  custom `*_HOME` overrides, and expired-but-present tokens make file-stat *necessary but not
  sufficient*. next_steps reuse the already-present-but-unused `_PROVIDER_SETUP_HINTS[name]["auth"]`
  strings (`checks_providers.py:19-45`), e.g. "run `codex login`".
- `SKIP` — CLI not installed (`llm.default` already reports that; don't double-report).

**Uniformity/boundary note:** add provider-declared metadata (a hookspec such as
`llm_offline_credential_paths()` / `llm_api_key_env_vars()`, or registry fields) so doctor stays
provider-neutral. An MVP could extend `_PROVIDER_SETUP_HINTS` with `cred_paths` / `api_key_envs`, but
the hookspec keeps new plugin providers self-describing.

### 3.2 Node.js / npm is an unchecked install prerequisite

Three of five provider CLIs (`claude`, `codex`, `qwen`) are installed via `npm install -g` — the
doctor's own setup hints hard-code this (`checks_providers.py:21,27,37`) — yet nothing checks for
`node`/`npm`. A user who can't run the install hint gets no signal. (`agy` and `opencode` ship
standalone binaries, so node is *not* universal.)

**Proposed — `runtime.node` (group `runtime`, default).** `shutil.which("node")`/`which("npm")`.
`WARN` only when node/npm is missing **and** an npm-based provider is registered but its CLI is not
found (i.e. only nag when it would actually help); else `SKIP`/`OK`.

### 3.3 tmux and clipboard are hidden behind `--deep` but centrally used

**Verified:** agents run via `subprocess.Popen` (`src/sase/axe/_process_start.py:99`), so **tmux is
not an agent-runtime dependency**. But:
- `sase ace --tmux` (the agent-scripting launcher) **hard-exits `2`** without tmux
  (`src/sase/main/ace_tmux.py:42-51`).
- Interactive UX degrades without tmux: workspace windows (`t` keymap,
  `_panel_tmux.py:214-245`), inline artifact side-panes, and zoom
  (`_panel_artifacts.py:415-441`, `_viewer_tmux.py:61-139`).
- **Clipboard** (`src/sase/core/clipboard.py:11-54`): with no `pbcopy`/`wl-copy`/`xclip`/`xsel`
  backend, `copy_to_system_clipboard` returns `False`. Some TUI call sites toast a failure, but
  vim-style yanks **silently no-op** (`ace/tui/widgets/_vim_visual_ops.py:20`,
  `_vim_normal_operator_exec.py:60-67`).

Both are only reachable today via the deep-only `tools.optional` check, so a first-run user with no
tmux/clipboard sees nothing in a default `sase doctor`.

**Proposed:**
- Promote **`tools.tmux`** to default mode: `WARN` if absent, next_steps naming `sase ace --tmux`,
  workspace windows, and inline artifact panes. (Not ERROR — the core TUI and all agent execution
  work without it.)
- Promote **`tools.clipboard`** to default mode: reuse `clipboard_available()`
  (`clipboard.py:52`), `WARN` if no backend, platform-aware next_steps
  (`wl-clipboard`/`xclip`/`xsel`; `pbcopy` on macOS).
- Lowest-effort implementation is adding both to `_OPTIONAL_TOOLS` and moving them (plus `kitten`,
  below) to a default-mode split of `tools.optional`; keep niche renderers (`bat`, `mpv`,
  `pdftoppm`, `pandoc`, PDF engine) deep.

### 3.4 `fzf` gates interactive pickers and is not in `sase doctor`

Without `fzf`: `sase prompt run --pick` returns nothing with a fallback message
(`src/sase/prompt/cli_run.py:127-133`) and editor prompt-history **hard-fails**
("Error: fzf is not installed…", `src/sase/main/query_handler/_editor.py:150-156`, verified).
`fzf` status is computed today only by the separate, obscure `sase prompt doctor`
(`history/prompt_maintenance.py:213`); it is **not** in `sase doctor` or `tools.optional`.

**Proposed — `tools.fzf`** (group `tools`): `WARN` if missing; next_steps note the disabled pickers.

### 3.5 Mobile push / FCM misconfiguration is a silent no-op

`mobile_gateway.push_provider: fcm` with missing credentials receives **zero Python-side
validation** — flags are appended only when non-empty (verified,
`src/sase/integrations/mobile_gateway.py:150-162`), so an FCM selection with no
`fcm_project_id`/credentials is passed through and push silently never delivers. The gateway binary
(`sase_gateway`) is also never pre-flighted and is not in `tools.optional`. (Telegram notifications,
by contrast, are already covered via `axe.chops`. MCP is not implemented anywhere in the repo —
grep-empty — so no MCP diagnostic is needed.)

**Proposed:**
- **`integrations.mobile_push_config`** (default): `SKIP` when `push_provider == "disabled"` (the
  default); `OK` for `test`/`fcm_dry_run`/complete FCM config; **`ERROR`** when `fcm` is selected but
  `fcm_project_id` is empty or neither `fcm_service_account_json` (existing file) nor
  `fcm_credential_env` (set var) resolves. Report which field is missing (never the secret).
- **`integrations.mobile_gateway_binary`** (deep): mirror `_resolve_gateway_command()` read-only;
  `SKIP` when unused, `WARN` when push is configured-for-use but the binary is unresolvable.

### 3.6 Free disk space is unchecked — full disk hard-fails agent launch

Ephemeral `sase_<N>` workspaces are **real full `git clone`s** (`workspace_provider/utils.py:252-265`);
a failed clone raises `RuntimeError` (`:266-280`, verified) at agent-launch time. Measured cost on
this host: ~0.9 GB working tree + ~0.39 GB `.venv` per workspace, retained for
`cleanup_ttl_days = 14`. `state.paths` checks writability but **not** free space (no
`shutil.disk_usage` anywhere in `src/sase`).

**Proposed — `resources.disk_free` (new group `resources`, default).** `shutil.disk_usage()` on the
resolved workspace `root_dir` and `sase_home`. `ERROR` if free < ~1 GB (can't materialize one
clone); `WARN` if free < ~3 GB; else `OK`. next_steps: free space or `sase workspace cleanup`; note
the ~0.5–1 GB per-workspace cost. This is the one prerequisite whose absence is an unambiguous,
currently-invisible hard failure.

### 3.7 chezmoi enabled-but-missing silently drops config writes

When `use_chezmoi: true` (default `false`), config writes and `sase init` deploys are remapped into
the chezmoi source tree and applied via `chezmoi apply` (`config/targets.py`,
`_init_chezmoi_deploy.py:283-299`). If the `chezmoi` binary is missing, the write path can silently
no-op unless `chezmoi_missing_is_error` is set. No doctor check references chezmoi.

Two related items:
- **`resources.chezmoi`** (deep, conditional): only when `use_chezmoi` or a `CHEZMOI_HOME` source
  exists — verify `chezmoi` on PATH and the source is a git repo. `ERROR` when enabled but missing;
  `SKIP` for everyone else.
- **chezmoi-apply skills blind spot** (deep): `config.init` compares skills against the chezmoi
  *source*, so it reports "current" even when `chezmoi apply` was never run and the applied
  `~/.claude/skills/...` copies are stale/missing. A `config.skills.applied` check would stat the
  real `~` targets in chezmoi mode and advise `chezmoi apply`.

### 3.8 Terminal graphics capability for artifact rendering

Inline `image` / `markdown` / `pdf` artifact modes require `kitten` (kitty graphics protocol) plus a
protocol-capable terminal (`ace/tui/graphics/_viewer_render.py:139-179`); missing `kitten` hard-skips
with a warning. Inside tmux this additionally needs tmux ≥ 3.3 with `allow-passthrough on` — and
there is **no tmux version gate anywhere** in the repo, so an old/misconfigured tmux fails at runtime
with a `kitten_failed` warning. Truecolor (`capability.py:18-23`) affects only Pillow image-preview
fidelity.

**Proposed (all deep, all `WARN`, cosmetic-to-medium):** `terminal.kitty_graphics` (kitten present +
terminal heuristic), `tools.tmux_version` (parse `tmux -V`, warn < 3.3 / advise
`allow-passthrough`), and optionally `terminal.truecolor`.

### 3.9 xprompt LSP / editor integration is unchecked

`sase lsp` powers editor completion/diagnostics for xprompt tokens (the sase-nvim integration). If
neither the `sase-xprompt-lsp` binary, a built `../sase-core/target`, nor `cargo` resolves, `sase lsp`
exits 1 (`integrations/xprompt_lsp.py:68-125`). Editor-only, so low severity, but wholly unchecked.

**Proposed — `tools.xprompt_lsp`** (deep): mirror the resolution order read-only; `OK` if a binary
resolves, `WARN` if only the slow `cargo` fallback or nothing resolves.

### 3.10 Host limits (informational)

- **`resources.ulimits`** (deep): compare `RLIMIT_NOFILE`/`RLIMIT_NPROC` soft limits against a floor
  derived from `max_agent_runners + max_hook_runners` (already read in `checks_deep.py`). `WARN`
  only; usually `OK`.
- **`resources.inotify`** (deep, Linux): ACE live-refresh uses inotify with a per-instance ceiling
  of 4096 × up to 2 instances (`ace/tui/util/fs_watcher.py:65`); exhaustion silently drops to ~60 s
  polling (self-healing). Read `/proc/sys/fs/inotify/*`; `WARN` if low. Lowest priority.

### 3.11 A reliability bug in an existing check (not a new diagnostic)

When `prettier` is missing, `plan_init_skills` renders skill targets unformatted while on-disk
skills were prettier-formatted, so `config.init` reports a spurious `overwrite` for potentially
*every* skill (`main/init_skills_handler.py:534,556,600`). The missing tool thus makes doctor's own
drift signal noisy. `prettier` is also only described in deep `tools.optional` as "Markdown
formatting," understating its real blast radius (agent prompt-wrap width in
`llm_provider/preprocessing.py:171`, precommit formatting). Worth: label the prettier case in
`config.init` ("stale counts may be inflated: prettier missing") and broaden the `tools.optional`
prettier description.

### Explicitly NOT recommended

- A generic internet/PyPI reachability check — telemetry endpoints, GitHub (`gh auth status`), and
  provider CLIs already cover the endpoints SASE actually depends on, and there is no background
  update ping to health-check.
- Any MCP diagnostic — the feature does not exist in this codebase.

---

## 4. Ranked Recommendations

Ranked by (does it reveal genuinely missing functionality) × (how many users it bites) × (how silent
the failure is today) ÷ (implementation cost).

| # | Recommendation | Mode | Reveals | Status | Effort | Severity |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **`llm.auth`** — offline provider credential presence | default | Installed-but-logged-out provider → every `sase run` fails late/cryptically | WARN / OK / SKIP | Med (add provider metadata) | **High** |
| 2 | **`resources.disk_free`** — free space on workspace root + `sase_home` | default | Full disk → `git clone` `RuntimeError` at agent launch, invisible today | ERROR/WARN | Low | **High** |
| 3 | **Promote `tools.tmux` + `tools.clipboard` to default** | default | `sase ace --tmux` hard-exit; silent vim-yank no-ops; degraded artifact UX | WARN | Low | Medium |
| 4 | **`integrations.mobile_push_config`** — FCM coherence | default | `push_provider: fcm` + missing creds → push silently never delivers (zero validation) | ERROR/SKIP | Low | Medium |
| 5 | **`runtime.node`** — node/npm for npm-based providers | default | Can't follow the install hints; no signal | WARN/SKIP | Low | Medium |
| 6 | **`tools.fzf`** — interactive pickers | deep→default | Prompt pickers disabled / editor history hard-fails; only surfaced by obscure `sase prompt doctor` today | WARN | Low | Medium |
| 7 | **`integrations.mobile_gateway_binary`** | deep | Mobile bridge dead with no pre-flight | WARN/SKIP | Low | Medium |
| 8 | **`resources.chezmoi`** + chezmoi-apply skills blind spot | deep | Config writes / skill deploys silently no-op for the chezmoi cohort | ERROR/WARN/SKIP | Med | Medium |
| 9 | **`terminal.kitty_graphics` + `tools.tmux_version`** | deep | Image/PDF/Markdown artifacts silently skip; no tmux version gate exists | WARN | Med | Low–Med |
| 10 | **`tools.xprompt_lsp`** | deep | Editor xprompt completion/diagnostics dead | WARN | Low | Low |
| 11 | **`resources.ulimits` / `resources.inotify` / `terminal.truecolor`** | deep | Concurrency starvation; stale live-refresh; degraded image fidelity (all self-healing/cosmetic) | WARN | Low | Low |
| 12 | **Fix `config.init` prettier false-drift + broaden prettier description** | (existing) | Doctor's own skill-drift signal is unreliable when prettier is missing | — | Low | Low |

### Suggested sequencing

- **Phase 1 (highest ROI, default-mode, cheap):** #1 `llm.auth`, #2 `resources.disk_free`, #3
  promote tmux/clipboard, #5 `runtime.node`. These convert the four most common silent/late failures
  (logged out, full disk, no tmux/clipboard, no node) into early, actionable signals.
- **Phase 2 (opt-in cohorts):** #4 FCM config, #6 `fzf`, #7 gateway binary, #8 chezmoi.
- **Phase 3 (deep completeness):** #9–#11 terminal/host-limit checks, #10 xprompt LSP.
- **Cross-cutting:** introduce a `resources` group and a small provider-capability metadata surface
  (credential paths / api-key env vars) so #1 stays runtime-uniform and boundary-respecting; split
  `tools.optional` so centrally-used tools (tmux, clipboard, kitten) appear in the default run while
  niche renderers stay deep. Each new check ships with the same test shape already used under
  `tests/doctor/`.

## 5. Longer-Term Directions (beyond new diagnostics)

The MVP note already flagged these as post-MVP; they remain the natural next steps once the check set
above lands:

- **`--support-bundle <dir>`** — write the JSON report plus bounded, redacted logs so users can
  attach one artifact when asking for help (the Flutter-doctor "support front door" pattern).
- **`-R/--repair`** — delegate *only* to established safe repair commands named in existing
  next_steps (`just install`, `git config`, `sase workspace repair`, `sase agent index gc`,
  `chezmoi apply`, `sase skill init`), never bespoke mutation.
- **Onboarding entry point** — reference `sase doctor` from agent-launch error paths so a failed run
  points the user at the one command that would have caught the cause.

## Appendix: Verification Notes

Claims spot-checked directly against source on 2026-07-08:

- Agents spawn via `subprocess.Popen` — `src/sase/axe/_process_start.py:99` (tmux is not an
  agent-runtime dependency).
- `sase ace --tmux` hard-exits `2` when tmux is absent — `src/sase/main/ace_tmux.py:42-51`.
- `git clone` failure raises `RuntimeError` — `src/sase/workspace_provider/utils.py:266-280`.
- FCM flags appended only when non-empty; no coherence validation —
  `src/sase/integrations/mobile_gateway.py:150-162`.
- `fzf` missing hard-fails editor prompt-history — `src/sase/main/query_handler/_editor.py:148-156`.
- Provider auth is explicitly "not verified" — `src/sase/doctor/checks_providers.py:47-49`; `codex`
  credential store confirmed via `CODEX_HOME` handling at `src/sase/llm_provider/codex.py:131,194`.
</content>
</invoke>
