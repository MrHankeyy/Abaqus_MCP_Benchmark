#!/usr/bin/env python3
"""Deny-by-default tool gate for the Abaqus-MCP benchmark.

Wired in via the PreToolUse hook in test_zone/.claude/settings.json.
Claude Code feeds the pending tool call as JSON on stdin; this script decides
whether it passes. Anything NOT on the allowlist below is denied automatically
(no prompt, no human needed) -- that is what makes this a true whitelist.

This file lives OUTSIDE test_zone on purpose: the benchmark agent is confined
to test_zone (and ../** is denied), so it can neither read nor modify its own
gatekeeper.
"""
import json
import sys

# Exact tool names that are allowed.
ALLOW = {
    "Read",
    "Edit",
    "Write",
    "Glob",
    "Grep",
    # ToolSearch only LOADS deferred-tool schemas; it does not grant the ability
    # to call them. Without it, the deferred mcp__abaqus-mcp__* tools can never
    # have their schemas loaded and are therefore uncallable. Actual invocation
    # of any loaded tool still passes back through this gate.
    "ToolSearch",
    # Skill lets the agent consult the Abaqus scripting skills for guidance.
    "Skill",
}

# Name prefixes that are allowed (covers every tool under a given MCP server).
ALLOW_PREFIX = (
    "mcp__abaqus-mcp__",
)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # If we cannot parse the payload, fail closed (deny).
        data = {}

    tool = data.get("tool_name", "")
    allowed = tool in ALLOW or tool.startswith(ALLOW_PREFIX)

    if allowed:
        # Exit 0 with no output -> let normal permission rules decide / proceed.
        sys.exit(0)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Tool '{tool}' is not on the benchmark allowlist."
            ),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
