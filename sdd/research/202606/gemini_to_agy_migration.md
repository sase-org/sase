# Migrating from Gemini CLI (`gemini`) to Antigravity CLI (`agy`)

**Date:** 2026-06-19
**Status:** Research / pre-implementation
**Goal:** Remove the `gemini` agent runtime entirely (target: zero *live* references) and add an `agy`
(Antigravity CLI) runtime with the fullest support the `agy` CLI currently permits.

---

## 1. Executive Summary

SASE already has a clean, plugin-based runtime abstraction (pluggy entry points under the `sase_llm`
group). Adding/removing a runtime is mostly mechanical: the *core* of the work is ~3 new Python modules +
a handful of hardcoded enumeration sites, plus 3 file deletions and a 2-line Rust-core path change. The
abstraction is well-decoupled — **no cascading logic changes** are required.

The hard part is **not** the SASE plumbing. It is that **`agy` is an immature, fast-moving CLI whose
headless/structured-output surface is not yet stable**, and it differs from `gemini` in exactly the
places the current `GeminiProvider` depends on:

- `gemini` is driven via `--output-format stream-json` and a rich, line-delimited JSON event stream that
  SASE parses for **text, tool calls, token usage, and "thinking" blocks**.
- `agy`'s `--output-format json` is repeatedly described across sources as *"still stabilizing"* /
  *"rejected with `flags provided but not defined`"*, with **no documented streaming event schema or
  tool-call event stream**, and a **non-TTY stdout bug** that silently drops output when piped.

**Consequence:** "as complete support as possible" today realistically means a *headless text-capture*
provider (pseudo-TTY wrapper + marker-based result extraction), **not** full streaming/tool-call/usage
parity with the old `GeminiProvider`. That parity can be added incrementally as `agy`'s `--output-format
json` stabilizes.

Two decisions need the user's call before implementation (see §8):

1. **Does "zero references" include the ~1,150 references in historical SDD records** (`sdd/prompts/`,
   `sdd/tales/`, `sdd/epics/`)? Recommendation: **no** — preserve history; scrub only live code, config,
   tests, docs, and memory.
2. **Provider naming** — call it `agy` (matches the binary, matches the user's framing) vs `antigravity`.
   Recommendation: **`agy`**.

---

## 2. What is Antigravity (`agy`)?

Antigravity CLI is Google's Go-based, multi-agent terminal coding agent — positioned as the **successor to
Gemini CLI** (Google publishes a "Gemini CLI → Antigravity" migration guide). Highlights from current
public material (June 2026):

- **Binary:** `agy` (aliased; the project/product name is "Antigravity"). Installed via
  `curl -fsSL https://antigravity.google/cli/install.sh | bash`.
- **Models:** Gemini 3.5 Flash (default, "High"), Gemini 3.1 Pro, plus (plan-dependent) Claude Sonnet,
  Claude Opus, and GPT-OSS 120B. This is a meaningful expansion over Gemini CLI's Gemini-only lineup.
- **Backward compatibility with Gemini CLI:** reads `GEMINI.md` context files and reuses `~/.gemini/…` as
  a config root (Antigravity config nests at `~/.gemini/antigravity-cli/`).
- **Auth:** interactive OAuth (Google account / GCP project) or, for headless use, an API key via
  `GEMINI_API_KEY` **or** `ANTIGRAVITY_API_KEY` env var.
- **Maturity caveat:** the CLI is new and its flags/output formats are still in flux. Sources disagree on
  exact flag spellings (see §4) — treat all flag names below as *verify-at-implementation*.

---

## 3. How SASE integrates runtimes today (the abstraction)

### 3.1 Registration model — pluggy entry points

Runtimes are discovered as `sase_llm` entry points (`pyproject.toml:113`):

```toml
[project.entry-points."sase_llm"]
claude   = "sase.llm_provider.claude:ClaudeCodeProvider"
codex    = "sase.llm_provider.codex:CodexProvider"
gemini   = "sase.llm_provider.gemini:GeminiProvider"
opencode = "sase.llm_provider.opencode:OpenCodeProvider"
qwen     = "sase.llm_provider.qwen:QwenProvider"
```

