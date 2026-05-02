# OpenAI Deep Research Integration for SASE

Date: 2026-04-25

## Question

How should SASE integrate GPT-5.5 and OpenAI Deep Research so a user can ask research questions from SASE, get a durable
source-backed report, and then hand the result to normal SASE agents?

This note reviews the prior agent transcripts, current SASE architecture, OpenAI API docs, and related prior art. It
ends with a recommended implementation path.

## Executive Summary

Do not integrate Deep Research as a normal `LLMProvider` model swap.

The best first implementation is a built-in `#research` xprompt workflow backed by a small Python runner that calls the
OpenAI Responses API, uses background mode, writes structured artifacts, and returns a concise pointer back into the
agent conversation.

Use three modes:

| Mode | Model | Use case |
| --- | --- | --- |
| `fast` | `gpt-5.5` with `web_search_preview` | Current-info research, quick comparisons, short sourced answers |
| `pro` | `gpt-5.5-pro` with background mode and tools | Expensive hard synthesis where GPT-5.5 Pro's stronger reasoning matters |
| `deep` | `o3-deep-research` or `o4-mini-deep-research` | True Deep Research reports over web, file search, and MCP sources |

The important correction to one prior transcript is that Deep Research is API-accessible now, but it is not the ChatGPT
Pro quota exposed through Codex CLI. It is Responses API usage and should be treated as separately billed API work.

## Prior Transcript Review

The first referenced chat, `sase-ace_run-260424_200136.md`, says Deep Research is a ChatGPT app feature and not exposed
through Codex CLI. That was directionally right for Codex CLI, but incomplete for the API surface.

The second referenced chat, `sase-ace_run-260424_200155.md`, corrects the API side: Deep Research can be integrated via
Responses API using dedicated models and a data source such as web search, file search, or MCP.

The two follow-up research transcripts propose similar implementation options:

- A normal LLM provider is tempting because SASE already routes `%model:provider/model`.
- A workflow is a better fit because research is a pipeline: clarify, build a brief, run long research, store artifacts,
  optionally synthesize.
- A background job subsystem is the stronger long-term shape, but it is larger than an MVP.

This note agrees with that direction and adds a more specific staged design.

## Current SASE Architecture

### LLM provider shape

SASE's `LLMProvider` interface is deliberately simple: providers receive an already-preprocessed prompt and return one
`InvokeResult` containing response text and optional usage data (`src/sase/llm_provider/base.py:8`). The shared
orchestrator preprocesses prompts, saves prompts to artifacts, invokes the provider, records telemetry, postprocesses the
response, and writes chat history (`src/sase/llm_provider/_invoke.py:61`).

The Codex provider is a CLI subprocess wrapper. Its large tier maps to `gpt-5.5`, and its known model list includes
OpenAI reasoning/coding names, but not the deep research models (`src/sase/llm_provider/codex.py:14`,
`src/sase/llm_provider/codex.py:58`). The provider shells out to `codex exec --model ... --json` (`src/sase/llm_provider/codex.py:129`).

Implication: a Deep Research API integration would be the first provider that is not a CLI wrapper and the first provider
whose natural output is not just a chat response. It needs job state, tool-call metadata, source annotations, and
polling.

### Workflow shape

Xprompt workflows already support the pieces a research pipeline needs: `agent`, `bash`, `python`, `parallel`,
`prompt_part`, conditionals, loops, `finally`, typed outputs, hidden infrastructure steps, and artifacts
(`src/sase/xprompt/workflow_models.py:52`). Python workflow steps run under the same interpreter, stream stderr for
progress, parse stdout into structured outputs, and can save stdout artifacts (`src/sase/xprompt/workflow_executor_steps_script.py:255`).

Standalone workflows are already launched in a background thread for home mode, or as a subprocess with a workspace and
artifact directory when running from project context (`src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py:118`,
`src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py:193`).

Implication: SASE has enough workflow and artifact machinery for a useful first version without inventing a whole new
provider contract.

### Existing research on long-running tasks

`sdd/research/202603/send_cmds_to_axe.md` recommends an internal task queue for long-running TUI work because it provides structured
status, output capture, cancellation, and better UI integration than arbitrary shell slots. That applies directly to
Deep Research, but it is a later phase. The first useful version can piggyback on workflow subprocesses and
`workflow_state.json`; the durable task queue can come after users prove the feature is worth making non-blocking and
resumable.

`sdd/research/202603/xprompt_workflow_best_practices.md` recommends keeping YAML orchestration thin and moving long Python logic
into modules. That is exactly the right shape here: the workflow should call `sase.research.openai`, not inline the
Responses API polling loop.

