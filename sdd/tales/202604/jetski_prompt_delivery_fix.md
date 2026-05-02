---
create_time: 2026-04-22 14:40:03
status: done
prompt: sdd/prompts/202604/jetski_prompt_delivery_fix.md
---

# Fix Jetski Prompt Delivery: Positional Argument, Not Stdin

## Problem

A `sase ace` run on a Google-corp machine (logpack at `~/tmp/260422_114703/`) invoked the jetski provider for the
`#cldd` xprompt ("Describe what this CL does"). The run reported SUCCESS in 11s of Jetski time, but the entire model
response was one line:

```
I am currently running on the Gemini Next model.
```

That is not a CL description — it is the kind of generic self-identification a model emits when the prompt it receives
carries no actual request. The user saw this in `sase ace` and correctly inferred "jetski integration isn't working."

Evidence from the logpack:

- `artifacts/pat/artifacts/ace-run/20260422114618/agent_meta.json`: `"llm_provider": "jetski"`,
  `"model": "jetski-default"` — so we did dispatch to `JetskiProvider`.
- `workflows/pat_fix_pg_2_ace-run-260422_114618.txt`: "✅ Waiting for Jetski completed in 00:11" — jetski-cli ran, took
  ~11s, exited 0.
- `artifacts/.../live_reply.md` (49 bytes): `I am currently running on the Gemini Next model.` — the full reply.
- `artifacts/.../workflow-tmp_260422_114622-main_prompt.md`: the prompt that was supposed to be delivered — a real,
  multi-line request with `@file` context references.

## Root Cause (two bugs, one symptom)

The authoritative jetski-cli reference lives at `~/org/lib/docs/jetski_cli.txt`:

- Line 200: `/google/bin/releases/jetski-devs/tools/cli -p "explain what this repo does"` — the `-p` flag takes the
  prompt as a **positional argument**, not stdin.
- Lines 177–183: the ONLY documented CLI flags are `-p/--print`, `-c/--continue`, `--conversation <id>`. **There is no
  `--model` flag.**
- Line 473: "Use the `/model` command to switch between available AI models at runtime. The selection persists across
  sessions." — model selection is an interactive slash command that writes to `~/.gemini/jetski/cli/settings.json`.

`src/sase/llm_provider/jetski.py` currently violates both facts:

1. **Prompt channel is wrong** (`jetski.py:96-101` + `jetski.py:181-183`). We build `[bin, "-p", "--model", model]` and
   then `process.stdin.write(prompt)`. jetski-cli's `-p` mode does not read stdin, so our real prompt is discarded.
   jetski-cli then sees `-p` with no positional prompt plus unknown `--model jetski-default` tokens — the tokens likely
   get parsed as the prompt, the model has nothing real to respond to, and we get a self-identification fallback.
2. **`--model` is not a CLI flag** (`jetski.py:96-101`). It is not in the documented flag table. Passing it wastes argv
   slots at best, corrupts the prompt at worst.

An existing draft at `~/.sase/plans/jetski_prompt_mode_fix.md` identified bug 1 but preserved `--model`. That is not a
complete fix — both bugs must be addressed together.

## Goal

After this change, `JetskiProvider.invoke()` produces a single, documented invocation pattern:

```
jetski-cli -p "<full prompt text>"
```

with nothing written to stdin. The interrupt-retry loop keeps working by rebuilding the prompt string (Gemini-style
concat of `--- Your Previous Response --- / --- User Follow-up ---`) and re-invoking jetski-cli with the rebuilt prompt
as the new positional argument.

Model selection stays in the Python API surface — `resolve_model_name()`, `model_override`, the `_DEFAULT_MODEL`
constant — but **nothing** is passed on the jetski-cli command line. The `model_tier` / `model_override` plumbing stays
because all providers share the abstract interface; a follow-up can wire model selection through
`~/.gemini/jetski/cli/settings.json` once we decide how sase should own that file.

## Approach

### 1. Fix `src/sase/llm_provider/jetski.py`

Two edits, both in `invoke()` / `_run_subprocess()`:

**A. Command construction (`jetski.py:93-101`).** Replace the current argv builder with a positional-prompt form:

```python
# Jetski CLI convention (per go/jetski-cli-getting-started):
#   jetski-cli -p "<prompt>"
# Prompt is positional after -p; stdin is NOT read in -p mode.
# --model is not a CLI flag — use the interactive /model slash command
# (persists to ~/.gemini/jetski/cli/settings.json) to change the active model.
base_args = [_jetski_bin(), "-p", current_prompt]
```

Move `base_args` construction inside the retry loop (so the rebuilt prompt on interrupt-cycle N actually becomes the
argv for cycle N+1). Drop `model` / `model_override` from argv entirely. Delete the
`# TODO(open-question-2): confirm --model is accepted in -p mode.` comment — open question 2 is now answered: it isn't.

