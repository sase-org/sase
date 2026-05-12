# Qwen CLI Quickstart for SASE

Research date: 2026-05-12

## Goal

Start from an already installed Qwen Code CLI and run a small SASE prompt against this repository:

```bash
sase run "#cd(.) %model:qwen/qwen3-coder-flash Describe this repo."
```

Use `#cd(.)` for this first run. It tells SASE to run in the current directory without allocating a VCS workspace. A
bare `sase run "Describe this repo."` is not equivalent in this repo: prompts without an explicit workspace reference
normalize to `#git:home`, which requires the local `home` bare-git project to be initialized.

Use `%model:qwen/qwen3-coder-flash` to force SASE to route this prompt through Qwen. Swap in
`%model:qwen/qwen3-coder-plus` when you want SASE's larger Qwen tier.

## Quickstart

1. Confirm the CLI is installed:

   ```bash
   qwen --version
   ```

   Local check: `qwen` is installed at `/home/bryan/.config/nvm/versions/node/v22.14.0/bin/qwen` and reports
   version `0.15.10`.

2. Confirm Qwen authentication:

   ```bash
   qwen auth status
   ```

   If needed, configure auth before using SASE:

   ```bash
   qwen auth
   qwen auth api-key
   qwen auth coding-plan
   ```

   Qwen OAuth free-tier access ended on 2026-04-15, so use an API key, Alibaba Cloud Coding Plan, OpenRouter,
   Fireworks, or another supported provider instead.

3. Optional direct CLI smoke test:

   ```bash
   qwen -p "Say OK." --output-format stream-json --yolo
   ```

   This verifies Qwen itself before adding SASE orchestration.

4. Run the SASE prompt from this repo:

   ```bash
   sase run "#cd(.) %model:qwen/qwen3-coder-flash Describe this repo."
   ```

   A slightly more constrained first prompt is useful while testing:

   ```bash
   sase run "#cd(.) %model:qwen/qwen3-coder-flash Describe this repo in three concise bullets."
   ```

## What SASE Does

SASE's Qwen provider launches Qwen Code in headless structured-output mode:

```bash
qwen --input-format text --output-format stream-json --yolo --model <model>
```

SASE writes the prompt to stdin, reads Qwen's line-delimited `stream-json` events, extracts assistant text from
`assistant` events, and falls back to the final `result` text if no assistant text was emitted.

Default SASE Qwen model mapping:

| SASE tier | Qwen model |
| --- | --- |
| `large` | `qwen3-coder-plus` |
| `small` | `qwen3-coder-flash` |

## Local Verification Notes

- `qwen auth status` reported `Standard API Key` auth configured and current model `qwen3.5-plus`.
- A direct `qwen -p "Say OK." --output-format stream-json --model qwen3-coder-flash --yolo` reached Qwen but returned
  `API Error: 401 Incorrect API key provided`.
- The SASE command
  `sase run "#cd(.) %model:qwen/qwen3-coder-flash Describe this repo in three concise bullets."` reached the Qwen
  provider through SASE and used the current repo as the workspace, but returned the same upstream 401 text.
- Therefore the command shape is verified, but this machine needs a refreshed Qwen API key before the prompt produces
  a real model answer.
- `#cd:.` is not the recommended spelling for this quickstart. In local testing, `#cd:.` selected the `cd` workflow but
  failed during setup with a missing `cd_ref`; `#cd(.)` worked.

## Sources

- Qwen Code headless mode docs: <https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/>
- Qwen Code quickstart docs: <https://qwenlm.github.io/qwen-code-docs/en/users/quickstart/>
- Qwen Code authentication docs: <https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/>
- Qwen Code README: <https://github.com/QwenLM/qwen-code>
- SASE Qwen integration docs: `docs/llms.md`
- SASE workspace and `%model` directive docs: `docs/xprompt.md`
- SASE configuration docs: `docs/configuration.md`