## OpenAI API Findings

OpenAI currently exposes two distinct surfaces relevant to this feature.

First, GPT-5.5 and GPT-5.5 Pro are general frontier models available through the Responses API. GPT-5.5 supports
Responses tools including web search, file search, code interpreter, hosted shell, MCP, tool search, and skills. The
model page lists a 1,050,000 token context window and `reasoning.effort` values including `xhigh`. GPT-5.5 Pro is
Responses API capable, uses more compute, may take several minutes, and OpenAI recommends background mode to avoid
timeouts. Sources: OpenAI GPT-5.5 model docs and GPT-5.5 Pro model docs:

- https://developers.openai.com/api/docs/models/gpt-5.5
- https://developers.openai.com/api/docs/models/gpt-5.5-pro

Second, OpenAI's specialized Deep Research models are `o3-deep-research` and `o4-mini-deep-research`. The Deep Research
guide says they are for complex analysis, can synthesize many sources, and are used through Responses API with at least
one data source: web search, remote MCP, or file search/vector stores. Code interpreter can be added for analysis.
Source:

- https://developers.openai.com/api/docs/guides/deep-research

OpenAI's background-mode guide says background responses are polled through the Responses GET endpoint until they leave
`queued` or `in_progress`. It also notes that background mode stores response data for roughly 10 minutes and is not
Zero Data Retention compatible. Source:

- https://developers.openai.com/api/docs/guides/background

Web search is the direct path for current public sources and citations. File search is the hosted path for OpenAI vector
stores. Remote MCP is the path for private/internal systems; for Deep Research, an MCP server must expose `search` and
`fetch`, and OpenAI calls out prompt-injection and data-exfiltration risks when combining private data with web search.
Sources:

- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/tools-file-search
- https://developers.openai.com/api/docs/guides/tools-connectors-mcp

The OpenAI cookbook shows two important product-design details:

- The raw Deep Research API is programmatic and does not automatically give you ChatGPT's full product wrapper.
- A stronger research workflow adds clarification and instruction-building before invoking the research model.
- The response contains final text, annotations/citations, reasoning summaries, web search calls, and code execution
  steps that applications can inspect or store.

Sources:

- https://developers.openai.com/cookbook/examples/deep_research_api/introduction_to_deep_research_api
- https://developers.openai.com/cookbook/examples/deep_research_api/introduction_to_deep_research_api_agents

ChatGPT Pro does include extended access to Deep Research in ChatGPT, but OpenAI Help says API usage is separate and
billed independently. SASE should not frame this as "using your ChatGPT Pro Deep Research quota" unless it is literally
driving ChatGPT, which it should not do. Source:

- https://help.openai.com/en/articles/9793128-what-is-chatgpt-pro

## Prior Art

### OpenAI Agents SDK Deep Research pipeline

OpenAI's Agents SDK cookbook uses a multi-agent pipeline with a clarifier, instruction builder, and research agent. The
notable design lesson is not "SASE must adopt Agents SDK"; it is that prompt enrichment is a first-class stage before
expensive research. This maps cleanly to SASE's xprompt workflows:

1. A cheap/normal SASE agent clarifies or rewrites the question into a research brief.
2. A Python step calls the Deep Research API.
3. A final SASE agent optionally synthesizes the external report with local repo context.

### LangGraph durable execution

LangGraph's durable-execution docs emphasize checkpointers, deterministic replay, idempotent side effects, and wrapping
external calls so they do not repeat after resume. This is relevant because Deep Research calls are expensive and
long-running. SASE's MVP can store `response_id` immediately after creation, then poll by ID; a later durable task queue
should persist every status transition and avoid launching duplicate API jobs on restart.

Source: https://docs.langchain.com/oss/python/langgraph/durable-execution

### Pydantic AI / Restate durable agents

Pydantic AI documents durable agents with Temporal, DBOS, Prefect, and Restate; Restate's model persists LLM calls and
tool executions so recovery does not duplicate side effects. Again, SASE does not need this dependency, but the lesson
is the same: a research integration should treat `responses.create()` as an idempotent job creation boundary and store
the result before doing anything else.

Sources:

- https://pydantic.dev/docs/ai/integrations/durable_execution/overview/
- https://pydantic.dev/docs/ai/integrations/durable_execution/restate/

## Solution Options

### Option A: Do nothing special; use Codex/GPT-5.5

Use today's SASE path with `%model:codex/gpt-5.5` for research prompts.

Pros:

