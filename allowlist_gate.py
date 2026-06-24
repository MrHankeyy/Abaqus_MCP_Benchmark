#!/usr/bin/env python3
"""Deny-by-default tool gate for the Abaqus-MCP benchmark.

Wired in via the PreToolUse hook in test_zone/.claude/settings.json. Claude Code
feeds the pending tool call as JSON on stdin; this script returns an explicit
allow/deny decision. It is the single source of truth for what the benchmark
agent may do -- it does NOT rely on settings.json glob rules, because those match
the raw argument string and are trivially bypassed with absolute paths
(`Read(D:\\...\\cases\\01.yaml)` never contains `..`, so `deny: Read(../**)` misses).

Two independent checks:
  1. Tool-name allowlist   -> only a fixed set of tools may run at all.
  2. Canonical-path containment (for file tools) -> every path argument is
     resolved with realpath() (defeating `..`, absolute paths, and symlinks)
     and must fall inside the sandbox root (test_zone). Writes additionally may
     not touch the sandbox's own .claude config dir.

This file lives OUTSIDE test_zone on purpose, and the agent is confined to
test_zone, so it can neither read nor modify its own gatekeeper.

The run_python tool (mcp__abaqus-mcp__*) executes arbitrary Python inside the
Abaqus kernel and its in-process file IO cannot be gated here -- relocating the
answer key (cases/) out of the tree is the complementary defense for that hole.
"""
import json
import os
import sys

# Tools allowed by name with no path argument to check.
NAME_ALLOW = {"ToolSearch", "Skill"}
MCP_ALLOW_PREFIX = ("mcp__abaqus-mcp__",)

# File tools, split by access kind.
READ_TOOLS = {"Read", "Glob", "Grep"}
WRITE_TOOLS = {"Write", "Edit"}


def _emit(decision: str, reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def allow(reason: str = "within sandbox") -> None:
    _emit("allow", reason)


def deny(reason: str) -> None:
    _emit("deny", reason)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        deny("unparseable hook payload (failing closed)")
        return

    tool = data.get("tool_name", "")
    tin = data.get("tool_input", {}) or {}

    # Sandbox root = the project dir (test_zone). Prefer the env var Claude Code
    # injects; fall back to the payload cwd, then to the process cwd.
    root = os.path.realpath(
        os.environ.get("CLAUDE_PROJECT_DIR")
        or data.get("cwd")
        or os.getcwd()
    )
    protected = os.path.realpath(os.path.join(root, ".claude"))

    def resolve(p: str) -> str:
        if not os.path.isabs(p):
            p = os.path.join(root, p)
        return os.path.realpath(p)

    def within(path: str, base: str) -> bool:
        return path == base or path.startswith(base + os.sep)

    # 1) Non-file tools: allow purely by name.
    if tool in NAME_ALLOW or tool.startswith(MCP_ALLOW_PREFIX):
        allow()
        return

    # 2) File tools: enforce canonical-path containment.
    if tool in READ_TOOLS or tool in WRITE_TOOLS:
        targets = []

        fp = tin.get("file_path")
        if fp:
            targets.append(resolve(fp))

        if tool in ("Glob", "Grep"):
            base = tin.get("path")
            targets.append(resolve(base) if base else root)
            # A path-glob can itself escape ("../*") or reach into .claude
            # (".claude/*") without ever touching the base path. Glob uses
            # `pattern`; Grep's regex `pattern` is content (not a path), but its
            # `glob` file filter is path-like -- vet whichever applies.
            globlike = tin.get("pattern" if tool == "Glob" else "glob", "") or ""
            parts = globlike.replace("\\", "/").split("/")
            if os.path.isabs(globlike) or ".." in parts:
                deny(f"pattern '{globlike}' may escape the sandbox")
                return
            if ".claude" in parts:
                deny(f"pattern '{globlike}' targets the off-limits .claude dir")
                return

        for p in targets:
            if not within(p, root):
                deny(f"path '{p}' is outside the sandbox root '{root}'")
                return
            # .claude holds the sandbox's own config; off-limits to read AND write.
            if within(p, protected):
                deny(f"the sandbox config dir '{protected}' is off-limits")
                return

        allow()
        return

    # 3) Everything else: denied.
    deny(f"tool '{tool}' is not on the benchmark allowlist")


if __name__ == "__main__":
    main()
