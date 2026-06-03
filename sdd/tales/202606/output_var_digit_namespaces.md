---
create_time: 2026-06-02 23:12:36
status: done
prompt: sdd/prompts/202606/output_var_digit_namespaces.md
---
# Output Variable Digit Namespace Plan

## Context

Prompt fan-out for `#plan #m_opus_codex` failed while launching `bob-cli`:

- The TUI model fan-out generated planned child names like `0n.cld` and `0o.cld`.
- `launch_multi_prompt_agents()` treats each already-planned fan-out child as a named segment and records it as an
  upstream output-variable producer for later segments.
- `build_agent_var_upstream_record()` immediately derives a Jinja namespace from that agent name.
- The current namespace normalizer only replaces hyphens with underscores, then requires every dot-separated component
  to already be a valid Jinja identifier. `0n.cld` fails because `0n` starts with a digit.

The related commits are the output-variable handoff commit (`1d0cd1140`) and the plan-family naming commit
(`d71af00c9`). The double-dash family separator change is not the direct bug; it just makes it clearer that
digit-leading auto names and dotted fan-out runtime suffixes are valid SASE names but not always valid Jinja
identifiers.

## Goal

Allow valid generated SASE agent names, especially digit-leading auto/fan-out names such as `0n.cld`, to participate in
output-variable handoff without failing launch. Preserve the existing readable namespace behavior for normal names:

- `build-agent` remains `build_agent`
- `research.final-@` remains `research.final`
- `0n.cld` becomes `_0n.cld`

## Proposed Design

Update `src/sase/agent/output_variable_context.py` with a small namespace-component normalizer:

- Keep dot-separated nesting.
- Keep the existing hyphen-to-underscore conversion.
- If a component starts with a digit, prefix it with `_`.
- Continue rejecting empty components and components that still are not valid Jinja identifiers after that
  normalization.

This is deliberately narrower than a broad slugifier. It fixes generated auto/fan-out names while avoiding silent
renaming of arbitrary unsupported characters such as spaces or slashes.

Apply the same normalization path anywhere a namespace is derived from an agent name or indexed-name template. Leave
stored explicit `namespace` values in upstream JSON validated as-is, because those are already the serialized normalized
contract.

Update the output-variable docs and `/sase_var` skill text to mention the digit-prefix rule.

## Tests

Add focused coverage in `tests/test_agent_output_variable_context.py`:

- Digit-leading names normalize to `_0n`.
- Dotted digit-leading fan-out names normalize to `_0n.cld`.
- Digit-leading nested components normalize, for example `build.3` to `build._3`.
- Existing invalid-character behavior still raises for a non-Jinja-safe component after normalization.
- Context loading can expose output variables under the normalized `_0n.cld` namespace.

Add a launcher regression in `tests/test_multi_prompt_launcher_launch.py`:

- Simulate the TUI model-fanout handoff with already-planned segments like `%name:0n.cld` and `%name:0n.cdx`.
- Assert the launch no longer raises.
- Assert the second segment receives `SASE_AGENT_VAR_UPSTREAMS_JSON` containing namespace `_0n.cld`.

## Verification

Run the normal workspace setup first, then focused tests, then the repo-required check:

```bash
just install
.venv/bin/python -m pytest -q tests/test_agent_output_variable_context.py tests/test_multi_prompt_launcher_launch.py
just check
```

## Non-Goals

- Do not change agent-name allocation or fan-out naming.
- Do not loosen output-variable key validation.
- Do not modify memory files.
- Do not broaden this into partial fan-out cleanup/report wording unless a test failure exposes it as necessary.