- Zero implementation.
- Keeps all current SASE chat history, artifacts, and repo context.
- Good for codebase-local research, design analysis, and ordinary reasoning.

Cons:

- Not the Deep Research API.
- Depends on Codex CLI behavior and account capabilities.
- Does not expose source annotations, web-search traces, or a controlled data-source configuration.
- Long research still looks like a normal agent run.

Verdict: keep this as the baseline, but it does not solve the request.

### Option B: Add an `openai` LLM provider

Add a new `sase_llm` provider, e.g. `%model:openai/gpt-5.5`, `%model:openai/gpt-5.5-pro`,
`%model:openai/o3-deep-research`.

Pros:

- Fits SASE's visible model-routing syntax.
- Useful for simple OpenAI Responses calls that are not available through Codex CLI.
- Could reuse `invoke_agent()` logging and chat history.

Cons:

- The provider contract is too narrow for research artifacts.
- Deep Research needs data-source selection, background create/poll, response IDs, citations, tool-call logs, and
  possibly cancellation.
- It blurs the meaning of `%model:` by making a long-running research pipeline look like a model choice.
- It creates naming confusion with the existing `codex` provider, which already owns `gpt-5.5` for CLI agent work.

Verdict: useful later for normal Responses API calls, but not the right first home for Deep Research.

### Option C: Built-in `#research` workflow plus shared OpenAI runner

Add a workflow like `src/sase/xprompts/research.yml` and a module like `src/sase/research/openai.py`.

Shape:

1. `brief` step: a normal SASE agent rewrites the user question into a specific research brief. It should ask
   clarifying questions only when necessary; otherwise it records assumptions.
2. `research` step: a Python step calls the shared runner, creates a Responses API job with `background=True`, stores
   `response_id`, polls, and writes artifacts.
3. `summarize` step: optional normal SASE agent summarizes the report and tells the user where it was saved.

Artifacts:

- `brief.md`
- `report.md`
- `response.json`
- `sources.json`
- `tool_calls.jsonl`
- `usage.json`
- `status.json`

Pros:

- Matches SASE's existing orchestration primitive.
- Keeps YAML orchestration thin and testable.
- Lets users write `#research:: question` rather than memorizing API settings.
- Can offer `mode=fast|pro|deep|deep-mini`, `sources=web|files|mcp`, `output=report|brief|json`.
- Works in home mode and project mode using existing workflow artifacts.

Cons:

- The first version still blocks the workflow runner while polling.
- Requires an API key and an OpenAI SDK dependency or direct HTTP client.
- Needs careful policy around private context plus web search.

Verdict: best MVP.

### Option D: Dedicated `sase research` CLI and job registry

Add commands such as:

```text
sase research start --mode deep --question ...
sase research status <job_id>
sase research attach <job_id>
sase research cancel <job_id>
```

The command writes to `~/.sase/projects/<project>/artifacts/sdd/research/<timestamp>/` and can be invoked by `#research`.

Pros:

- Gives a clean non-TUI and automation surface.
- Enables explicit status/cancel/resume.
- Makes duplicate-job prevention easier.
- Can integrate later with AXE/TUI background status.

Cons:

- More product surface to design.
- Still needs the same OpenAI runner.
- More work before the first useful user experience.

Verdict: good phase two if `#research` gets real usage.

### Option E: SASE Deep Research MCP server

Expose SASE memory, chats, research docs, bead state, and repo summaries through a remote MCP server with Deep Research
compatible `search` and `fetch` tools.

Pros:

- Best long-term way for Deep Research to inspect private SASE knowledge without dumping giant context into the prompt.
- Lets OpenAI's research model decide what internal material to retrieve.
- Aligns with OpenAI's Deep Research requirements for internal sources.

Cons:

- Needs authentication, network exposure, permission boundaries, audit logs, and prompt-injection defenses.
- OpenAI explicitly warns about exfiltration risk when private MCP data and web search are mixed.
- SASE's existing local memory and file refs are already useful enough for an MVP.

Verdict: valuable, but only after the basic runner exists. Start with explicit local context capture, then add MCP.

## Recommended Solution

Build Option C first, with a design that can grow into Options D and E.

### Public UX

Add a built-in workflow:

```text
#research:: What is the best way to integrate OpenAI Deep Research into SASE?
#research(mode=fast):: compare current OpenAI web search vs Deep Research for SASE
#research(mode=deep, sources=web):: produce a prior-art report on durable AI research agents
```

Defaults:

