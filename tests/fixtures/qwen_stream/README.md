# Qwen Stream Fixtures

`qwen-code-0.15.10-tools.jsonl` is a real stream-json capture from Qwen Code 0.15.10, run in a
temporary directory with this prompt:

```text
Use your shell tool to run: printf qwen_tool_fixture. Then reply with done.
```

The capture shows the current Qwen tool event shape: tool starts are nested
`assistant.message.content[]` blocks with `type: "tool_use"`, while results are nested
`user.message.content[]` blocks with `type: "tool_result"`.
