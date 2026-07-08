---
create_time: 2026-07-08
updated_time: 2026-07-08
status: research
---

# `sase doctor` Improvement Research

## Research Request

The request was to research how to improve `sase doctor`, especially by finding new diagnostics that reveal real SASE
functionality loss caused by missing prerequisites.

## Bottom Line

`sase doctor` is already a strong support front door. It has a shared diagnostic registry, stable check IDs, selected
checks, deep checks, strict exit behavior, JSON output, runtime/core/config/provider/plugin/project/workspace/state/bead
coverage, and AXE chop diagnostics. The highest-value next improvements are not more generic "is this tool installed?"
rows. They are capability checks that map a failed prerequisite to a specific SASE workflow the user will lose.

The most important gap is install-management readiness: `sase update`, plugin install/update/uninstall, the Admin Center
Updates tab, and chat-driven update workers all depend on the running `sase` being a canonical `uv tool install sase`
environment. The repo already has a pure detector for that condition, but top-level doctor does not report it.

The second strongest gap is editor readiness. The install guide calls a text editor required, and many SASE workflows
fall back to `nvim` then `vim`, but doctor does not verify that the selected editor can actually be executed.

The third gap is that `sase doctor -D` is documented as reporting optional tools, but the current `tools.optional` check
omits several documented or existing optional capabilities: clipboard helpers, `fzf`, mobile gateway binary resolution,
and xprompt LSP server resolution. Conversely, the docs still list `rg` and `delta`, but this repo review did not find
clear current runtime call sites that require either one, so those should not be added as noisy checks until the docs or
implementation are reconciled.

## Current Coverage

Current registry construction lives in `src/sase/doctor/runner.py`. It registers these groups in order:

- `runtime`: package inventory, Rust core health, runtime environment, state paths, git executable and identity.
- `config`: config layers, init planners, SDD validation, model-alias migration, model xprompt routing, xprompt load
  issues.
- `llm`: provider registry and effective default provider executable.
- `plugins`: resource entry-point loading and GitHub plugin `gh auth status`.
- `axe`: configured chop resolution, available-unconfigured chops, and Telegram chop prerequisites.
- `project` / `workspace`: current project and workspace registry.
- `state`: agent artifact index status, with a deep full verify.
- `ops`: telemetry status, deep telemetry health, deep AXE runtime state.
- `providers`: deep provider CLI `--version` probes.
- `tools`: deep optional artifact/formatting tools.

Evidence:

- Registry wiring: `src/sase/doctor/runner.py`
- Optional tools currently checked: `src/sase/doctor/checks_tools.py`
- Deep provider CLI version probes: `src/sase/doctor/checks_deep.py`
- AXE chop aggregation: `src/sase/doctor/checks_axe.py`
- Telegram env/token/pass checks: `src/sase/axe/chop_doctor.py`

Live probe from this checkout:

```bash
.venv/bin/sase doctor -L
.venv/bin/sase doctor -D -j
```

The check list includes 21 default checks and 5 deep checks. The deep JSON run returned useful real findings:

- `axe.chops` was `ERROR` because configured Telegram chop scripts did not resolve in the current environment.
- `config.sdd` was `WARN` with SDD validation warnings.
- `ops.telemetry_health` was `WARN`.
- `state.agent_index_verify` was `WARN` with stale/missing row drift.
- `providers.cli_version` was `WARN` because `opencode` was registered but missing.

That validates the general design: doctor is already capable of surfacing missing functionality when the check is tied
to a real subsystem.

## Gaps Found

### 1. Install Management Is Not Diagnosed

The install guide says `uv tool install sase` is more than a convenience: `sase update`, plugin install/update, and the
Admin Center Updates tab manage the environment through `uv tool` and `uv-receipt.toml`. The code has a precise detector
in `src/sase/uv_tool/detect.py`: a managed install requires `uv` on PATH, `sys.prefix` equal to the uv tool `sase`
environment, and a `uv-receipt.toml`.

