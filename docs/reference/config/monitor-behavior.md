---
title: "Monitor configuration"
description: "Settings for monitor execution, wrappers, and continuation."
---

# Monitor configuration

Settings for monitor execution, wrappers, and continuation.

## monitor

Controls which monitors run their command inside `sase tool run` and the amount of
command evidence projected into a monitor continuation prompt. The evidence limits do
not change the monitor's bounded rotating log or the output available to
`sase monitor show`; they bound only automatically selected prompt content.

```yaml
monitor:
  tool_wrap: verify
  evidence_limits:
    selected_diagnostics_bytes: 8192
    fallback_tail_bytes: 4096
    total_raw_excerpt_bytes: 12288
    raw_tail_lines: 200
```

[Generated reference for `monitor`](runtime.md#monitor)

`selected_diagnostics_bytes` and `fallback_tail_bytes` must each be no larger than
`total_raw_excerpt_bytes`. The runtime falls back to all four packaged defaults if that
relationship is invalid; schema validation rejects non-positive values. Strict
`--next-output file` and `none` policies still embed no raw command output.

An unrecognized `tool_wrap` value falls back to `verify` at runtime. Wrapping changes
only the argv the proc supervisor execs, never the recorded monitor command; see
[Tool-run wrapping](../automation/monitors.md#tool-run-wrapping) for the per-command
rules.

Source: `src/sase/default_config.yml`, `src/sase/config/_settings_display.py`,
`src/sase/config/sase.schema.json`, `src/sase/monitor/result_projection.py`,
`src/sase/monitor/tool_wrap.py`

## Related

- [Runtime and stored data configuration](runtime.md) — generated monitor keys and
  defaults.
- [Monitors](../../monitors.md) — monitor lifecycle and operation.