`registry.py` builds a `pluggy.PluginManager` from these entry points (`_build_llm_pm`, `iter_plugins`,
`get_provider`). A provider is a class implementing `llm_*` hookimpls defined in
`llm_provider/_hookspec.py`. **Dispatch is fully dynamic** — nothing hardcodes the *set* of runtimes for
invocation; you add a runtime by adding an entry point + class.

### 3.2 Per-runtime surface area (what `gemini` actually consists of)

| Concern | `gemini` artifact | Location |
|---|---|---|
| Provider class | `GeminiProvider` (11 hookimpls + `invoke`/`_run_subprocess`) | `src/sase/llm_provider/gemini.py` |
| Stream parser | `stream_and_parse_gemini_json_output()` + line processors | `src/sase/llm_provider/_subprocess_gemini.py` |
| Tool-call normalizer | `append_gemini_tool_call_event()` + normalizers | `src/sase/llm_provider/_tool_call_gemini.py` |
| Re-exports | imports `_subprocess_gemini` | `src/sase/llm_provider/_subprocess.py` |
| Re-exports | imports `_tool_call_gemini` | `src/sase/llm_provider/_tool_calls.py` |
| Entry point | `gemini = …:GeminiProvider` | `pyproject.toml:116` |
| Family color | `"gemini": "#4285F4"` | `registry.py:32` |
| Env var (cache policy) | `"SASE_GEMINI_PATH"` | `registry.py:338` |
| CLI invocation | `gemini --output-format stream-json --yolo --model <m>` (prompt via **stdin**) | `gemini.py:148-155, 223-264` |
| Short name | `"gem"` | `gemini.py:60` |
| Default / known models | `gemini-3-flash-preview` + 6 models + 6 aliases | `gemini.py:19, 68-87` |
| Skill template context | `Gemini` / `Gemini CLI` / `ask_user` | `gemini.py:90-95` |
| Skill deploy subpath | `[".gemini/jetski"]` | `gemini.py:98-99` |
| Autodetect | priority `30`, cli name `"gemini"` | `gemini.py:102-107` |
| Doctor hint | `Gemini CLI` / `npm i -g @google/gemini-cli` | `doctor/checks_providers.py:31-35` |
| TUI style + emoji | `_ProviderStyle("gemini")`, `♊` | `ace/tui/provider_styles.py:59, 84` |
| TUI prompt-panel display | provider badge / thinking-buffer special-casing | `ace/tui/widgets/prompt_panel/_helpers.py`, `_agent_display_parts.py` |
| **"Thinking" log parser** | reads `gemini_api_proxy.par.INFO` from `SASE_GEMINI_CLI_TMP` | `ace/tui/thinking/parser.py` (~39 refs) |
| Context shim file | `GEMINI.md` in `PROVIDER_SHIM_FILES` | `amd/constants.py:6`, `memory/inventory.py:25` |
| Schema default | `"default": "gemini"` (stale; see note) | `config/sase.schema.json:575` |

> **Note on the "default provider".** The *shipped* default in `src/sase/default_config.yml:270` is
> `provider: ""` (= autodetect). Autodetect order is by ascending priority: claude `0`, codex `10`,
> qwen `15`, opencode `18`, **gemini `30`** — so `gemini` is the *lowest-priority* fallback, not the
> active default. The `"default": "gemini"` in `config/sase.schema.json:575` is a stale cosmetic
> JSON-schema default and should be corrected during the migration.

### 3.3 What is generic (no changes needed)

`base.py`, `types.py`, `config.py`, `_hookspec.py`, `_plugin_manager.py`, `_invoke.py`,
`_subprocess_stream.py`, `_subprocess_plain.py`, `_subprocess_artifacts.py`, `_tool_call_common.py`,
`_tool_call_io.py`, `preprocessing.py`, `postprocessing.py`, the commit finalizer
(`commit_finalizer*.py`), and the commit skills (`sase_git_commit.md`, …) are all **runtime-agnostic**.
Per the "Uniform Agent Runtimes" rule in `memory/gotchas.md`, the commit workflow is VCS-driven, not
runtime-driven — `agy` inherits it for free.

