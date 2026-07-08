---
create_time: 2026-07-08
bead_id: sase-5l
tier: epic
status: planned
research: sdd/research/202607/sase_doctor_diagnostics_consolidated_20260708.md
---
# Plan: Expand `sase doctor` Diagnostic Coverage

## Problem & Product Context

`sase doctor` is the support front door for a tool with many prerequisites. It is already a solid read-only diagnostic
framework (`src/sase/doctor/runner.py`), but several prerequisites can be absent, stale, unauthenticated, or
misconfigured without doctor saying so — and each gap silently removes a concrete SASE capability. The consolidated
research in `sdd/research/202607/sase_doctor_diagnostics_consolidated_20260708.md` verifies the strongest gaps against
current source and ranks the fixes. This epic implements that ranked set of improvements as one diagnostic per phase.

## Shared Design Constraints (apply to every phase)

- Keep default checks fast and read-only; never emit secret values.
- `SKIP` unused/opt-out integrations; `WARN` only when a real capability is degraded; reserve `ERROR` for required or
  explicitly-enabled workflows that are actually blocked.
- Provider/plugin-specific behavior must be declared via provider/registry/hook metadata, not `if provider == ...`
  ladders — all runtimes are treated uniformly.
- Introduce a `resources` check group for disk, limits, inotify, and chezmoi-environment checks, and split
  `tools.optional` into a small default "core UX tools" set and a deep "artifact/rendering extras" set so central
  failures are not hidden behind `--deep`.
- Every new check ships with focused tests in the existing doctor test shape: mocked probes, deterministic
  `DiagnosticCheck` payloads, and explicit `SKIP` coverage for opt-out/default states.
- Read the matching section of the research file for full rationale, source line references, and status semantics before
  implementing. Do NOT duplicate checks that already exist (e.g. Telegram is covered by `axe.chops`).

## Execution Model

The phases are chained into a strict linear dependency order so exactly one phase runs at a time. This is intentional:
many phases touch the same doctor registry and `tools`/`resources` modules, and serialization avoids conflicting edits.
Each phase agent reads its bead description and this plan, implements only its own check(s) with tests, runs `just
check`, and closes its own bead without touching the epic. A final Opus-driven phase end-to-end tests the whole new
surface and fixes any bugs or clear-win improvements it finds.

## Phases (ranked; one diagnostic per phase)

1. **`llm.auth` — offline provider auth evidence** (default, offline-only). `OK` when the selected provider CLI is
   present and local credential evidence or a relevant API-key env var exists; `WARN` when present but no auth evidence;
   `SKIP` when `llm.default` already reports the CLI missing. Provider-declared credential-path/env metadata; keep
   `auth_verified=false` unless a provider-owned bounded status command can verify without an LLM call. Research §1.
2. **`install.management` — canonical uv-tool install readiness** (default). Reuse the existing
   `src/sase/uv_tool/detect.py` detector. `OK` for a confirmed uv-tool install; `WARN` for pip/pipx/dev-venv/missing
   `uv`/wrong prefix/missing receipt (never `ERROR`). Reveals `sase update`, plugin management, and chat-driven
   install/update workers may be unavailable. Research §2.
3. **`resources.disk_free` — free disk before workspace clone** (default). Numbered workspaces are real `git clone`s;
   a full disk hard-fails agent launch. `ERROR` under ~1 GB free at the workspace root; `WARN` under ~3 GB; `OK`
   otherwise. Include `sase_home` as a secondary path; next steps mention `sase workspace cleanup`. Research §3.
4. **`tools.editor` — shared editor resolver** (default). Create one shared editor resolver and reuse it from doctor and
   the commit/prompt/ACE editor call sites. `OK` when `$VISUAL`/`$EDITOR` or `nvim`/`vim` resolves; `WARN` when the
   selected command head is missing or only an unverified shell command was configured. Support `code --wait`-style
   commands. Research §4.
5. **Promote `tools.tmux` and `tools.clipboard` to default** (default). `tools.tmux` `WARN` (not `ERROR`) if missing —
   `ace --tmux` hard-exits and tmux enables workspace windows/artifact panes. `tools.clipboard` reuses
   `clipboard_available()` with platform-aware next steps (`wl-clipboard`/`xclip`/`xsel`/`pbcopy`). Keep niche artifact
   tools deep. Research §5.
6. **`integrations.mobile_push_config` — FCM/push coherence** (default, skips when disabled). `SKIP` when push disabled;
   `OK` for `test`, `fcm_dry_run`, or complete FCM config; `ERROR` when `fcm` is selected but project ID or credential
   source is missing. No MCP diagnostic (MCP is not implemented here). Research §6.
7. **`runtime.node` — conditional node/npm setup check** (default). `WARN` only when `node`/`npm` is missing AND an
   npm-distributed provider is registered but its CLI is not found; otherwise `SKIP`/`OK`. Avoids noisy unconditional
   warnings. Research §7.
8. **`tools.fzf` — surface fzf in top-level doctor** (default or deep). `fzf` gates prompt pickers and editor prompt
   history; it is currently only in `sase prompt doctor`. `WARN` when missing. Research §8.
9. **`integrations.mobile_gateway_binary` — gateway binary preflight** (deep). `SKIP` when mobile is unused; `WARN` when
   the gateway is configured but no `sase_gateway` command resolves. Research §6/§9.
10. **`resources.chezmoi` + `config.skills.applied` — chezmoi mode blind spots** (deep, conditional). `resources.chezmoi`
    `SKIP` unless `use_chezmoi` or a source tree exists; `ERROR` when enabled but `chezmoi` is missing; `WARN` for
    suspicious source state. `config.skills.applied` stats real home skill targets and advises `chezmoi apply` when
    source and applied state diverge. Research §9.
11. **`tools.xprompt_lsp`, `terminal.kitty_graphics`, `tools.tmux_version` — editor/graphics deep checks** (deep). Mirror
    the `sase lsp` resolver read-only (`WARN` if no server resolves or only the slow cargo fallback is available); explain
    missing inline artifact rendering and old-tmux passthrough failures. Research §10.
12. **`resources.ulimits`, `resources.inotify`, `terminal.truecolor` — host-limit deep checks** (deep). Compare soft
    `RLIMIT_NOFILE`/`RLIMIT_NPROC` against a floor derived from configured runner concurrency; read
    `/proc/sys/fs/inotify/*` (Linux) and warn when watch/instance limits force polling; low-priority truecolor warning.
    Research §11.
13. **Fix prettier false-drift messaging** (existing checks). Broaden the `prettier` optional-tool description and label
    the `config.init` false-drift case ("stale counts may be inflated: prettier missing") so doctor's own skill-drift
    signal is not noisy when prettier is absent. Research §12.
14. **Opus end-to-end verification & hardening** (`claude/opus`). End-to-end test every new diagnostic added in phases
    1–13: exercise `sase doctor` and `sase doctor -v`/`--deep` across OK/WARN/ERROR/SKIP paths, confirm registry wiring
    and grouping, and confirm no secret values leak. Fix any bugs found. If this agent identifies any objective,
    clear-win improvements (not subjective preferences), it should make them. Run `just check` before closing.

## Do Not Add (from research)

Generic network/PyPI reachability, MCP diagnostics, unverified `rg`/`delta` checks, provider auth smoke prompts (quota
use / interactive hangs), and duplicate `pass`/Telegram checks already covered by `axe.chops`.
