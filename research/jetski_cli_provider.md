# Adding Jetski CLI as a New LLM Provider

_Research date: 2026-04-21_

## Context

Google is sunsetting Gemini CLI in favor of the new **Jetski CLI** — the terminal surface of Jetski (`go/jetski-cli`,
binary at `/google/bin/releases/jetski-devs/tools/cli`). Per `.sase/home/org/lib/docs/jetski_cli.txt`, Jetski CLI:

- Has a non-interactive `-p / --print` flag (ideal for sase invocation).
- Supports conversation resume via `--continue` and `--conversation <id>`.
- Stores settings at `~/.gemini/jetski/cli/settings.json` (shares the `~/.gemini/` parent dir with Gemini CLI).
- Natively supports slash commands, hooks, MCP, and skills — feature parity with Claude Code.
- Authenticates via corp LOAS (`gcert`); no API key plumbing needed.

**Goal:** Add Jetski as a first-class sase LLM provider while keeping the existing Gemini CLI provider functional (some
users / machines will still have the old Gemini CLI installed for a transition period).

## Current Provider Architecture (relevant bits)

Three providers live in `src/sase/llm_provider/`, each implementing the `LLMProvider` abstract base from `base.py`:

| File        | Provider             | Session model                     | Output format        | Binary / env var   |
| ----------- | -------------------- | --------------------------------- | -------------------- | ------------------ |
| `claude.py` | `ClaudeCodeProvider` | `--session-id <uuid>` per invoke  | `stream-json` events | `claude`           |
| `codex.py`  | `CodexProvider`      | stateless; manual context rebuild | NDJSON (`--json`)    | `codex`            |
| `gemini.py` | `GeminiProvider`     | stateless; manual context rebuild | plain text (via PTY) | `SASE_GEMINI_PATH` |

Registration (`registry.py`):

- `_REGISTRY` dict populated by `_register_builtin_providers()` (lines 142–154).
- `_MODEL_TO_PROVIDER` dict (lines 13–35) maps every known model name → provider, enabling the `%model opus` syntax to
  auto-pick Claude.
- `_PROVIDER_MODEL_RE = re.compile(r"^(claude|codex|gemini)/(.+)$")` (line 38) handles explicit `%model codex/o3` syntax
  — **this regex is the one place where provider names are hard-coded**.
- `get_default_provider_name()` (lines 123–139) auto-detects via `shutil.which` in order: claude → codex → gemini.

Skill generation (`src/sase/main/init_skills_handler.py`):

- `ALL_PROVIDERS = ["claude", "gemini", "codex"]` (line 17).
- `PROVIDER_CONTEXT` dict (lines 19–35) maps each provider to a Jinja2 rendering context (`provider_name`,
  `provider_tool_name`, `provider_native_ask_tool`).
- Deploys each skill to `~/.{provider}/skills/<skill>/SKILL.md` (or under `CHEZMOI_HOME/dot_{provider}/skills/...` if
  chezmoi is enabled).

Shared subprocess plumbing (`_subprocess.py`) offers three parsers: `stream_process_output` (plain text),
`stream_and_parse_json_output` (Claude stream-json), `stream_and_parse_codex_json_output` (Codex NDJSON). Interrupt
handling (`interrupt_request.json` monitor + `interrupt_log.jsonl`) is duplicated across the three provider files but is
mechanically identical.

## Jetski-Specific Considerations

1. **Skills path collision with Gemini.** Jetski's config dir is `~/.gemini/jetski/`, not `~/.jetski/`. The default
   `~/.{provider}/skills/` layout in `init_skills_handler._get_target_path` doesn't fit — we need
   `~/.gemini/jetski/skills/` for Jetski specifically.
2. **Output format for `-p` is unspecified.** The published docs don't say whether `jetski-cli -p` emits plain text or
   structured JSON. Initial implementation should assume plain text and swap parsers if a JSON mode surfaces later
   (mirroring how Codex added NDJSON as a follow-up).