> ⚠️ **Misleadingly-named module:** `src/sase/gemini_wrapper/` is **not** gemini-specific. It is a
> deprecated-but-load-bearing utility package (`format_with_prettier`, `process_command_substitution`,
> `validate_file_references`, a generic `invoke_agent` wrapper) imported by ~8 call sites. **Do not delete
> it as part of "removing gemini."** Renaming it (e.g. to `agent_wrapper`) is an optional, separable
> cleanup — see §6.4.

### 3.4 Rust core

The Rust core (`../sase-core/crates/sase_core`) is **runtime-agnostic** except for **two hardcoded memory
search paths** in `xprompt_catalog.rs:1110` and `:1120` (`home.join(".gemini").join("memory").join("long")`
and the project-root equivalent). There is **no runtime enum** in core and the `vcs_project_completion`
algorithm contains no runtime names. Migration impact: change/add `.gemini` → `.agy` (or `.agents`) in
those two lines, then rebuild bindings (`sase_core_rs`). This is the *only* cross-repo change.

---

## 4. The `agy` CLI surface — external-dependency analysis

This is the crux of the migration. The table below consolidates what current sources say; **confidence is
low-to-medium** because `agy` is new and sources conflict. Everything here must be confirmed against
`agy --help` / `agy inspect` at implementation time.

| Capability | Gemini CLI (today, known-good) | Antigravity `agy` (reported) | Confidence |
|---|---|---|---|
| Headless prompt | prompt via **stdin** | `agy -p "…"` / `--print` (prompt as **arg**); `--prompt-file <f>` also seen | medium |
| Auto-approve | `--yolo` | `--yolo` *or* `--yes` (sources disagree); `/goal` prefix in interactive | low |
| Model select | `--model <name>` | `--model` not consistently documented; default Gemini 3.5 Flash | low |
| Structured output | `--output-format stream-json` (line-delimited events) | `--output-format json` / `--output json` — **"still stabilizing"**, sometimes rejected as undefined flag | **low** |
| Streaming events | rich event stream (`message`/`result`/`error`/`tool_use`/`tool_result`) | **none documented** | low |
| Tool-call stream | parsed into `tool_calls.jsonl` | **no documented machine-readable tool-call stream** | low |
| Token usage | from `result.stats.models` | **not documented** | low |
| "Thinking" capture | reads `gemini_api_proxy.par.INFO` proxy log | **no equivalent** (different Go internals) | n/a |
| Auth (headless) | login flow | `GEMINI_API_KEY` or `ANTIGRAVITY_API_KEY` env var | medium |
| Non-TTY stdout | works piped | **BUG: silently drops final output when piped, exit code still 0** | medium |
| Context files | `GEMINI.md` | `.antigravity.md` (recommended), `GEMINI.md` (back-compat), `AGENTS.md` (native) | medium |
| Config root | `~/.gemini/` | `~/.gemini/antigravity-cli/` (settings/keybindings/skills); MCP at `~/.gemini/config/mcp_config.json` | medium |
| Workspace skills | `.gemini/…` | **`.agents/skills/`** (note: *not* `.agy/`) | medium |
| Workspace MCP | — | `.agents/mcp_config.json` | medium |
| Inspect config | — | `agy inspect` | medium |

### 4.1 The two headline risks

**(a) Non-TTY stdout drop.** `agy` checks for a TTY at startup and disables rendering when stdout is a
pipe/file/subprocess — and in that mode `agy -p` can return **empty output with exit code 0**. SASE always
runs the runtime as a piped subprocess, so this directly breaks naïve integration. The community-documented
workaround is a **pseudo-TTY** wrapper:

```bash
# Linux (util-linux script): -q quiet, -e propagate exit code, -c command
script -qec 'agy -p "<PROMPT>"' /dev/null < /dev/null
```

then strip ANSI/`\r`. SASE's subprocess layer would need to wrap the `agy` invocation in a PTY (either via
`script(1)` or Python's `pty`/`ptyprocess`). The interrupt-monitor and streaming scaffolding
(`_subprocess_plain.py`, `_subprocess_stream.py`) are reusable, but the spawn step changes.

