---
create_time: 2026-04-03 14:44:42
status: done
prompt: sdd/prompts/202604/json_null_default_validation.md
---

# Plan: Allow null values for JSON schema fields with defaults

## Problem

When the `#split` xprompt workflow runs, the `#split_spec_generator` agent sometimes produces `parent: None` (or
`parent: null`) in its JSON output. The `#json` embedded workflow's `validate` step then rejects this with:

```
validation_error=At 1 -> parent: None is not of type 'string'
```

The schema definition is: `parent: { type: word, default: "" }` — meaning `parent` is optional (has a default). A null
value should be semantically equivalent to omitting the field.

## Root Cause

In `src/sase/xprompt/loader_parsing.py`, the `_parse_shortform_output_spec()` function only marks fields as nullable
when the default is literally `None`:

```python
if default is None:
    properties[field_name] = {"type": [type_str, "null"]}
else:
    properties[field_name] = {"type": type_str}
```

When `default: ""` (empty string), `default is None` is `False`, so the generated schema becomes `{"type": "word"}` —
which does NOT accept null. The fix needs to make _any_ field that has a default (i.e., `default is not UNSET`) also
accept null, since having a default implies the field is optional.

## Approach

Two changes needed — one to allow null through validation, and one to normalize nulls to defaults so downstream
consumers get clean data.

### Phase 1: Make schema nullable for all fields with defaults

**File**: `src/sase/xprompt/loader_parsing.py` (lines 185-188, 212-215)

Change the condition from `if default is None` to `if default is not UNSET` in both the array-of-objects and
single-object branches. This means any field with a default value — whether `None`, `""`, or `"some_value"` — will
produce `{"type": [type_str, "null"]}` in the schema.

### Phase 2: Normalize null values to defaults before validation

**File**: `src/sase/xprompt/output_validation.py`

Add a normalization step in `validate_against_schema()` (or `_convert_data_types()`) that replaces null values with
their schema defaults before jsonschema validation runs. This ensures downstream code never sees `None` for a field that
should be `""`.

This requires the schema to carry default values. Currently `_parse_shortform_output_spec()` discards the default after
deciding nullability. We should emit `"default": <value>` in the property schema so the validation layer can use it.

### Phase 3: Tests

**File**: `tests/test_output_validation.py`

Add tests covering:

- Array schema with a field that has `default: ""` — null value passes validation
- Array schema with a field that has `default: None` — null value passes validation (existing behavior)
- Array schema field without default — null value still fails
- Verify null is normalized to the default value in the validated output

Also add a test for `_parse_shortform_output_spec` in an appropriate test file to verify that fields with any default
produce nullable schemas.