**B. Subprocess plumbing (`jetski.py:157-195`).** In `_run_subprocess()`, keep `stdin=subprocess.PIPE` on the `Popen`
call (it's harmless, and keeping it keeps the signature symmetric with the other providers), but **delete the
`if process.stdin: process.stdin.write(prompt); process.stdin.close()` block**. Jetski-cli will see an empty/closed
stdin and ignore it; the prompt is in argv.

Keep the interrupt-monitor registration and `stream_process_output(...)` call unchanged. Both are orthogonal to the
prompt channel.

### 2. Update `tests/test_llm_provider_jetski.py`

- **`test_jetski_provider_command_uses_p_mode`** — currently just asserts `"-p" in cmd`. Strengthen to: `"-p"` is
  present, the token immediately following `-p` is the prompt text passed to `invoke()`, and no entry in `cmd` starts
  with `--model`.
- **`test_jetski_provider_model_override`** — currently asserts the model name appears in the argv. This is no longer
  true. Repurpose: assert that `model_override` does NOT appear in the argv (regression guard so we don't re-add the
  broken flag), and that the provider does not raise. Keep `resolve_model_name` covered by the existing
  `test_jetski_provider_resolve_model_name`.
- **`test_jetski_provider_interrupt_cycle_rebuilds_prompt`** — already uses the `_run_subprocess` seam; should still
  pass. Verify the `seen_prompts` assertions remain meaningful now that `prompt` arrives via argv rather than stdin (the
  seam receives `prompt` as a parameter, so the test isn't sensitive to this change).
- **New test `test_jetski_provider_does_not_write_to_stdin`** — mock `subprocess.Popen`; run `invoke()`; assert
  `popen.return_value.stdin.write` was never called and `popen.return_value.stdin.close` was never called. This is the
  regression that protects against re-introducing the stdin path in a future refactor.

### 3. Tidy companion files

- `~/.sase/plans/jetski_prompt_mode_fix.md` — leave in place (it's in the user's personal scratch area), but note in the
  PR description that the plan under-scoped the fix by preserving `--model`.
- `plans/202604/jetski_cli_provider.md` (status: done) — add a brief amendment section at the bottom noting the
  post-merge discovery that `-p` reads argv not stdin and `--model` isn't a flag, with a pointer to this plan.
- `sdd/research/202604/jetski_cli_provider.md` — update open question 2 ("Does Jetski expose a CLI flag for model selection") with
  the answer: "No — model selection is via the `/model` slash command, persisted to
  `~/.gemini/jetski/cli/settings.json`. A follow-up plan should decide whether sase owns that file."

### 4. Run `just check`

`just install` first (this may be a cold workspace), then `just check`.

## Files to change

- `src/sase/llm_provider/jetski.py` — argv builder, remove stdin write, refresh comments.
- `tests/test_llm_provider_jetski.py` — strengthen existing tests, repurpose model-override test, add stdin-unused
  regression test.
- `plans/202604/jetski_cli_provider.md` — short amendment block (~5 lines) at the bottom.
- `sdd/research/202604/jetski_cli_provider.md` — resolve open question 2.

## Sequencing

One commit is sufficient — the two bugs are a single mis-reading of the docs and need to be fixed together. Splitting
would leave jetski half-broken between commits.

1. Edit `jetski.py`.
2. Edit tests; run `pytest tests/test_llm_provider_jetski.py` to confirm fast feedback.
3. Amend docs (plan + research).
4. `just check`.
5. Commit (per user's commit workflow).

## Validation

**Unit / static:** `just check` passes — the new stdin-unused test is the strongest regression signal for bug 1; the "no
`--model` in argv" assertion is the regression signal for bug 2.

**Manual validation on a corp machine** (for the user after the change lands): re-run the same `sase ace` flow that
produced the broken logpack. Expected: the CL description reply is an actual multi-sentence description, not a
self-identification one-liner. If the user ever needs to change models, they do it once interactively via `/model`; that
persists in `~/.gemini/jetski/cli/settings.json` and applies to all subsequent `-p` invocations.

## Out of scope

- **Real session resume via `--conversation <id>`** — still the right direction per the original research doc's open
  question 4, but blocked on a Cloudtop spike to confirm `-p` + `--conversation` compose. Leave the Gemini-style concat
  fallback in place; the TODO already flags this.
- **Structured output parsing** — `-p` output format (plain / JSON / NDJSON) is still unconfirmed. Keep
  `stream_process_output(clean_ansi=True)` as-is.
- **sase-owned `settings.json` for model selection** — out of scope here; would be its own plan. Users who want
  non-default jetski models must invoke `/model` interactively once.
- **The sase-google plugin** — unrelated; it supplies Hg/VCS workflows and happens to be installed on the same machine.
  No changes needed there.

## Risks

- **Argv length limits.** The prompt is now an argv entry. Linux `ARG_MAX` is ≥128 KB on every platform sase targets,
  and the observed prompts (including dynamic memory and xcmd context) run ~500 B–a few KB. No risk in practice; if we
  ever approach the ceiling in a coder-resume scenario, we add a `--prompt-file <path>` probe for jetski-cli (not in
  docs today) or switch to a temp file. Not doing either now.
- **Hidden stdin-reading mode.** If a future jetski-cli version reads stdin as a prompt-append channel in `-p`, our
  empty stdin is still correct: close-empty means "no additional input." Keeping `stdin=subprocess.PIPE` preserves the
  ability to send Ctrl-D signals if that ever matters.
- **`_pending_interrupt_message` path.** The rebuilt-prompt string on interrupt cycle N must be the value written into
  `current_prompt` for cycle N+1 AND passed into the new `base_args` for cycle N+1. Moving `base_args` construction
  inside the `while True` loop is how we guarantee that. Miss this and interrupt-retry would reuse the original prompt —
  tested by `test_jetski_provider_interrupt_cycle_rebuilds_prompt`.

## What will NOT change

- `resolve_model_name()` still returns `_DEFAULT_MODEL` — the Python-side abstraction stays uniform across providers.
- `agent_meta.json` / `done.json` will keep reporting `model: jetski-default` / `llm_provider: jetski` — those come from
  the dispatch layer, not from jetski-cli, so they stay meaningful for telemetry and TUI display.
- The interrupt-monitor helper, artifacts-dir plumbing, and retry config all stay as-is.
