---
create_time: 2026-07-08
updated_time: 2026-07-08
status: research
---

# `sase doctor` Diagnostic Improvements

## Research Question

`sase doctor` is the support front door for a tool with many prerequisites. The highest-value
improvements are checks that reveal a concrete SASE capability that is missing because a prerequisite
is absent, stale, unauthenticated, or misconfigured. This note consolidates the two July 2026
research passes and verifies the strongest claims against the current source.

## Current Baseline

`sase doctor` is already a solid read-only diagnostic framework. The registry in
`src/sase/doctor/runner.py:53-82` wires runtime, config, LLM provider, plugin, AXE, project,
workspace, agent-index, bead, telemetry, deep, and optional-tool checks. Checks return stable
`DiagnosticCheck` rows with `OK | WARN | ERROR | SKIP` status.

Existing strengths worth preserving:

- `llm.default` resolves the selected provider and executable, but explicitly reports auth as not
  verified (`src/sase/doctor/checks_providers.py:47-49`).
- Config checks already catch silent model-alias and `%model` routing drift.
- `axe.chops` already aggregates Telegram chop diagnostics, including env vars, token sources, and
  `pass` (`src/sase/axe/chop_doctor.py:169-317`). Do not duplicate Telegram checks elsewhere.
- `tools.optional` is deep-only and currently covers `tmux`, `bat`, `kitten`, `mpv`, `pdftoppm`,
  `pandoc`, PDF engines, and `prettier` (`src/sase/doctor/checks_tools.py:25-43`).
- `state.paths` checks existence and writability for important directories, but not capacity
  (`src/sase/doctor/checks_runtime.py:222-267`).

Design constraints from the original MVP note still hold: keep default checks fast and read-only;
skip unused optional integrations; warn only when a real capability is degraded; reserve `ERROR` for
required or explicitly enabled workflows that are blocked; never emit secret values.

## Verified Gaps

### 1. Provider auth is the largest runtime blind spot

`llm.default` checks provider CLI presence but never checks whether the CLI can authenticate. Agent
execution later spawns provider processes; an installed-but-logged-out provider therefore fails late
inside a run rather than during doctor. This is a hard blocker for normal `sase run` use, but doctor
currently only says auth was not verified.

Recommended diagnostic:

- ID: `llm.auth`
- Mode: default, but offline-only
- Status: `OK` when the selected provider CLI is present and local credential evidence or a relevant
  API-key env var is present; `WARN` when the CLI is present but no local auth evidence is found;
  `SKIP` when `llm.default` already reports the CLI missing.
- Implementation: provider-declared metadata, not an `if provider == ...` ladder. Add registry or
  hook metadata for offline credential paths and API-key env vars. Reuse existing provider auth
  setup hints in `_PROVIDER_SETUP_HINTS`.
- Important limitation: file presence proves only "probably configured", not "valid token". Keep
  `auth_verified=false` unless a provider-owned bounded status command can verify auth without an
  LLM call, quota use, or interactive login.

### 2. Canonical uv-tool install readiness is not diagnosed

Plugin install/update/uninstall and update workflows are built around the running `sase` being a
canonical `uv tool install sase` environment. The pure detector already exists:
`src/sase/uv_tool/detect.py:1-140` checks `uv` on PATH, `sys.prefix` under the uv tool `sase`
environment, and `uv-receipt.toml`. Plugin install/update paths call `probe_uv_tool_install`
(`src/sase/plugins/_operations_install.py:117-131`, `src/sase/plugins/cli_update.py:58-86`).

Recommended diagnostic:

- ID: `install.management` or `runtime.install_management`
- Mode: default
- Status: `OK` for a confirmed uv-tool install; `WARN` for pip, pipx, dev venv, missing `uv`, wrong
  prefix, or missing receipt. Doctor should not error because normal CLI use can still work.
- Reveals: `sase update`, plugin management, Admin Center update flows, and chat-driven install/update
  workers will not be available or reliable from this environment.
- Data: `uv_path`, `tool_dir`, `sys_prefix`, `receipt_path`, `reason`, `managed`.

### 3. Free disk space is unchecked before workspace cloning

Numbered workspaces are real `git clone`s. `_ensure_git_clone_at` runs `git clone` and raises
`RuntimeError` on failure (`src/sase/workspace_provider/utils.py:252-280`), and
`ensure_workspace_checkout` calls that path for materialization (`:304-339`). A full disk therefore
hard-fails agent launch. Current `state.paths` can say a directory is writable while it has
insufficient free space.

Recommended diagnostic:

- ID: `resources.disk_free`
- Mode: default
- Status: `ERROR` if the workspace root has less than roughly 1 GB free; `WARN` below roughly 3 GB;
  `OK` otherwise. Include `sase_home` as a secondary path.
- Next steps: free space or run `sase workspace cleanup`; mention that live workspaces can consume
  hundreds of MB to over 1 GB after checkout and `.venv` creation.

### 4. Editor readiness is not checked despite being used in core workflows

