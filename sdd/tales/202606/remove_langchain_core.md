---
create_time: 2026-06-15 21:31:34
status: done
prompt: sdd/prompts/202606/remove_langchain_core.md
---
# Remove `langchain-core` Dependency

## Goal

Remove SASE's direct `langchain-core` dependency by replacing the tiny subset of LangChain message functionality we use
with SASE-owned message types. Preserve current runtime behavior for `invoke_agent()` callers and the deprecated Gemini
wrapper APIs that expect message objects with a `.content` attribute.

## Current Findings

- `pyproject.toml` declares `langchain-core` as a runtime dependency and has a mypy ignore override for
  `langchain_core.*`.
- Runtime imports are limited to:
  - `src/sase/llm_provider/_invoke.py`: returns `AIMessage(content=response_content)`.
  - `src/sase/gemini_wrapper/wrapper.py`: uses `AIMessage` and `HumanMessage` for deprecated compatibility APIs.
  - `src/sase/workflows/mentor.py`: creates an `AIMessage` fallback when mentor invocation raises `LLMInvocationError`.
- Tests import `AIMessage` from `langchain_core.messages` only to build fake responses with `.content`.
- The real provider boundary already uses `sase.llm_provider.types.InvokeResult(content: str, usage: dict | None)`, so
  LangChain is not part of provider execution, tool handling, retries, metrics, or finalization.
- `src/sase/__init__.py` suppresses a Pydantic v1 warning specifically because of LangChain; that should be removed with
  the dependency.

## Proposed Design

Add a small SASE-native message module, likely `src/sase/llm_provider/messages.py`, containing:

- `MessageContent = str | list[str | dict[Any, Any]]`
- immutable `BaseMessage` with a public `content` field
- immutable `AIMessage(BaseMessage)`
- immutable `HumanMessage(BaseMessage)`

This intentionally implements only the behavior SASE currently needs:

- construction with `content=...`
- `.content` access
- `isinstance(msg, HumanMessage)` routing in the deprecated Gemini wrapper
- list content compatibility with `ensure_str_content()`

I do not plan to create a fake `langchain_core` package or compatibility import path. That would hide the dependency
removal and could mislead future code into relying on LangChain semantics SASE does not implement.

## Implementation Steps

1. Add the local message types.
   - Put the implementation under the LLM provider package because the message objects are part of the public
     `invoke_agent()` compatibility surface.
   - Export `AIMessage`, `HumanMessage`, `BaseMessage`, and `MessageContent` from `sase.llm_provider.__init__`.
   - Consider also re-exporting `AIMessage` and `HumanMessage` from `sase.gemini_wrapper.__init__` because that wrapper
     is the legacy LangChain-shaped API.

2. Replace runtime LangChain imports.
   - Change `_invoke.py` to import local `AIMessage` and keep returning `AIMessage(content=response_content)`.
   - Change `gemini_wrapper/wrapper.py` to import local `AIMessage` and `HumanMessage`.
   - Change the mentor fallback to use the local `AIMessage`.
   - Update docstrings from "LangChain AIMessage" wording to "message response" or "SASE AIMessage".

3. Keep content normalization local and explicit.
   - Update `sase.content.ensure_str_content()` docs and type hints so they describe SASE message content rather than
     LangChain's `AIMessage.content`.
   - Preserve current behavior exactly: strings pass through, list content is converted with `str(content)`.

4. Update tests.
   - Replace test imports from `langchain_core.messages` with the local SASE message module.
   - Add focused coverage for the local message types and the Gemini wrapper's `HumanMessage` routing, if existing tests
     do not already cover that path.
   - Add or update an `invoke_agent()` test to assert the returned object is the local `AIMessage` and carries the
     provider content.

5. Remove package metadata dependency.
   - Delete `"langchain-core"` from `pyproject.toml`.
   - Delete the `langchain_core.*` mypy override.
   - Remove the LangChain/Pydantic warning suppression from `src/sase/__init__.py`.
   - Regenerate `uv.lock` with `uv lock` so `langchain-core` and no-longer-needed transitive dependencies drop from the
     lockfile.

6. Sweep for accidental remaining references.
   - Run `rg -n "langchain|AIMessage|HumanMessage" src tests pyproject.toml uv.lock`.
   - Expected result: no `langchain` references in source/tests/package metadata/lockfile; `AIMessage` and
     `HumanMessage` references should point to SASE's local message module.
   - Historical SDD/research references can stay unless they are misleading current docs.

## Validation Plan

Run the repo-required setup/check flow after code changes:

1. `just install`
2. Focused tests first:
   - `.venv/bin/python -m pytest tests/test_llm_provider_invoke.py tests/test_gemini_wrapper.py tests/test_content.py`
   - `.venv/bin/python -m pytest tests/test_workflow_executor.py tests/test_fix_just_workflow.py`
   - Include any new message-specific test file.
3. Dependency/import sweep:
   - `rg -n "from langchain_core|import langchain_core|langchain-core|langchain_core\\." src tests pyproject.toml uv.lock`
4. Full repo gate:
   - `just check`

## Risks and Mitigations

- External callers may have passed real LangChain `HumanMessage` objects to the deprecated Gemini wrapper. Since this
  repo does not test that as a supported contract, the primary compatibility target is SASE's own local message classes.
  If needed, the wrapper can tolerate duck-typed objects with `.content`, but it should not import LangChain.
- `uv lock` may remove additional transitive packages that were present only for LangChain. That is expected, but I will
  review the lockfile diff for unrelated churn.
- If mypy or pyvision treats the new message module as unused, I will keep exports and tests explicit rather than adding
  broad ignores.

## Expected Outcome

SASE no longer depends on `langchain-core`; the public `invoke_agent()` compatibility surface still returns an object
with `.content`; deprecated Gemini wrapper behavior remains covered; and the Python 3.14 Pydantic v1 warning workaround
is no longer necessary.