**(b) Immature structured output.** Because `--output-format json` is unstable and no streaming/tool-call
schema is documented, the three richest gemini features — **live tool-call rows, token-usage accounting,
and thinking-block extraction** — have **no reliable `agy` equivalent today**. The pragmatic v1 is
text-capture with a self-chosen result marker (e.g. instruct the agent to prefix its final answer), exactly
as the CI guides recommend. Treat full parity as a fast-follow gated on `agy` shipping a stable
`--output-format json`.

---

## 5. Census of `gemini` references (removal scope)

Counts from ripgrep across the repo (live tree only; `sdd/research/` excluded). "Live" = must change for a
working, reference-free migration; "Historical" = immutable record.

| Bucket | Files | Refs | Action |
|---|---:|---:|---|
| **A. Live source** (`src/`) | ~39 | ~229 | **Must change** — delete 3 provider modules, edit ~12 enumeration/UI sites |
| **B. Tests** (`tests/`) | ~79 | ~456 | **Must change** — delete 3 gemini-only suites; update cross-provider fixtures |
| **C. Config & dotfiles** | ~8 | ~8 | **Must change** — `pyproject.toml`, `sase.schema.json`, `default_config.yml`, `GEMINI.md` shims, `.gemini/` |
| **D. User docs** (`README`, `docs/`) | ~13 | ~84 | **Should change** — `docs/llms.md` (42), `docs/xprompt.md`, `docs/ace.md`, `README.md`, blog posts |
| **E. Memory files** (`memory/`) | 3 | 3 | **Should change** — `generated_skills.md`, `gotchas.md` (needs user approval per AGENTS.md) |
| **F. Historical SDD** (`sdd/prompts`,`tales`,`epics`) | ~40+ | **~1,150** | **Recommend: do NOT touch** — immutable history (see §8.1) |

### Live-source hotspots (bucket A)
- **Delete:** `llm_provider/gemini.py`, `_subprocess_gemini.py`, `_tool_call_gemini.py`.
- **Edit (de-enumerate gemini):** `_subprocess.py`, `_tool_calls.py`, `registry.py` (color + env var),
  `doctor/checks_providers.py`, `amd/constants.py`, `memory/inventory.py`,
  `ace/tui/provider_styles.py`, `ace/tui/widgets/prompt_panel/_helpers.py`, `_agent_display_parts.py`,
  `main/parser_init.py` (CLI `--provider` choice list, if present), `xprompt/directives.py` (example),
  `default_config.yml` retry block.
- **Special — thinking parser:** `ace/tui/thinking/parser.py` (+ `thinking/__init__.py`, several tests)
  is built around gemini's proxy-log format. There is no `agy` analog, so this is **removed**, not ported,
  unless/until `agy` exposes a thinking stream.

---

## 6. Scope of work