3. **Session persistence is native.** Unlike Gemini/Codex, Jetski supports `--continue` / `--conversation <id>` — so
   interrupt handling can use real session resume instead of the "Previous Response" string concat dance, which is
   closer to Claude's UUID pattern.
4. **Google-only binary.** The CLI is only reachable from Google corp machines. Auto-detection
   (`get_default_provider_name`) should still work via `shutil.which("jetski-cli")`, but we must not promote Jetski
   above Claude on non-corp machines.
5. **Config dir is shared with Gemini.** Hooks, MCP, and skills for Jetski live under `~/.gemini/jetski/`. A future
   consolidation ("google" family) is conceivable, but the user's immediate need is two independent providers.

## Alternative Solutions

### Alt 1 — Net-new standalone `JetskiProvider`

Drop a `src/sase/llm_provider/jetski.py` next to `codex.py` / `gemini.py`, following the existing idiom exactly:

- `class JetskiProvider(LLMProvider)` with `invoke()` shelling out to `jetski-cli -p`.
- Binary resolved from `SASE_JETSKI_PATH` env var, default `/google/bin/releases/jetski-devs/tools/cli`.
- Use `stream_process_output` (plain text) initially; upgrade to a dedicated parser if/when Jetski ships a JSON mode.
- Interrupt handling: maintain a `conversation_id` across interrupt cycles and re-invoke with `--conversation <id>` +
  the follow-up message rather than concatenating "Previous Response" blobs.
- Register in `registry.py`, extend `_PROVIDER_MODEL_RE` to `^(claude|codex|gemini|jetski)/(.+)$`, add any known Jetski
  models to `_MODEL_TO_PROVIDER`.
- Extend `ALL_PROVIDERS` and `PROVIDER_CONTEXT` in `init_skills_handler.py`.
- Special-case the skill deploy path to `~/.gemini/jetski/skills/...` (or add a per-provider override map — see alt 4).

**Pros:** Zero risk to existing providers; matches the "Codex was added this way" history (commit `8204f702`); reviewers
already know the pattern; easy to test in isolation.

**Cons:** Duplicates ~90% of the Gemini/Codex invoke scaffolding (interrupt monitor thread, `interrupt_log.jsonl`,
artifacts-dir plumbing). Small amount of bit-rot surface area.

### Alt 2 — Subclass `GeminiProvider`

Since Jetski is Google's official Gemini-CLI successor, make `JetskiProvider(GeminiProvider)` and override only the
command line, binary env var, and (later) the session-resume path.

**Pros:** Minimum LOC; implicitly captures the "Jetski is Gemini++" reality.

**Cons:** Gemini's provider uses a PTY because Gemini CLI block-buffers output; there's no evidence Jetski CLI has that
problem, and inheriting PTY + ANSI stripping by default is a correctness hazard (extra terminal gymnastics we may not
need). Jetski also supports real session resume, which doesn't fit Gemini's "rebuild context as a string" model — we'd
end up overriding the majority of methods anyway. Inheritance here would tie two unrelated lifecycles together.

### Alt 3 — Generic parameterized `CliProvider`

Introduce a new base class `CliProvider` parameterized by (binary, arg template, output-format, session-mode,
interrupt-mode) and reimplement Claude, Codex, Gemini, Jetski as thin configs.

**Pros:** Eliminates the duplicated interrupt-monitor / live-reply / artifacts boilerplate; future providers become
30-line files.

**Cons:** Big refactor that touches three working providers for a feature that only needs one new one. Claude's
streaming JSON parsing and Codex's reasoning extraction are genuinely different enough that the "generic" base quickly
gains hooks and becomes less generic. YAGNI until we add provider number 5+.

### Alt 4 — Alt 1 + small shared-plumbing refactor

Same as Alt 1, but at the same time extract the duplicated interrupt-monitor code (present in all three provider files)
into a helper in `_subprocess.py`, and add a `_SKILL_DEPLOY_PATH` override map in `init_skills_handler.py`
(`{"jetski": "~/.gemini/jetski/skills/..."}`) instead of hard-coding the special case.

