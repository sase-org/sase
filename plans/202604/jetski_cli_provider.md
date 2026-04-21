---
create_time: 2026-04-21 17:32:51
status: wip
---

# Add `JetskiProvider` LLM Backend (keeping Gemini CLI)

_Implements Alt 4 from `research/jetski_cli_provider.md`._

## Problem

Google is sunsetting Gemini CLI in favor of **Jetski CLI** — a new TUI that ships the same agent capabilities as the
Jetski IDE, with a non-interactive `-p / --print` mode suitable for `sase` invocation. Sase's Gemini provider will not
continue to work indefinitely, but some machines will still have old Gemini CLI installed during a transition period, so
both must coexist.

Jetski is architecturally closer to Claude than to Gemini:

- Native conversation resume via `--continue` / `--conversation <id>` (cf. Gemini's stateless "rebuild context as a
  string" model).
- Alt-screen / structured output / native skills / hooks / MCP — feature parity with Claude Code.
- Config and skill directory lives at `~/.gemini/jetski/…` (shares the `~/.gemini/` parent with Gemini CLI, but is
  otherwise independent).

## Goal

Add a first-class `JetskiProvider` (registered as `jetski`) that mirrors the standalone-class idiom used by
`CodexProvider` and `GeminiProvider`, while paying down one piece of duplication that a fourth provider would make
worse: the interrupt-monitor thread currently copy-pasted across all three existing providers.

Concretely, after this plan lands:

- `%model jetski/<model>` and `llm_provider.provider: jetski` in config both work.
- `sase init-skills --provider jetski` deploys skills to `~/.gemini/jetski/skills/…` (not `~/.jetski/skills/…`).
- The old `GeminiProvider` is untouched beyond a one-line swap to call the new shared interrupt-monitor helper.
- On a machine where both `jetski-cli` and the old `gemini` binary are on `$PATH`, auto-detect prefers Jetski, but
  Claude and Codex still win over Jetski.

## Approach

Two separable changes, bundled into one PR for review coherence but cleanly sequenced so that each is reviewable in
isolation:

### Step 1 — Extract shared `start_interrupt_monitor` helper

Same interrupt-monitor code is duplicated almost character-for-character across three files:

- `src/sase/llm_provider/claude.py:195-210`
- `src/sase/llm_provider/codex.py:193-208`
- `src/sase/llm_provider/gemini.py:201-216`

Each spins a daemon thread that polls `${SASE_ARTIFACTS_DIR}/interrupt_request.json`, reads the message, unlinks the
file, and calls `process.terminate()`. The only per-provider variation is how the parent class stores the interrupt
message (all three use `self._pending_interrupt_message = data.get("message")`).

Extract into `src/sase/llm_provider/_subprocess.py`:

```python
def start_interrupt_monitor(
    process: subprocess.Popen,
    on_interrupt: Callable[[str], None],
) -> None:
    """Spin a daemon thread that watches for interrupt_request.json.

    When the file appears, invoke ``on_interrupt(message)`` (with the
    "message" field from the JSON) and call ``process.terminate()``.
    Reads SASE_ARTIFACTS_DIR from the environment; no-op if unset.
    """
```

Update all three existing providers to call
`start_interrupt_monitor(process, on_interrupt=lambda m: setattr(self, "_pending_interrupt_message", m))` (or,
preferably, a small named method). Behavior must be bit-identical — no timing changes, no retry changes, no logging
changes. This is purely a cut/paste → helper extraction.

### Step 2 — Add `JetskiProvider`

**New file `src/sase/llm_provider/jetski.py`** (~200 lines, mirroring `codex.py` structure):

- Module-level `_DEFAULT_BINARY = "/google/bin/releases/jetski-devs/tools/cli"` (from Jetski install docs).
- `_jetski_bin()` resolves in order: `SASE_JETSKI_PATH` env → default path if it exists on disk → `"jetski-cli"` (PATH
  lookup, for users who aliased the long path).
- `class JetskiProvider(LLMProvider)` with `_pending_interrupt_message: str | None = None`.
- `resolve_model_name()` returns a single default model string until canonical Jetski model names are confirmed (open
  question 3 in the research doc). Accept `model_override` verbatim.
- `invoke()` builds `[binary, "-p"]` plus (for interrupt cycles) `--conversation <id>` once session-resume behavior is
  confirmed. **For the first PR**, implement the Gemini-style "rebuild prompt as string" fallback (with the same
  `--- Your Previous Response --- / --- User Follow-up ---` structure) so interrupt works immediately; leave a TODO with
  a `conversation_id` placeholder for the session-resume upgrade.
- Output parsing: `stream_process_output(..., clean_ansi=True)`. Leave a TODO for JSON/NDJSON parsing (open question 1).
- `_run_subprocess` uses the new `start_interrupt_monitor` helper (no duplicated thread code).

**`src/sase/llm_provider/registry.py`:**

- Extend `_PROVIDER_MODEL_RE` (line 38) to `r"^(claude|codex|gemini|jetski)/(.+)$"`.
- Import and register `JetskiProvider` in `_register_builtin_providers()` (lines 142-150).
- Update `get_default_provider_name()` (lines 123-139): after `shutil.which("codex")`, add
  `if shutil.which("jetski-cli"): return "jetski"`, _then_ fall through to `"gemini"`. Priority chain becomes claude →
  codex → jetski → gemini.
- Do **not** add Jetski model names to `_MODEL_TO_PROVIDER` yet — pending open question 3.

**`src/sase/main/init_skills_handler.py`:**

- Add `"jetski"` to `ALL_PROVIDERS` (line 17).
- Add `PROVIDER_CONTEXT["jetski"]` entry:
  ```python
  "jetski": {
      "provider_name": "Jetski",
      "provider_tool_name": "Jetski CLI",
      "provider_native_ask_tool": "ask_user",  # TODO: confirm on Cloudtop
  },
  ```
- Introduce a `_SKILL_DEPLOY_SUBPATH` override map at module scope:
  ```python
  # Provider → subdirectory under ~/ (or under CHEZMOI_HOME) where skills deploy.
  # Defaults to f".{provider}" if not listed.
  _SKILL_DEPLOY_SUBPATH: dict[str, str] = {
      "jetski": ".gemini/jetski",
  }
  ```
- Update `_get_target_path` (lines 47-51) to consult the map for both branches:
  ```python
  subpath = _SKILL_DEPLOY_SUBPATH.get(provider, f".{provider}")
  if use_chezmoi:
      # "dot_" prefix on each path segment so chezmoi treats them as dotfiles
      chezmoi_subpath = Path(*(f"dot_{p}" if i == 0 else p for i, p in enumerate(subpath.split("/"))))
      # For jetski: dot_gemini/jetski (not dot_gemini/dot_jetski — nested dirs aren't dotfiles).
      return CHEZMOI_HOME / chezmoi_subpath / "skills" / skill_name / "SKILL.md"
  return Path.home() / subpath / "skills" / skill_name / "SKILL.md"
  ```
  (Double-check the chezmoi `dot_` convention against an existing deployed file before finalizing — the exact
  transformation may need tweaking so that `~/.gemini/jetski/…` round-trips correctly.)

**`src/sase/default_config.yml`** (lines 205-222): add a `jetski` retry block mirroring `gemini`/`claude`, with sensible
defaults copied from gemini's. Example:

```yaml
jetski:
  max_retries: 3
  error_patterns:
    - "An unexpected critical error occurred:"
  wait_times: [60, 300, 1800]
  fallback_model: "" # TODO: fill in once model names confirmed
```

**`memory/short/gotchas.md`:** one-liner noting that Jetski's skill-deploy path is `~/.gemini/jetski/skills/` (not
`~/.jetski/skills/`) by design, so the `_SKILL_DEPLOY_SUBPATH` override map should not be "fixed".

