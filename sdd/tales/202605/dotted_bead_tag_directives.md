---
create_time: 2026-05-05 22:38:58
status: done
prompt: sdd/prompts/202605/dotted_bead_tag_directives.md
---
# Plan: Accept Dotted Bead IDs In `%tag` Directives

## Problem

The `sase ace` snapshot shows repeated launch failures while processing an epic land-agent prompt:

```text
%name:sase-42.3
%tag:sase-42.3
%w:sase-42.3.1,...
#bd/land_epic:sase-42.3
```

The failure happens before the agent prompt is written:

```text
DirectiveError: Invalid '%tag' value: tag name 'sase-42.3' must match ^[A-Za-z0-9_-]+$
```

Commit `1ab48ecfcb5c` is relevant because it moved epic work rendering toward bead-driven launch tags for legend-linked
work. That commit, plus the matching `sase-core` change, is the right semantic direction: phase and land agents should
remain named after the working bead, while `%tag` groups them by the controlling bead. The immediate failure is that the
`%tag` directive and persisted agent-tag validation still reject dots, even though generated bead IDs commonly use
dotted hierarchy such as `sase-42.3` and `sase-42.3.1`.

## Target Behavior

- `%tag:sase-42.3` is accepted by directive extraction and persisted agent-tag storage.
- Existing valid tags like `review`, `Release-Blocker_42`, and `sase-42` continue to work.
- Invalid tags remain invalid:
  - empty strings
  - `@`-prefixed input
  - whitespace and other punctuation not intentionally supported
- Agent search can match dotted tags naturally with `tag:sase-42.3`, not only with quoted `tag:"sase-42.3"`.
- Bead work rendering keeps the `1ab48ecfcb5c` separation:
  - `%name` and `%w` stay agent/bead specific.
  - `#bd/work_phase_bead:<phase_id>` and `#bd/land_epic:<epic_id>` stay bead specific.
  - `%tag` may be the legend ID or epic ID depending on `launch_tag_id`, but either value is valid if dotted.

## Implementation Approach

1. Update the canonical agent-tag validator.
   - In `src/sase/ace/agent_tags.py`, expand `TAG_NAME_RE` from `^[A-Za-z0-9_-]+$` to include dot.
   - Update the module docstring, `validate_tag_name()` docstring, and error message so the contract is accurate.
   - Keep all callers using `validate_tag_name()` rather than adding local bead-work sanitization.

2. Update agent query tokenization for dotted property values.
   - The query evaluator already compares tag strings directly.
   - The tokenizer currently parses unquoted property values with the same restricted bare-word character set, so
     `tag:sase-42.3` would stop at `sase-42`.
   - Add or adjust the property-value character helper to accept dots for property values while preserving the existing
     bare-word grammar for free text if that is safer for query parsing.

3. Add focused regression tests.
   - `tests/test_agent_tags.py`: assert `validate_tag_name("sase-42.3")` succeeds and malformed dotted variants still
     fail when appropriate.
   - `tests/test_directives_extract.py`: assert `%tag:sase-42.3` extracts cleanly and returns
     `directives.tag == "sase-42.3"`.
   - `tests/test_agent_query_tokenizer.py` and/or parser tests: assert `tag:sase-42.3` tokenizes/parses as one property
     value.
   - `tests/test_bead/test_work_rendering.py`: add a direct rendering regression for an `EpicWorkPlan` or seeded bead
     with a dotted `launch_tag_id`, then run each rendered segment through directive extraction so the snapshot failure
     is covered at the same boundary that crashed.

4. Verify the local Rust/Python boundary stays aligned.
   - Do not move tag normalization into Python bead rendering; the backend should keep deciding `launch_tag_id`.
   - Confirm the sibling `../sase-core` already has `launch_tag_id` support from `7b32ae0`.
   - Run `just install` before test/check commands so the local venv gets the current Rust binding, per repo memory.

5. Verification commands.
   - Focused tests first:
     `just test tests/test_agent_tags.py tests/test_directives_extract.py tests/test_agent_query_tokenizer.py tests/test_agent_query_parser.py tests/test_bead/test_work_rendering.py`
   - Then the repo-required final gate after changes: `just install` `just check`

## Risks And Notes

- This changes the global agent-tag contract, not only bead-work tags. That is intentional: `%tag` is the storage and UI
  grouping mechanism, and dotted bead IDs are first-class generated identifiers.
- Dot remains a conservative addition compared with accepting arbitrary punctuation; it avoids escaping or sanitizing
  bead IDs while keeping tag names easy to read and query.
- If a deployed `sase` command still uses an old `sase_core_rs` wheel without `launch_tag_id`, it may render the epic ID
  instead of the legend ID. This plan still prevents that fallback from crashing when the epic ID is dotted, while
  `just install` handles the local development alignment with the current core checkout.
