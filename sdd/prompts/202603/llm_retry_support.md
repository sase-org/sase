---
plan: sdd/epics/202603/llm_retry_support.md
---
Can you help me add retry support for specific LLM providers, that the user should be able to configure?

#phase

### Rety Behavior

- If an LLM provider, say gemini, is configured to retry N times and then fallback to model X, say
  gemini-3-flash-preview, then if an agent of that provider fail, which we determine by looking at the reply / error
  message output and matching against user-configured strings, then we will retry N times before trying the fallback
  model.
- Before each retry, we should wait for a user-configured amount of time before trying again. Each retry attempt should
  have its own configurable wait time.
- We will only try the fallback model once, and if that fails, we will not retry anymore.

### Configuration

- The default configuration should default to not retrying at all for any provider (the user needs to configure this).
- Do your best to figure out what the YAML configuration needs to look like based on our requirements.

### The "Agents" Tab of the `sase ace` TUI

- Whenever an agent retries or falls back to a different model, we should trigger a sase notification to let the user
  know.
- We should also mark that agent to indicate how many retries it has done, and if it has fallen back to a different
  model. I want you to lead the design on this one. Just make sure it looks beautiful!
- Also, we need to ensure that the agent is NOT marked as "DONE" when waiting for the next retry. We should show the
  agent as "RETRYING" with a countdown timer until the next retry attempt. Again, I want you to lead the design for the
  UI here.
