# Fakey Testing Provider

`fakey` is a deterministic fake agent CLI bundled with SASE. Its first-class `FakeyProvider` uses the same registry,
model selection, subprocess streaming, interrupt, usage, and retry plumbing as real providers, making it useful for
reproducible launch and failure tests. It never calls a model and should not be used for production coding work.

## Quick Start

The default scenario succeeds immediately:

```bash
printf 'hello\n' | fakey
```

Select fakey for one SASE launch with either model tier:

```text
%model:fakey-large
Exercise the launch path.
```

The provider maps `large` to `fakey-large` and `small` to `fakey-small`. It is deliberately the last autodetection
candidate because the executable is always installed with SASE; prefer explicit selection.

## Scenario Selection and Precedence

Scenario settings are layered from least to most specific:

1. Built-in success defaults.
2. Individual environment knobs.
3. `FAKEY_SCENARIO`, a YAML path or bundled `@name`.
4. A fenced `fakey` YAML block embedded in the prompt.

For example:

````text
Run a deterministic response.

```fakey
reply: embedded reply
usage: {input_tokens: 7, output_tokens: 3}
```
````

List bundled scenarios with `fakey --list-scenarios`. The initial set includes `@ok`, `@flaky`, `@flaky2`, `@crash`,
`@hang`, `@slow`, and `@capacity`. Use `fakey --scenario @flaky --explain` to print the resolved YAML without running
it.

## Scenario Grammar

```yaml
version: 1
reply: default success text
delay: 0
stream:
  chunk_delay: 0.05
usage:
  input_tokens: 7
  output_tokens: 3
attempts:
  - fail:
      message: model melted
      retryable: true
      exit_code: 1
      channel: stderr
    steps:
      - signal: /tmp/fakey-started
      - wait_for: { path: /tmp/fakey-release, timeout: 30 }
  - succeed:
      reply: second try worked
```

The attempt cursor persists in `FAKEY_STATE_DIR`; the final attempt repeats after the list is exhausted. A retryable
failure emits `FAKEY-RETRYABLE: <message>`, while other failures emit `FAKEY-FAIL: <message>`. The provider's built-in
retry config matches only the retryable marker, retries up to three times with no delay, and preserves workspace edits.

Steps support `signal`, `wait_for`, and `sleep`. Every `wait_for` has a timeout, and SIGTERM exits cleanly, which makes
barrier-based tests deterministic without timing sleeps.

## Environment Controls

| Variable                | Purpose                                                      |
| ----------------------- | ------------------------------------------------------------ |
| `FAKEY_SCENARIO`        | Scenario path or bundled name such as `@flaky`               |
| `FAKEY_REPLY`           | One-line success reply override                              |
| `FAKEY_FAIL_MESSAGE`    | One-line failure message                                     |
| `FAKEY_EXIT_CODE`       | Failure exit code                                            |
| `FAKEY_DELAY`           | Delay before the outcome                                     |
| `FAKEY_FAIL_TIMES`      | Fail this many invocations, then succeed                     |
| `FAKEY_STATE_DIR`       | Attempt cursor and `invocation-<n>.json` recording directory |
| `SASE_FAKEY_PATH`       | Override the provider's fakey executable                     |
| `SASE_FAKEY_LARGE_ARGS` | Extra provider args for the large tier                       |
| `SASE_FAKEY_SMALL_ARGS` | Extra provider args for the small tier                       |
| `SASE_LLM_LARGE_ARGS`   | Provider-neutral large-tier args; takes precedence           |
| `SASE_LLM_SMALL_ARGS`   | Provider-neutral small-tier args; takes precedence           |

Each invocation record contains argv, prompt, selected environment, resolved scenario and attempt, model, effort, and
outcome. This makes provider wiring assertions possible without mocking the subprocess.

## Testing Retries

For an interactive retry smoke test, set an isolated state directory and launch the bundled flaky scenario:

```bash
export FAKEY_STATE_DIR="$(mktemp -d)"
export FAKEY_SCENARIO=@flaky
sase run -m fakey-large 'Exercise retry handling'
```

The first invocation fails with `FAKEY-RETRYABLE`; SASE's provider defaults retry immediately, and the second invocation
succeeds. Inspect `$FAKEY_STATE_DIR/invocation-*.json` to verify both prompts, selected model, and outcomes. For tests,
prefer a temporary scenario file and `signal`/`wait_for` barriers so assertions can freeze and release exact pipeline
states without depending on wall-clock sleeps.