### Step 3 — Tests

**New `tests/test_llm_provider_jetski.py`** mirroring `tests/test_llm_provider_codex.py`. Cover:

- `JetskiProvider` is a `LLMProvider` subclass.
- `resolve_model_name()` returns the expected default.
- `SASE_JETSKI_PATH` env var overrides the hardcoded default.
- When env var is unset and default path doesn't exist on the test machine, `_jetski_bin()` returns `"jetski-cli"`.
- `model_override` is passed through to the command line (once model-flag syntax is confirmed — initial test can assert
  the model string appears in the command, agnostic of exact flag name).
- `invoke()` raises `subprocess.CalledProcessError` on non-zero exit.
- Interrupt cycle: one interrupt → prompt is rebuilt with "Previous Response" concat → second invocation succeeds and
  returns accumulated response. (Upgrade this test when session-resume is implemented in a follow-up.)

**Extend `tests/test_llm_provider_codex.py` or add `tests/test_llm_provider_subprocess.py`** with a unit test for the
new `start_interrupt_monitor` helper:

- Mock a `subprocess.Popen` whose `.poll()` returns `None` then an int.
- Drop an `interrupt_request.json` into a tmp artifacts dir.
- Assert the `on_interrupt` callback fires with the correct message, the file is unlinked, and `process.terminate()` is
  called.

## Files to change

