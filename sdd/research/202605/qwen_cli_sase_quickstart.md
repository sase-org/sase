# Qwen CLI Quickstart for SASE

Research date: 2026-05-12 (updated 2026-05-12 with full auth subcommand surface, autodetect priority caveat,
alternative routing paths, artifact locations, and `SASE_QWEN_PATH`)

## Goal

Start from an already installed Qwen Code CLI and run a small SASE prompt against this repository:

```bash
sase run "#cd(.) %model:qwen/qwen3-coder-flash Describe this repo."
```

Two prefixes are doing work here:

- `#cd(.)` selects the workspace. It tells SASE to run in the current directory without allocating a numbered VCS
  workspace. A bare `sase run "Describe this repo."` is **not** equivalent: prompts without a workspace reference are
  normalized to `#git:home`, and `home` must already be initialized (`sase init-git home --existing ... --clone-dir
  ...`) or the launch fails with a setup error.
- `%model:qwen/qwen3-coder-flash` forces SASE to route this prompt through the Qwen provider. Swap in
  `qwen/qwen3.6-plus` for SASE's larger Qwen tier. The bare form `%model:qwen3-coder-flash` also works because Qwen
  registers that model name (see [Routing options](#routing-options) for why you usually want this directive on the
  first run anyway).

## Quickstart

1. Confirm the CLI is installed:

   ```bash
   qwen --version
   ```

   Local check on this machine: `qwen` is installed at `/home/bryan/.config/nvm/versions/node/v22.14.0/bin/qwen` and
   reports version `0.15.10`.

2. Confirm Qwen authentication:

   ```bash
   qwen auth status
   ```

   The four configured auth flows surfaced by the installed CLI (`qwen auth --help`):

   | Subcommand | When to use |
   | --- | --- |
   | `qwen auth qwen-oauth` | Qwen OAuth — note that the free OAuth tier ended 2026-04-15, so this path now needs a paid Qwen account. |
   | `qwen auth coding-plan` | Alibaba Cloud Coding Plan subscription. |
   | `qwen auth openrouter` | Route Qwen models through OpenRouter using an OpenRouter API key. |
   | `qwen auth api-key` | Plain API key (Alibaba DashScope, Fireworks, or any OpenAI-compatible endpoint Qwen Code accepts). |

   Pick whichever matches your billing setup, run that subcommand once, then re-run `qwen auth status` to confirm.

3. Optional direct CLI smoke test (skips SASE entirely):

   ```bash
   qwen --input-format text --output-format stream-json --yolo \
        --model qwen3-coder-flash -p "Say OK."
   ```

   This verifies Qwen Code itself before adding SASE orchestration. The flag shape exactly matches what SASE's Qwen
   provider runs, so a failure here will also fail through SASE.

4. Run the SASE prompt from this repo:

   ```bash
   sase run "#cd(.) %model:qwen/qwen3-coder-flash Describe this repo."
   ```

   A more constrained first prompt is often easier to evaluate:

   ```bash
   sase run "#cd(.) %model:qwen/qwen3-coder-flash Describe this repo in three concise bullets."
   ```

## Routing Options

`%model:` on every invocation is the simplest path, but it is not the only one. SASE picks a default provider in this
order (`src/sase/llm_provider/registry.py`):

1. Explicit `provider_name=` argument to `invoke_agent()` (internal callers).
2. `%model` directive in the prompt — `provider/model`, a known bare model, or a configured alias.
3. Active temporary override at `~/.sase/llm_override.json` (the ACE `,P` chord writes this).
4. `llm_provider.provider` in `~/.config/sase/sase.yml`.
5. Auto-detection by plugin priority: claude=0, codex=10, qwen=15, opencode=18, gemini=last-resort.

Auto-detection is why Qwen does not "just run" by default on this machine: Claude and Codex auto-detect ahead of Qwen,
so SASE picks one of them unless you override. Two ways to make Qwen the persistent default:

- Edit `~/.config/sase/sase.yml`:

  ```yaml
  llm_provider:
    provider: qwen
    model_tier_map:
      large: qwen3.6-plus
      small: qwen3-coder-flash
  ```

- Or set a temporary override from the ACE TUI with the `,P` chord (choose `qwen/qwen3-coder-flash` and a duration). The
  override file expires automatically; see `docs/llms.md` § Temporary Default Override.

You can also force tier without changing provider — `SASE_MODEL_TIER_OVERRIDE=small sase run "..."` makes every
provider use its small-tier model for the launch.

## What SASE Does

SASE's Qwen provider (`src/sase/llm_provider/qwen.py`) launches Qwen Code in headless structured-output mode:

```bash
qwen --input-format text --output-format stream-json --yolo --model <model> [SASE_LLM_*_ARGS...]
```

SASE writes the prompt to stdin, reads Qwen's line-delimited `stream-json` events, extracts assistant text from
`assistant` events, and falls back to the final `result` text if no assistant text was emitted. Token counters from the
result event are persisted to `usage.json` (see [Output artifacts](#output-artifacts)).

Default SASE Qwen model mapping:

| SASE tier | Qwen model |
| --- | --- |
| `large` | `qwen3.6-plus` |
| `small` | `qwen3-coder-flash` |

Qwen Code itself reads config from `~/.qwen/settings.json` and an optional project-local `.qwen/settings.json`. SASE
does not create a shadow Qwen home, so any tweaks you make to those files (auth, default model, telemetry off, MCP
servers, hooks) apply to both direct `qwen` runs and SASE-launched ones.

### Custom Qwen Binary

If your Qwen binary is not on `PATH` (for example, you keep multiple node toolchains via nvm), point SASE at it
directly:

```bash
export SASE_QWEN_PATH=/home/bryan/.config/nvm/versions/node/v22.14.0/bin/qwen
```

This is the only Qwen-specific path knob; everything else is upstream Qwen settings or generic SASE config.

### Extra CLI Args

To pass additional flags to Qwen for a tier — for example `--debug` while smoke-testing — set one of:

```bash
export SASE_LLM_LARGE_ARGS="--debug"   # all providers, large tier
export SASE_QWEN_LARGE_ARGS="--debug"  # Qwen-only fallback when generic is unset
```

The generic `SASE_LLM_*_ARGS` takes precedence over `SASE_QWEN_*_ARGS`. Values are whitespace-split and appended to the
command.

## Output Artifacts

When SASE runs an agent it sets `SASE_ARTIFACTS_DIR`. Useful files for a Qwen run:

| Path | What's in it |
| --- | --- |
| `<artifacts>/live_reply.md` | Streamed assistant text, written as it arrives. The ACE TUI's reply pane reads from here. |
| `<artifacts>/usage.json` | Final token counters (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`). |
| `<artifacts>/<agent_type>_prompt.md` | The fully preprocessed prompt that was sent to Qwen. |
| `<artifacts>/sase.md` | Append-only timestamped log of `(prompt, response)` pairs for the agent. |

`sase run --resume` can resume a prior conversation by agent name or chat-history file; that path goes through the
`#resume` workflow and prepends the prior history to the new prompt. See `docs/llms.md` § Resume Support.

## Local Verification Notes

- `qwen --version` → `0.15.10`.
- `qwen auth status` → `Standard API Key` auth configured, current model `qwen3.5-plus` (the configured-model field is
  Qwen's own default; SASE always overrides it with `--model qwen3-coder-{plus,flash}`).
- Direct CLI smoke test `qwen --input-format text --output-format stream-json --yolo --model qwen3-coder-flash -p "Say
  OK."` reached Qwen but returned `API Error: 401 Incorrect API key provided` — the configured API key on this machine
  is stale.
- The SASE command `sase run "#cd(.) %model:qwen/qwen3-coder-flash Describe this repo in three concise bullets."`
  reached the Qwen provider through SASE, used this repo as the workspace, and returned the same upstream 401. The
  command shape is verified; the machine needs `qwen auth api-key` (or another auth subcommand) re-run with a current
  key before the prompt produces a real model answer.
- `#cd:.` is **not** the right spelling for "here." In local testing the bare-`.` ref selected the `cd` workflow but
  failed during setup with a missing `cd_ref`. `#cd(.)` works because the parenthesized form bypasses the colon
  workspace-ref tokenizer that stops at whitespace and treats `.` ambiguously. The docs only enumerate the
  parenthesized form for the current directory (`docs/workspace.md`).

## Sources

- Qwen Code headless mode docs: <https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/>
- Qwen Code quickstart docs: <https://qwenlm.github.io/qwen-code-docs/en/users/quickstart/>
- Qwen Code authentication docs: <https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/>
- Qwen Code README: <https://github.com/QwenLM/qwen-code>
- Installed CLI surface, verified locally on 2026-05-12: `qwen --help`, `qwen auth --help`, `qwen auth status` against
  `qwen 0.15.10`.
- SASE Qwen provider implementation: `src/sase/llm_provider/qwen.py`
- SASE LLM provider docs (Qwen integration, model aliases, temporary override, retry/fallback, artifacts):
  `docs/llms.md`
- SASE workspace docs (`#cd` and `#git` references, `home` setup): `docs/workspace.md`
- SASE xprompt docs (`%model`, `provider/model`, alias resolution): `docs/xprompt.md`
- SASE configuration docs (env vars, CLI flags, override files): `docs/configuration.md`
- Prior research framing Qwen vs Claude/Codex in SASE: `sdd/research/202605/qwen_opencode_vs_codex_claude.md`