Commit editing uses `$EDITOR`, then `nvim`, then `vim`
(`src/sase/workflows/commit/editor_utils.py:7-30`). Prompt and ACE editor paths have similar but not
fully centralized logic (`src/sase/main/query_handler/_editor.py`, `src/sase/ace/tui/actions/agent_workflow/_editor.py`).
Doctor does not verify that the selected editor command can execute.

Recommended diagnostic:

- ID: `tools.editor`
- Mode: default
- Status: `OK` when `$VISUAL`/`$EDITOR` or `nvim`/`vim` resolves; `WARN` when the selected command
  head is missing or only an unverified shell command was configured.
- Implementation: create one shared editor resolver and reuse it from doctor and editor call sites.
  Explicitly support commands like `code --wait` if SASE wants to treat them as valid.

### 5. Centrally used tools are hidden in deep-only optional coverage

`tmux` is not an agent-runtime dependency: agents are started with `subprocess.Popen`
(`src/sase/axe/_process_start.py:99`). But `sase ace --tmux` hard-exits with code 2 when `tmux` is
missing (`src/sase/main/ace_tmux.py:42-51`), and tmux enables workspace windows, inline artifact panes,
and artifact zoom.

Clipboard is similarly central. `clipboard_available()` already exists
(`src/sase/core/clipboard.py:52-54`), but no top-level doctor check uses it. Missing clipboard
helpers disable copy/yank workflows; some TUI vim-style yanks can fail without an obvious user-facing
message.

Recommended diagnostics:

- Promote `tools.tmux` to default: `WARN` if missing, not `ERROR`.
- Promote `tools.clipboard` to default: reuse `clipboard_available()`, with platform-aware next steps
  (`wl-clipboard`, `xclip`, `xsel`, or `pbcopy`).
- Keep niche artifact/rendering tools deep.

### 6. Mobile push / FCM config can be enabled but incoherent

The mobile gateway config has `push_provider`, `fcm_project_id`, service-account path, credential-env,
and dry-run fields (`src/sase/integrations/mobile_gateway.py:31-47`). Launch prep appends FCM flags only
when values are non-empty (`:155-164`), so `push_provider: fcm` with no project or credential source is
passed through without Python-side coherence validation. The gateway binary resolver also is not
preflighted by doctor (`:273-286`).

Recommended diagnostics:

- `integrations.mobile_push_config`, default: `SKIP` when push is disabled; `OK` for `test`,
  `fcm_dry_run`, or complete FCM config; `ERROR` when `fcm` is selected but project ID or credential
  source is missing.
- `integrations.mobile_gateway_binary`, deep: `SKIP` when mobile is unused; `WARN` when the gateway is
  configured but no `sase_gateway` command resolves.
- No MCP diagnostic: MCP is not implemented in this repo.

### 7. Node/npm setup readiness is conditional but real

Provider setup hints for `claude`, `codex`, and `qwen` use `npm install -g`
(`src/sase/doctor/checks_providers.py:19-45`), but doctor does not check `node` or `npm`. Node is not
a universal SASE runtime requirement, so an unconditional warning would be noisy.

Recommended diagnostic:

- ID: `runtime.node`
- Mode: default
- Status: `WARN` only when `node`/`npm` is missing and an npm-distributed provider is registered but
  its CLI is not found; otherwise `SKIP` or `OK`.

### 8. `fzf` is only covered by `sase prompt doctor`

`fzf` gates prompt pickers and editor prompt history. The editor path explicitly prints an error when
`fzf` is not installed (`src/sase/main/query_handler/_editor.py:150-156`). Top-level doctor and
`tools.optional` do not mention it.

Recommended diagnostic:

- ID: `tools.fzf`
- Mode: default if top-level doctor is meant to be first-run readiness; otherwise deep. Either way,
  it should be in `sase doctor`, not only `sase prompt doctor`.
- Status: `WARN` when missing.

### 9. Chezmoi mode has two blind spots

`use_chezmoi` defaults false, but when enabled SASE remaps home-managed config writes into the
chezmoi source and applies them with `chezmoi apply`. If `chezmoi` is missing, some paths can no-op
or defer the real failure. Skills also compare against the chezmoi source, so the source can appear
current while applied home copies are stale or missing.

Recommended diagnostics:

- `resources.chezmoi`, deep and conditional: `SKIP` unless `use_chezmoi` is true or the source tree
  exists; `ERROR` when enabled but `chezmoi` is missing; `WARN` for suspicious source state.
- `config.skills.applied`, deep and chezmoi-only: stat the real home skill targets and advise
  `chezmoi apply` when source and applied state diverge.

### 10. Editor/LSP and terminal graphics checks would explain optional UX loss

`sase lsp` resolves `SASE_XPROMPT_LSP_CMD`, venv/PATH `sase-xprompt-lsp`, sibling `sase-core` build
outputs, or a `cargo run` fallback (`src/sase/integrations/xprompt_lsp.py:68-125`). Doctor does not
mirror this resolution, so missing editor completions/diagnostics are unexplained.