### 6.1 Create (new `agy` runtime) — ~3 modules + registrations
1. `src/sase/llm_provider/agy.py` — `AgyProvider` implementing all `llm_*` hookimpls. Key non-default
   hook: **`llm_skill_deploy_subpath()` → `.agents`** (not the `.{provider}` = `.agy` default), to match
   `agy`'s `.agents/skills/` convention. Skill template context → `Antigravity` / `Antigravity CLI` /
   native ask tool. Models: `gemini-3.5-flash` (default), `gemini-3.1-pro`, and (if exposed) the
   Claude/GPT-OSS aliases. CLI name `agy`, env var `SASE_AGY_PATH`, autodetect priority (suggest `30`,
   inheriting gemini's slot).
2. `src/sase/llm_provider/_subprocess_agy.py` — spawn `agy` (PTY-wrapped per §4.1a) and capture output.
   v1: text capture + marker extraction. v2 (when stable): parse `--output-format json`.
3. `src/sase/llm_provider/_tool_call_agy.py` — **stub/skeleton** in v1 (no tool-call stream yet); fill in
   when `agy` exposes one. Reuse `_tool_call_common.py`.
4. Register: add entry point to `pyproject.toml`; re-exports in `_subprocess.py` / `_tool_calls.py`; add
   `SASE_AGY_PATH` to `registry.py:336-340`; add family color + `provider_styles` entry + emoji; add
   `doctor/checks_providers.py` hint (install via `curl … install.sh`, auth via API key); add `AGY.md` (or
   `.antigravity.md`) to `amd/constants.py` `PROVIDER_SHIM_FILES` and `memory/inventory.py`
   `INSTRUCTION_ROOT_FILENAMES` — **or** deliberately omit a shim since `agy` reads `AGENTS.md` natively
   (decision §8.4).

### 6.2 Delete (remove `gemini`)
- 3 provider modules (§5 bucket A) + their re-export lines + 3 gemini-only test suites
  (`tests/llm_provider/test_gemini_stream_parser.py`, `tests/test_gemini_wrapper.py`*,
  `tests/test_thinking_parser.py`).
  (*`test_gemini_wrapper.py` tests the mis-named generic `gemini_wrapper` package — rename, don't delete,
  if §6.4 is taken; otherwise keep + rename the test.)
- Root `GEMINI.md`, `tools/GEMINI.md`, `src/sase/ace/GEMINI.md`, and `.gemini/` directory.
- `thinking/parser.py` gemini path (or whole file if no other use).

### 6.3 Edit (config/docs/memory)
- `config/sase.schema.json`: fix `provider` default + description examples.
- `default_config.yml`: replace `gemini` retry block with `agy`; update prose examples (lines 504, 509).
- `docs/llms.md`, `docs/xprompt.md`, `docs/ace.md`, `docs/configuration.md`, `README.md`, blog posts.
- `memory/generated_skills.md`, `memory/gotchas.md` (**requires user approval** per AGENTS.md).

### 6.4 Optional cleanup (separable)
- Rename `src/sase/gemini_wrapper/` → `agent_wrapper/` (or similar) so no incidental `gemini` token
  survives in live code. ~8 import sites. **Recommend doing this** if the user truly wants zero live
  tokens, but track it as its own bead/PR — it is orthogonal to the runtime swap and touches unrelated
  call sites.

### 6.5 Rust core
- `../sase-core`: `xprompt_catalog.rs:1110,1120` `.gemini` → `.agy` (or `.agents`); rebuild `sase_core_rs`
  binding; update core tests. Coordinate via `sase workspace open -p sase-core <N>`.

### Effort estimate
- New `agy` provider (v1, text-capture): **~1–1.5 days**.
- Gemini removal + de-enumeration + tests: **~1 day**.
- Docs/memory/config + Rust core: **~0.5 day**.
- Full streaming/tool-call/usage parity (v2): **deferred / gated on `agy` stability** — potentially several
  days once the upstream JSON format lands.

---

## 7. Gap analysis: can `agy` reach `gemini`'s feature parity?

| `gemini` feature (SASE) | `agy` v1 (now) | `agy` v2 (when JSON stabilizes) |
|---|---|---|
| Headless invocation | ✅ via `agy -p` + PTY wrapper | ✅ |
| Auto-approve / non-interactive | ✅ (`--yolo`/`--yes`/`/goal`) | ✅ |
| Model selection | ⚠️ best-effort (`--model` unconfirmed) | ✅ |
| Final text capture | ✅ marker-based | ✅ structured |
| Live tool-call rows (`tool_calls.jsonl`) | ❌ no stream | ✅ if upstream emits tool events |
| Token-usage accounting | ❌ not exposed | ✅ if `result.usage` exposed |
| "Thinking" block extraction | ❌ no proxy log | ❓ depends on upstream |
| Skills / hooks / commit workflow | ✅ (runtime-agnostic in SASE) | ✅ |
| MCP | ✅ (`.agents/mcp_config.json`) | ✅ |

**Bottom line:** SASE-side parity is automatic; *agent-output* parity is bounded by `agy`'s current lack of
a stable machine-readable stream. "As complete as possible" = ship v1 now, design the parser seam so v2 is
a drop-in once upstream ships structured output.

---

## 8. Decisions needed before implementation

### 8.1 Scope of "zero references" — **biggest open question**
The ~1,150 references in `sdd/prompts/`, `sdd/tales/`, `sdd/epics/` are dated historical records of past
work (and `AGENTS.md` forbids editing memory files without approval). Scrubbing them rewrites project
history and is almost certainly undesirable. **Recommendation:** define "zero references" as *zero in live
code, config, tests, docs, and memory*; leave historical SDD untouched and note the rename in this research
doc + the migration's tale. Confirm with user.

### 8.2 Provider name: `agy` vs `antigravity`
`agy` matches the binary and the user's framing; `antigravity` is more descriptive. **Recommend `agy`**
(short name e.g. `agy` or `agv`).

### 8.3 Replacement for gemini's autodetect slot
gemini was priority `30` (lowest). Give `agy` the same `30`, or raise it if `agy` should be preferred over
opencode/qwen when present. **Recommend `30`** (neutral parity).

### 8.4 Context shim file
`agy` natively reads `AGENTS.md`, so a `@AGENTS.md` shim may be redundant. Options: (a) add `AGY.md`/
`.antigravity.md` shim for consistency with other runtimes, or (b) rely on native `AGENTS.md`.
**Recommend (a) `.antigravity.md`** for symmetry with the existing per-runtime shim machinery, unless you
prefer to lean on native support.

### 8.5 v1 fidelity vs waiting
Ship the text-capture v1 now, or wait for `agy`'s `--output-format json` to stabilize before integrating?
**Recommend ship v1 now** behind the same provider seam, with the parser stubbed for v2.

---

## 9. Recommended migration strategy

A **phased, additive-then-subtractive** approach — stand `agy` up and prove it before deleting `gemini`,
so the runtime set is never broken.

**Phase 0 — Confirm the `agy` contract (½ day, do first).**
Install `agy`; capture `agy --help`, `agy inspect`, and the real behavior of `-p`, the auto-approve flag,
`--model`, `--output-format json`, and non-TTY piping. Record the *actual* flags in the migration tale.
This de-risks every later phase (current web sources conflict).

**Phase 1 — Add `agy` runtime (additive, no gemini changes).**
Create `agy.py` + `_subprocess_agy.py` (PTY-wrapped text capture) + stub `_tool_call_agy.py`; register
entry point, env var, color, doctor hint, TUI style, shim file. Add `agy` to autodetect. Write provider
tests mirroring the lighter providers (e.g. `opencode`). **Both `gemini` and `agy` coexist here** — easy to
A/B and verify `agy` end-to-end before committing to removal. Run `just check`.

**Phase 2 — Remove `gemini` (subtractive).**
Delete the 3 provider modules + re-exports + entry point; remove gemini from every enumeration site
(registry color/env, doctor, amd/inventory shims, provider_styles, prompt-panel display, parser_init
choices, default_config retry, schema default). Delete the thinking-parser gemini path and the 3
gemini-only test suites; fix cross-provider tests. Delete `GEMINI.md` shims + `.gemini/`. Run `just check`.

**Phase 3 — Rust core + bindings.**
`sase workspace open -p sase-core <N>`; update `xprompt_catalog.rs:1110,1120`; rebuild `sase_core_rs`;
update core tests.

**Phase 4 — Docs, memory, config.**
Rewrite `docs/llms.md` et al., `README` support table; update `memory/generated_skills.md` +
`memory/gotchas.md` (**get user approval**). Update `sase.schema.json` default.

**Phase 5 — Optional `gemini_wrapper` rename** (separate bead/PR) to eliminate the last incidental live
`gemini` token. Leave historical SDD untouched (per §8.1).

**Phase 6 — Parity fast-follow** (deferred). When `agy` ships stable `--output-format json`, flesh out
`_subprocess_agy.py` / `_tool_call_agy.py` to restore tool-call rows + token usage (and thinking, if
exposed).

> **Verification at each phase:** `just install` (ephemeral workspace) → `just check`. After Phase 1/2,
> sanity-run a real `agy` agent through `sase` to confirm headless capture works under SASE's piped
> subprocess model (the non-TTY trap, §4.1a).

---

## 10. Open risks

1. **`agy` flag/format instability** — the single biggest risk. Mitigated by Phase 0 and by isolating all
   `agy` specifics behind one provider module + parser seam.
2. **Non-TTY stdout drop** — must PTY-wrap or output silently vanishes (exit 0). Add output-non-empty +
   marker assertions and a retry, per the CI guides.
3. **Feature regression** — losing tool-call rows / token usage / thinking until v2. Set expectations; the
   UI already degrades gracefully for providers that emit less.
4. **Default-provider surprise** — gemini was the lowest autodetect fallback; ensure autodetect still
   resolves sanely after removal (claude→codex→qwen→opencode→agy).
5. **Memory-file edits need approval** (`AGENTS.md`) — `memory/gotchas.md` and `memory/generated_skills.md`.
6. **Historical-record scope** — see §8.1; don't rewrite `sdd/` history without explicit instruction.

---

## Appendix A — Sources (Antigravity CLI)

- [Using Google's Antigravity CLI (agy) and YOLO mode — DEV](https://dev.to/gde/using-googles-new-ai-command-line-assistant-antigravity-cli-agy-and-yolos-no-confirmation-mode-10d)
- [Antigravity CLI: Hands-On Guide — DEV](https://dev.to/arindam_1729/antigravity-cli-a-hands-on-guide-to-googles-terminal-coding-agent-5bc7)
- [Antigravity CLI Tutorial Series — Google Cloud Community / Medium](https://medium.com/google-cloud/antigravity-cli-tutorial-series-12b46cfe3bf2)
- [Running `agy` Headless in CI: non-TTY stdout problem — Antigravity Lab](https://antigravitylab.net/en/articles/integrations/antigravity-cli-agy-headless-non-tty-stdout-ci)
- [Running Antigravity CLI Headless: design before CI/cron — Antigravity Lab](https://antigravitylab.net/en/articles/integrations/antigravity-cli-headless-non-interactive-ci-design)
- [Antigravity CLI Cheatsheet — scriptbyai](https://www.scriptbyai.com/antigravity-cli-cheatsheet/)
- [Google Antigravity CLI: Orchestrating Parallel Agents — DataCamp](https://www.datacamp.com/tutorial/antigravity-cli)
- [Antigravity CLI Reference: Sandbox, Plugins & Subagents — explainx.ai](https://www.explainx.ai/blog/antigravity-cli-features-sandbox-plugins-subagents-2026)
- [Getting Started with Antigravity CLI — Google docs](https://antigravity.google/docs/cli-getting-started)
- [Gemini CLI → Antigravity migration — Google docs](https://antigravity.google/docs/gcli-migration)
- [`--print` per-conversation ID issue #7 — google-antigravity/antigravity-cli](https://github.com/google-antigravity/antigravity-cli/issues/7)

## Appendix B — Key file index (SASE)

| Area | Path |
|---|---|
| Entry points | `pyproject.toml:113-118` |
| Provider class (template to copy) | `src/sase/llm_provider/gemini.py` (or lighter: `opencode.py`) |
| Stream parser | `src/sase/llm_provider/_subprocess_gemini.py` |
| Tool-call normalizer | `src/sase/llm_provider/_tool_call_gemini.py` |
| Registry (colors/env/autodetect) | `src/sase/llm_provider/registry.py:32, 336-340, 311-313` |
| Doctor hints | `src/sase/doctor/checks_providers.py:20-46` |
| Shim filenames | `src/sase/amd/constants.py:6`, `src/sase/memory/inventory.py:24-30` |
| TUI styles/emoji | `src/sase/ace/tui/provider_styles.py:59, 84` |
| Thinking parser | `src/sase/ace/tui/thinking/parser.py` |
| Schema default | `config/sase.schema.json:574-575` |
| Default config | `src/sase/default_config.yml:269-281, 504-509` |
| Rust core paths | `../sase-core/crates/sase_core/src/xprompt_catalog.rs:1110, 1120` |