Current doctor reports runtime package inventory but does not tell a user that major update/plugin-management features
are disabled because the active executable is from pip, pipx, a dev venv, or a broken uv-tool receipt.

Recommended check:

- ID: `install.management` or `runtime.install_management`
- Mode: default
- Status:
  - `OK` for confirmed uv-tool install.
  - `WARN` for dev venv / pip / pipx / missing receipt, because SASE can still run but update/plugin management is
    unavailable.
  - `ERROR` only if a selected install-management operation is impossible in a context where SASE knows it must be
    managed. Doctor itself probably should keep this as `WARN`.
- Data: `uv_path`, `tool_dir`, `sys_prefix`, `receipt_path`, `reason`, `managed`.
- Next steps:
  - End user: `uv tool install sase --force` or reinstall through the documented command.
  - Dev checkout: `just install` for local work; use a uv-tool install for plugin/update workflows.

Why this is high value:

- It reveals missing functionality before `sase update` or `sase plugin install` fails.
- It reuses existing, tested detection logic instead of probing heuristically.
- It is central to both CLI and TUI update paths.

### 2. Editor Readiness Is Not Diagnosed

The install guide lists "A text editor" as required. Commit-message editing uses `$EDITOR`, then `nvim`, then `vim`.
Prompt editing and many TUI actions also use `$EDITOR` or default to `nvim`. The current doctor does not verify that
the chosen editor command exists.

Relevant code:

- Commit editor fallback: `src/sase/workflows/commit/editor_utils.py`
- Prompt editor fallback: `src/sase/main/query_handler/_editor.py`
- ACE prompt/workflow editor defaults: `src/sase/ace/tui/actions/agent_workflow/_editor.py`

Recommended check:

- ID: `tools.editor`
- Mode: default, because docs classify it as required.
- Status:
  - `OK` when `$VISUAL` or `$EDITOR` is set to an executable command, or `nvim`/`vim` is found.
  - `WARN` when only an unverified shell command is configured but the command head cannot be resolved.
  - `ERROR` only if SASE wants to treat editor-backed workflows as required for first-run readiness. I recommend
    `WARN` to avoid blocking noninteractive users.
- Details:
  - Selected source: `VISUAL`, `EDITOR`, `nvim`, or `vim`.
  - Resolved executable path.
  - Note if code paths disagree on `$VISUAL`; today some paths only consult `$EDITOR`.

Implementation note:

Create one shared editor resolver and reuse it from doctor and editing code. Several code paths currently treat an
editor command as a single argv head, so a value like `code --wait` needs explicit handling if SASE wants to support it
reliably.

### 3. Optional Tool Coverage Does Not Match Documented Capabilities

`INSTALL.md` says `sase doctor -D` reports optional tools. Current `tools.optional` checks:

- `tmux`
- `bat`
- `kitten`
- `mpv`
- `pdftoppm`
- `pandoc`
- one PDF engine: `wkhtmltopdf`, `xelatex`, `pdflatex`
- `prettier`

The install guide also lists:

- `fzf`
- `rg`
- `delta`
- clipboard helper: `pbcopy`, `wl-copy`, `xclip`, or `xsel`
- `pass`
- `node` / `npm`

Findings:

- Clipboard is a real capability. `src/sase/core/clipboard.py` already has `clipboard_available()` and platform-aware
  helper resolution. Missing helpers disable ACE copy actions and some profile-path copying.
- `fzf` is real. `sase prompt select` and prompt-history picker paths depend on it and print a fallback error when
  absent.
- `pass` is already checked through `axe.chops` when Telegram chop scripts are installed or configured. It should not be
  duplicated in `tools.optional` unless the check is careful to avoid double-reporting.
- `node` / `npm` are not SASE runtime requirements when provider CLIs are already installed. They are setup helpers for
  npm-distributed provider CLIs, so doctor should only mention them when no usable provider executable exists and the
  best next setup hint uses npm.
- I did not find a current runtime requirement for `rg` or `delta` in this repo. The docs may be stale, or those tools
  may be planned/indirect. Do not add noisy checks for them until there is a verified code path.