Inline image/PDF/Markdown artifact viewing depends on `kitten`, terminal support for the kitty
graphics protocol, and inside tmux often tmux >= 3.3 with passthrough. `kitten` is checked only as a
deep optional tool; there is no tmux version gate.

Recommended diagnostics:

- `tools.xprompt_lsp`, deep: mirror the resolver read-only; `WARN` if no server command resolves or
  only the slow cargo fallback is available.
- `terminal.kitty_graphics` and `tools.tmux_version`, deep: explain missing inline artifact rendering
  and old tmux passthrough failures.
- `terminal.truecolor`, deep and low priority: warn only when image-preview fidelity matters.

### 11. Host limits are useful deep/informational checks

ACE inotify watchers have a per-instance watch cap and silently fall back to polling on failure; low
`RLIMIT_NOFILE` / process limits can also hurt multi-agent sessions. These are real but self-healing
or uncommon.

Recommended diagnostics:

- `resources.ulimits`, deep: compare soft `RLIMIT_NOFILE` / `RLIMIT_NPROC` against a floor derived
  from configured runner concurrency.
- `resources.inotify`, deep Linux-only: read `/proc/sys/fs/inotify/*`; warn when watch/instance limits
  are likely to force polling.

### 12. Existing prettier signal needs repair

`prettier` is already checked in deep mode, but the impact is understated. When missing,
`config.init` can report broad skill overwrite drift because generated skill files are rendered
without the same formatting as deployed files. Broaden the optional-tool description and label the
`config.init` false-drift case ("stale counts may be inflated: prettier missing").

## Ranked Recommendations

| # | Recommendation | Mode | Reveals | Status | Effort | Severity |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `llm.auth` offline credential evidence | default | Installed but unauthenticated provider; all runs fail late | WARN / OK / SKIP | Med | High |
| 2 | `install.management` uv-tool readiness | default | Update and plugin-management features unavailable in this environment | WARN / OK | Low | High |
| 3 | `resources.disk_free` | default | Workspace clone fails at agent launch on full disk | ERROR / WARN / OK | Low | High |
| 4 | `tools.editor` shared editor resolver | default | Commit/prompt/ACE editor workflows fail because no executable editor resolves | WARN / OK | Med | Medium |
| 5 | Promote `tools.tmux` and `tools.clipboard` | default | `ace --tmux` hard-exit, degraded artifact UX, copy/yank failures | WARN / OK | Low | Medium |
| 6 | `integrations.mobile_push_config` | default, skips off | FCM selected without project/credentials; mobile push silently unavailable | ERROR / OK / SKIP | Low | Medium |
| 7 | `runtime.node` conditional setup check | default | User cannot follow npm-based provider install hints | WARN / OK / SKIP | Low | Medium |
| 8 | `tools.fzf` | default or deep | Prompt pickers/history disabled, currently only in `sase prompt doctor` | WARN / OK | Low | Medium |
| 9 | `integrations.mobile_gateway_binary` | deep | Mobile bridge configured but gateway binary missing | WARN / OK / SKIP | Low | Medium |
| 10 | `resources.chezmoi` and `config.skills.applied` | deep, conditional | Config writes/skill deploys fail or are unapplied in chezmoi mode | ERROR / WARN / SKIP | Med | Medium |
| 11 | `tools.xprompt_lsp`, `terminal.kitty_graphics`, `tools.tmux_version` | deep | Editor LSP and inline artifact rendering unavailable | WARN / OK | Low-Med | Low-Med |
| 12 | `resources.ulimits`, `resources.inotify`, `terminal.truecolor` | deep | Low host limits, stale polling fallback, lower-fidelity previews | WARN / OK / SKIP | Low | Low |
| 13 | Fix prettier false-drift messaging | existing checks | Doctor's own skill drift signal is noisy when prettier is missing | n/a | Low | Low |

## Do Not Add Yet

- Generic network/PyPI reachability: telemetry and GitHub already check the endpoints SASE actually
  owns; provider CLIs own their own network behavior.
- MCP diagnostics: no MCP feature exists in this repo.
- `rg` or `delta` checks: they appear in docs or prior expectations, but current runtime call sites
  were not verified. Add only when tied to a concrete SASE workflow.
- Provider auth smoke prompts: they can consume quota, mutate provider history, hang on interactive
  login, and violate default doctor expectations.
- Duplicate `pass` checks: Telegram token fallback is already covered through `axe.chops` when
  Telegram chops are installed/configured.

## Implementation Notes

- Split `tools.optional` into a small default "core UX tools" set and a deep "artifact/rendering
  extras" set. This avoids hiding central failures behind `--deep`.
- Add a `resources` group for disk, limits, inotify, and chezmoi environment checks.
- Keep provider auth metadata provider-declared to preserve uniform runtime treatment and plugin
  extensibility.
- Every new check should have focused tests under the existing doctor test shape: mocked probes,
  deterministic `DiagnosticCheck` payloads, and explicit `SKIP` coverage for opt-out/default states.