- New: `src/sase/llm_provider/jetski.py`
- New: `tests/test_llm_provider_jetski.py`
- New: `tests/test_llm_provider_subprocess.py` (or extend existing, if one exists — check before creating)
- Modified: `src/sase/llm_provider/_subprocess.py` (add `start_interrupt_monitor`)
- Modified: `src/sase/llm_provider/claude.py` (swap in helper)
- Modified: `src/sase/llm_provider/codex.py` (swap in helper)
- Modified: `src/sase/llm_provider/gemini.py` (swap in helper)
- Modified: `src/sase/llm_provider/registry.py` (register + regex + auto-detect)
- Modified: `src/sase/main/init_skills_handler.py` (ALL_PROVIDERS + PROVIDER_CONTEXT + deploy-path override)
- Modified: `src/sase/default_config.yml` (retry block)
- Modified: `memory/short/gotchas.md` (one-liner about deploy-path override)

## Sequencing

1. Step 1 (extract helper + update 3 providers + helper test) → run `just check`. Keep as the first commit so the
   refactor is reviewable on its own.
2. Step 2 (add `JetskiProvider` + registry + skills-handler + default_config) → run `just check`.
3. Step 3 (Jetski-specific tests) → run `just check`.
4. Docs tweaks (`gotchas.md`, any changelog).

Splitting Steps 1 and 2 across separate PRs is an option if reviewers prefer; the plan does not require it.

## Pre-flight checks (15-min Cloudtop spike before merge, not before coding)

These match the "Open Questions" section of the research doc. Code can land with TODOs keyed to each; the spike answers
each question and we swap real values in before merge:

1. **Output format of `jetski-cli -p`** (plain text? JSON? NDJSON?). If JSON/NDJSON, decide whether to write a dedicated
   parser or defer to follow-up.
2. **Model selection via CLI flag**. Is `--model` supported in `-p` mode, or is `/model` interactive-only?
3. **Canonical Jetski model names** (for `_MODEL_TO_PROVIDER` and `resolve_model_name()`).
4. **Does `-p` support `--continue` / `--conversation <id>`?** If yes, upgrade interrupt handling from Gemini-style
   concat to Claude-style session resume.
5. **Token usage reporting** in `-p` output (for `InvokeResult.usage`).
6. **Native ask-user tool name** for `PROVIDER_CONTEXT["jetski"]["provider_native_ask_tool"]`.

## Out of scope (explicit non-goals for this PR)

- Alt 5's "google" provider family / namespace consolidation.
- Rewriting Claude/Codex/Gemini interrupt handling beyond the mechanical helper swap.
- Adding any JSON/NDJSON parser for Jetski (deferred until the Cloudtop spike confirms the output format).
- Adding Jetski model names to `_MODEL_TO_PROVIDER` (deferred; `%model jetski/<explicit>` works via the regex in the
  meantime).
- Promoting Jetski above Claude/Codex in the auto-detect chain.
- Any change to the Gemini CLI provider's retry config, PTY handling, or model names.

## Risks and mitigations

- **Risk:** The extracted `start_interrupt_monitor` subtly changes timing (e.g., different sleep interval) and breaks
  interrupt semantics for a provider that was silently relying on that timing. **Mitigation:** Copy the 1.0-second poll
  interval verbatim; do not "improve" it in this PR. Keep the three providers' call sites side-by-side in the same
  commit so a diff review can verify identity.
- **Risk:** The `_SKILL_DEPLOY_SUBPATH` map + chezmoi-prefix logic produces the wrong path for Jetski (e.g., deploys to
  `~/.gemini/dot_jetski/skills/` instead of `~/.gemini/jetski/skills/`). **Mitigation:** Add a test covering both the
  regular-home and chezmoi branches for a provider that has a `/`-containing subpath. Verify the exact chezmoi
  convention by inspecting an existing `dot_claude/` or `dot_gemini/` directory before finalizing the logic.
- **Risk:** On a Google corp machine without Claude/Codex installed but with Jetski _and_ old Gemini CLI both on
  `$PATH`, the auto-detect change flips the default from `gemini` to `jetski` for users who didn't configure
  `llm_provider.provider` explicitly. **Mitigation:** This is the desired behavior per the goal statement, but document
  the change in the PR description so users who relied on the implicit gemini default know to pin it explicitly if they
  want to stay on Gemini during the transition.
- **Risk:** The Gemini-style "Previous Response" concat interrupt fallback produces a degraded experience compared to
  real session resume, and users notice. **Mitigation:** Clearly marked TODO in `jetski.py` pointing to the
  session-resume follow-up; the Cloudtop spike is scheduled pre-merge so in practice the upgrade lands in the same PR if
  the answer to open question 4 is "yes".