Recommended changes:

- Add `clipboard` and `fzf` to deep optional tool coverage.
- Keep `pass` under `axe.chops`.
- Add conditional `node`/`npm` setup hints to provider checks instead of unconditional optional-tool warnings.
- Reconcile the docs for `rg` and `delta`: either wire them into real workflows or remove them from the authoritative
  optional-tool list.

### 4. XPrompt LSP Server Readiness Is Not Diagnosed

The editor integration is a substantial SASE feature. The docs say `sase lsp` resolves the Rust server through:

1. `SASE_XPROMPT_LSP_CMD`
2. a `sase-xprompt-lsp` binary in the current Python environment
3. `sase-xprompt-lsp` on PATH
4. a sibling `../sase-core` debug/release binary
5. `cargo run --manifest-path ../sase-core/Cargo.toml -p sase_xprompt_lsp --`

This resolver exists in `src/sase/integrations/xprompt_lsp.py`, but doctor does not call it.

Recommended check:

- ID: `editor.lsp`
- Mode: deep, or default with `SKIP`/`OK` only and no warning unless explicitly selected.
- Status:
  - `OK` if the server command resolves.
  - `WARN` if no server command resolves, because ACE still works but editor LSP features are unavailable.
  - `WARN` if `SASE_XPROMPT_LSP_CMD` is set but malformed.
- Data: resolution source, command head, whether fallback requires `cargo`, catalog materialization paths.
- Optional deep probe: run the resolved command with `--version` under a short timeout when `-D` is active.

Why this is useful:

- It directly explains missing editor completions, diagnostics, hovers, and definitions.
- It reuses the same resolver as the actual command, so it will not drift.

### 5. Mobile Gateway Readiness Is Not Diagnosed

The mobile gateway is documented and implemented, but `sase doctor` has no mobile group. `sase mobile gateway start`
fails when the Rust `sase_gateway` binary cannot be resolved. It also has meaningful configuration constraints around
loopback binding and FCM credentials.

Relevant code:

- Gateway launch/config: `src/sase/integrations/mobile_gateway.py`
- Config keys: `mobile_gateway` in `src/sase/default_config.yml` and `src/sase/config/sase.schema.json`
- Docs: `docs/mobile_gateway.md`, `docs/mobile_mvp_runbook.md`

Recommended check:

- ID: `mobile.gateway`
- Mode: deep by default; targeted users can run `sase doctor -D -C mobile.gateway`.
- Status:
  - `SKIP` if the mobile gateway config is entirely default and push provider is disabled.
  - `OK` if a gateway command resolves and configured push settings are internally consistent.
  - `WARN` if the binary is missing, non-loopback binding lacks opt-in, or FCM is selected without project ID or a
    usable credential pointer.
- Read-only details:
  - Resolved gateway command source.
  - Effective bind address and port.
  - Whether port appears already occupied. This should be a non-binding socket/connect check only.
  - FCM credential source presence, never credential contents.

Why this is useful:

- It catches mobile setup failures before a user starts the foreground gateway.
- It avoids warning every non-mobile user by returning `SKIP` for defaults.

### 6. Provider Authentication Remains Mostly Undiagnosed

`llm.default` checks executable presence but explicitly says authentication is not verified. The install guide tells
users at least one provider CLI must be installed and authenticated, so this is an important blind spot.

Do not hardcode provider-specific auth commands in the top-level doctor. Provider auth semantics change, and the SASE
gotchas require uniform runtime treatment. Instead, add an optional provider hook for bounded read-only auth diagnostics.

Recommended shape:

- Provider hook: `llm_doctor_checks()` or a narrower `llm_auth_status()` returning diagnostic rows.
- Top-level check ID: `llm.auth`
- Mode: deep or selected-only at first.
- Status:
  - `OK` when the selected provider's own plugin can verify local auth state without launching an agent or consuming LLM
    tokens.
  - `WARN` when the provider plugin cannot verify auth.
  - `ERROR` only when the selected provider reports a definite unauthenticated state for the default launch path.