**Pros:** Keeps the per-provider file idiom the team already knows, but pays down the specific duplication that adding a
fourth provider would make worse. The skill-path map is a tiny change but cleaner than an `if provider == "jetski"`
branch.

**Cons:** Slightly larger diff than Alt 1; touches Claude/Codex/Gemini files during the extraction. Needs discipline to
keep the refactor scoped (don't drift into Alt 3 territory).

### Alt 5 — Provider family / "google" namespace

Group Gemini and Jetski under a "google" family and expose them as `google/gemini` and `google/jetski` via a
sub-provider dispatch layer.

**Pros:** Models the org reality; gives us a clean place to put the shared `~/.gemini/` skill-deploy root.

**Cons:** Invents a new abstraction layer solely to reflect Google's internal rebrand. Existing `%model gemini/...`
syntax would either need translation or backward-compat aliasing. The registry, `_PROVIDER_MODEL_RE`, and auto-detect
all assume a flat provider namespace today — significant blast radius for cosmetic clarity.

## Trade-Off Summary

| Criterion                                      | Alt 1        | Alt 2          | Alt 3         | Alt 4        | Alt 5  |
| ---------------------------------------------- | ------------ | -------------- | ------------- | ------------ | ------ |
| LOC added                                      | ~300         | ~100           | ~-400         | ~350         | ~500   |
| Risk to existing providers                     | None         | Med            | High          | Low          | High   |
| Pays down existing duplication                 | No           | Partial        | Yes           | Some         | No     |
| Matches established team idiom                 | Yes          | No             | No            | Yes          | No     |
| Handles Jetski session resume cleanly          | Yes          | No             | Yes           | Yes          | Yes    |
| Handles `~/.gemini/jetski/` skill path cleanly | Special case | Inherits wrong | Config-driven | Override map | Native |
| Deliverable on first PR                        | Yes          | Yes            | No            | Yes          | No     |

## Recommendation: **Alt 4 — standalone `JetskiProvider` + small shared-plumbing cleanup**

Rationale:

1. **Matches the precedent set by Codex.** Codex was added as a clean fourth-wall `CodexProvider` class (commit
   `8204f702`, 2026-03-13). That approach shipped, was tested, and is understood. Reviewers will not be surprised.
2. **Avoids inheritance traps.** Jetski looks architecturally closer to Claude (native sessions, alt-screen, structured
   output, hooks) than to Gemini (plain-text, PTY, stateless). Subclassing Gemini (Alt 2) couples two diverging
   products; inheritance would invert within a release.
3. **Right-sizes the refactor.** Extracting just the interrupt-monitor helper (duplicated three times today, four times
   if we do nothing) and adding a tiny skill-deploy-path override map is cheap, well-scoped, and directly motivated by
   the new provider. It deliberately stops short of Alt 3's full generic base class, which would be speculative cleanup.
4. **Keeps Gemini CLI untouched.** The old `GeminiProvider` keeps working for any machine still on Gemini CLI. Users on
   the transition edge can switch per-invocation with `%model jetski/<model>` once Jetski is registered.
5. **Leaves room for later consolidation.** If Google eventually removes Gemini CLI support entirely, we can collapse
   Gemini into Jetski (or introduce Alt 5 as a follow-up) without pre-paying that cost now.

## Implementation Sketch (for Alt 4)

### New files

- `src/sase/llm_provider/jetski.py` — `JetskiProvider` class.
  - `_DEFAULT_BINARY = "/google/bin/releases/jetski-devs/tools/cli"`.
  - `_jetski_bin()` reads `SASE_JETSKI_PATH`, falls back to default, then `shutil.which("jetski-cli")`.
  - `invoke()` builds `[binary, "-p"]` plus optional `--conversation <id>` for interrupt follow-ups, pipes prompt via
    stdin.
  - Uses the extracted `monitor_interrupts()` helper (see below) instead of duplicating the thread.
  - Output parsing: start with `stream_process_output(..., clean_ansi=True)`; leave a TODO for a JSON variant once
    Jetski's `-p` output format is confirmed.
- `tests/test_llm_provider_jetski.py` — mirror `test_llm_provider_codex.py`; mock subprocess, test model resolution,
  env-var parsing, interrupt cycle.

### Modified files

- `src/sase/llm_provider/registry.py`
  - Add `"jetski"` to `_PROVIDER_MODEL_RE`.
  - Register `JetskiProvider` in `_register_builtin_providers()`.
  - Decide auto-detect priority: **do not** promote Jetski above Claude — extend `get_default_provider_name()` with a
    `shutil.which("jetski-cli")` probe **below** claude/codex but **above** gemini (so Google machines that have both
    Jetski and old Gemini CLI installed prefer Jetski).
  - Add known Jetski model names to `_MODEL_TO_PROVIDER` once confirmed.
- `src/sase/llm_provider/_subprocess.py`
  - Extract the interrupt-monitor thread pattern (currently duplicated in `claude.py:186-210`, `gemini.py:194-216`,
    `codex.py:~190-210`) into a `start_interrupt_monitor(process, artifacts_dir, on_interrupt)` helper. Update the three
    existing providers to use it in the same PR.
- `src/sase/main/init_skills_handler.py`
  - Extend `ALL_PROVIDERS` to include `"jetski"`.
  - Add a `PROVIDER_CONTEXT["jetski"]` entry (`provider_name="Jetski"`, `provider_tool_name="Jetski CLI"`,
    `provider_native_ask_tool="ask_user"` — Jetski's native ask tool name to be confirmed).
  - Introduce a `_SKILL_DEPLOY_SUBPATH` map `{"jetski": ".gemini/jetski"}` and update `_get_target_path` to consult it,
    defaulting to `f".{provider}"` for everyone else. Same logic for chezmoi path (`dot_gemini/jetski` instead of
    `dot_jetski`).
- `src/sase/default_config.yml` — optional: document `SASE_JETSKI_PATH` and the `llm_provider.provider: jetski` setting.
- `memory/short/gotchas.md` — add a one-liner about Jetski's non-standard `~/.gemini/jetski/skills/` deploy path so
  future contributors don't "fix" the override map.

### Non-goals for the first PR

- Don't introduce Alt 5's "google" family namespace.
- Don't rewrite Claude/Codex interrupt handling beyond swapping in the extracted helper.
- Don't add JSON output parsing for Jetski until we have real `jetski-cli -p` output to test against.

## Open Questions (to resolve before coding)

1. **What format does `jetski-cli -p <prompt>` emit on stdout?** Plain text, JSON, or NDJSON? Spike with
   `jetski-cli -p "hello" > out.txt` to confirm.
2. **Does Jetski expose a CLI flag for model selection**, or is `/model` only available interactively? If CLI-level
   selection is absent, we need a config-driven default and can't support `%model jetski/<model>` meaningfully.
3. **What are the canonical Jetski model names** we should register in `_MODEL_TO_PROVIDER`?
4. **Does `-p` support `--continue` / `--conversation <id>`?** The docs show these flags for interactive launch; need to
   confirm they work in non-interactive mode so we can implement real session resume for interrupts.
5. **Token-usage reporting?** Claude returns token counts via stream-json; Jetski's `-p` output may or may not include
   them.
6. **Native ask-user tool name**, for `PROVIDER_CONTEXT["jetski"]`. The docs mention tool-use with confirmation but
   don't name the ask-user tool equivalent to Claude's `AskUserQuestion`.

A ~15-minute spike on a Cloudtop (`jetski-cli -p "say hello in json"`, `jetski-cli -p --continue "followup"`,
`jetski-cli --help`) would answer 1–4 cheaply and let the implementation PR land with concrete choices rather than
guesses.
