#!/usr/bin/env python3
"""Minimal smoke test for the benchmark agent + sandbox.

Verifies three things end-to-end, without any scoring logic:
  1. claude-agent-sdk can start a session (i.e. it found and spawned the CLI);
  2. the sandbox is active -- a Read of ../cases/01.yaml is DENIED by the gate;
  3. normal in-sandbox work (Write + Read inside test_zone) is ALLOWED.

KEY: setting_sources=["project"] is required, otherwise the SDK loads NO
filesystem settings and our test_zone/.claude/settings.json + PreToolUse gate
never activate.

Run:  D:\\Study\\Abaqus_MCP_Benchmark\\.venv\\Scripts\\python.exe smoke_test.py
"""
import os

# Region proxy: the spawned `claude` CLI (Node) does not read the system proxy,
# so route it explicitly. The Python process env is inherited by the CLI.
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7897")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7897")

import anyio

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

TEST_ZONE = r"D:\Study\Abaqus_MCP_Benchmark\test_zone"

PROMPT = """You are running inside a sandbox smoke test. Perform EXACTLY these
three steps in order, each with the stated tool, then report success/denied for
each:

1. Write tool: create ./smoke_ok.txt containing the text "hello".
2. Read tool: read ./smoke_ok.txt back.
3. Read tool: read ../cases/01.yaml  (this is EXPECTED to be blocked -- attempt
   it anyway so we can confirm the sandbox denies it).

Do not skip step 3. After all three, summarize what happened."""


def _short(x, n=300):
    return str(x).replace("\n", " ")[:n]


async def main():
    options = ClaudeAgentOptions(
        cwd=TEST_ZONE,
        setting_sources=["project"],   # load test_zone/.claude/settings.json + gate hook
        permission_mode="default",
        max_turns=12,
    )

    async for msg in query(prompt=PROMPT, options=options):
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock):
                    print("ASSISTANT:", _short(b.text, 600))
                elif isinstance(b, ToolUseBlock):
                    print(f"  -> TOOL_USE  {b.name}  {_short(b.input, 200)}")
        elif isinstance(msg, UserMessage):
            content = msg.content if isinstance(msg.content, list) else []
            for b in content:
                if isinstance(b, ToolResultBlock):
                    err = getattr(b, "is_error", None)
                    print(f"  <- TOOL_RESULT (is_error={err})  {_short(b.content, 250)}")
        elif isinstance(msg, ResultMessage):
            print("\n=== RESULT ===")
            print(_short(getattr(msg, "result", ""), 1000))
            print(_short(getattr(msg, "usage", ""), 1000))
            print(_short(getattr(msg, "total_cost_usd", ""), 1000))


if __name__ == "__main__":
    anyio.run(main)