- `mode=fast`: `gpt-5.5` with `web_search_preview`.
- `mode=deep`: `o4-mini-deep-research` initially, because it is faster and cheaper.
- `mode=deep-pro`: `o3-deep-research`.
- `mode=pro`: `gpt-5.5-pro` with background mode, for hard synthesis that is not necessarily Deep Research.

Use "research" as the user-facing noun, not "deep research" for every mode. Reserve "deep" for the specialized
Responses API models.

### Runner API

Create `src/sase/research/openai.py` with a small interface:

```python
@dataclass
class ResearchRequest:
    question: str
    brief: str | None
    mode: Literal["fast", "pro", "deep", "deep-mini"]
    tools: list[ResearchToolConfig]
    artifacts_dir: Path
    poll_interval_seconds: int = 15

@dataclass
class ResearchResult:
    response_id: str
    status: str
    report_path: Path
    response_path: Path
    sources_path: Path | None
    tool_calls_path: Path | None
    usage: dict[str, Any] | None
```

Implementation details:

- Require `OPENAI_API_KEY`.
- Call `responses.create(..., background=True, tools=[...])`.
- Immediately write `status.json` with `response_id`, model, mode, timestamps, and request hash.
- Poll `responses.retrieve(response_id)` until terminal status.
- Persist the raw response before parsing.
- Extract final text into `report.md`.
- Extract citation annotations into `sources.json`.
- Extract search/code/MCP steps into `tool_calls.jsonl`.
- Write incremental status to stderr so workflow logs show progress.

Do not inline this in YAML.

### Workflow Design

Create `src/sase/xprompts/research.yml`:

1. `prepare_brief` agent step:
   - Inputs: `question`, `mode`, optional `audience`, optional `constraints`.
   - Output: `{ brief: text, needs_clarification: bool, assumptions: text }`.
   - If clarification is needed in non-interactive mode, proceed with explicit assumptions rather than blocking.
2. `run_research` Python step:
   - Calls `sase.research.openai.run_research(...)`.
   - Output: `{ report_path: path, response_id: word, mode: word, source_count: int }`.
3. `return_summary` agent or prompt step:
   - Returns a concise summary and the report path.

For the first implementation, skip automatic local repo upload/vector-store creation. Let users pass local files through
the normal SASE prompt/reference system into the brief. Add file search/vector stores after the basic API integration is
stable.

### Safety Defaults

- Never mix private SASE memory/chats with web search unless the workflow explicitly says it will.
- Default `sources=web` should include only the user's question and the generated brief.
- For project-local/private context, use a two-phase pattern:
  1. public web research without private context;
  2. local synthesis by a normal SASE/Codex agent using the public report and local files.
- Add `sources=mcp` later only for trusted, explicitly configured MCP servers.
- Store raw responses and tool calls for auditability.

### Why This Beats a Provider

Deep Research is not a model tier. It is a research product surface with job lifecycle and evidence artifacts. The SASE
provider abstraction is optimized for "send prompt, get response"; the workflow abstraction is optimized for "run a
pipeline with typed step outputs and artifacts." The workflow path preserves SASE's current architecture and avoids
mixing orchestration concerns into `LLMProvider.invoke()`.

## Implementation Plan

1. Add `openai` SDK dependency and `src/sase/research/openai.py`.
2. Add unit tests for:
   - mode-to-model/tool mapping;
   - status persistence after `responses.create`;
   - parsing report text, citations, tool calls, and usage from mocked response objects;
   - polling terminal success/failure/cancel states.
3. Add `src/sase/xprompts/research.yml`.
4. Add workflow tests using a fake runner or monkeypatched module.
5. Add docs/examples for `#research`.
6. Phase two: add `sase research start/status/cancel/attach`.
7. Phase three: add a trusted SASE MCP server or file-search upload path for internal corpora.

## Open Questions

- Should `mode=deep` default to `o4-mini-deep-research` for cost/latency, or should the name imply the stronger
  `o3-deep-research`?
- Should research reports be written only to workflow artifacts, or also copied into repo-local `sdd/research/` when the
  user asks for a project research note?
- Should `#research` be available inside normal agent prompts as an embedded workflow, or only as a standalone workflow
  launched from the prompt bar?
- How should SASE expose cancellation for a background Responses job before a dedicated research CLI exists?

## Bottom Line

Implement `#research` as a workflow-backed research pipeline, not a provider. Use GPT-5.5 for fast/tool-using research
and synthesis, use `o3-deep-research` or `o4-mini-deep-research` for true Deep Research, and store the full report plus
source/tool artifacts in SASE's artifact system. Add a separate durable `sase research` job surface only after the MVP
proves useful.