Why selected/deep first:

- Auth probes can be slow, networked, or provider-version-sensitive.
- SASE should not call LLM APIs from default doctor.
- Provider plugins should own their own checks.

### 7. Configured Shell Command Readiness Is Not Diagnosed

`precommit_command` is a direct example: if configured and broken, commit workflows fail. The command is arbitrary shell,
so a doctor check cannot prove it will succeed, but it can catch obvious missing command heads and shell syntax errors.

Relevant code:

- `src/sase/workflows/commit/precommit_hooks.py` runs `precommit_command` with `shell=True`.

Recommended check:

- ID: `config.precommit_command`
- Mode: default when configured, otherwise `SKIP`.
- Status:
  - `OK` when empty or syntactically plausible.
  - `WARN` when the first simple command head is not on PATH or shell syntax validation fails.
- Implementation:
  - Use `shlex` only for a best-effort command-head hint.
  - Optionally run `/bin/sh -n` against the command text. That is read-only and avoids executing hooks.
  - Do not try to evaluate aliases, functions, compound shell expressions, or project-specific environment setup.

### 8. Deep Provider CLI Version Env Var Derivation Duplicates Registry Logic

`llm.default` uses the canonical registry helper for provider path env names. The deep `providers.cli_version` check
reimplements the derivation locally. That is low risk for built-in provider names today, but it is an avoidable drift
point for plugin provider names with punctuation or future naming rules.

Recommended fix:

- In `src/sase/doctor/checks_deep.py`, call `llm_registry.provider_path_env_var(provider_name)` instead of keeping a
  local `_provider_path_env()`.

This is a small hardening change, not a new user-facing diagnostic.

## Checks I Would Not Add Yet

- `rg`: documented, but I did not find a direct current runtime dependency. Add only after tying it to a real workflow.
- `delta`: documented, but current diff display appears to use `git`, `bat`, and `less`, not `delta`.
- Generic `node` / `npm`: useful for installing some provider CLIs, not for SASE runtime if the CLIs already exist.
  Surface conditionally from provider setup hints.
- Broad `gh` checks for every user: current `plugins.github` already probes `gh auth status` only when a GitHub plugin
  is installed, which is the right noise profile.
- Default provider auth smoke prompts: they can consume quota, mutate provider history, hang on interactive login, and
  violate doctor default-mode expectations.

## Recommended Ranking

1. **Add `install.management` default check for uv-tool readiness.** This is the clearest missing-functionality
   diagnostic: updates, plugin install/update/uninstall, Admin Center update operations, and chat install workflows are
   disabled outside the canonical uv-tool environment.

2. **Add `tools.editor` default check and centralize editor resolution.** The docs classify editor availability as
   required, and many SASE workflows invoke an external editor. This catches a common first-run failure with minimal
   cost.

3. **Expand deep optional-tool checks with real missing capabilities: clipboard and `fzf`; reconcile `rg`/`delta` docs.**
   This makes `sase doctor -D` match the install guide without creating false warnings for tools not actually used.

4. **Add `editor.lsp` deep check using the existing xprompt LSP resolver.** This directly explains missing editor
   completions, diagnostics, hover, snippets, and jump-to-definition.

5. **Add `mobile.gateway` deep/selected check.** Return `SKIP` for default non-mobile setups; warn only when mobile is
   configured or explicitly selected and the gateway binary, bind policy, or FCM credential pointers are incomplete.

6. **Add provider-owned `llm.auth` deep/selected diagnostics.** Do this through provider hooks, not hardcoded top-level
   commands. Keep default doctor non-networked and non-token-consuming.

7. **Add configured-command checks for `precommit_command` and similar shell hooks.** Keep them best-effort and
   read-only. This is valuable, but less central than install/editor/provider/mobile readiness.

8. **Deduplicate provider path env-var derivation in deep CLI-version checks.** Small reliability hardening that prevents
   future drift.

