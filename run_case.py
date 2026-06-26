#!/usr/bin/env python3
r"""
Single-case evaluation harness for the ABAQUS-MCP benchmark.

Runs ONE case end-to-end and scores it on the pipeline dimensions:

  D1  information-gap detection   (binary: did the agent flag a gap iff one exists)
  D2  result accuracy            (read output.odb per expected[].extract vs reference)
  D3  hallucinated API calls      (classify failed abaqus-mcp tool results)
  D4  token cost                  (cost-weighted usage from the SDK message stream)
  D5  solver cost                 (output.dat JOB TIME SUMMARY + DOF)

Flow (multi-turn, one session = one run; see notes.txt section 4):
  turn1  send preamble+problem -> agent replies with `NEED_INFO: [...]` and STOPS
         >>> D1 scored here: bool(declared) == bool(actually dropped)
  turn2  harness UNCONDITIONALLY supplies ALL dropped values, then "Proceed"
         (decoupling rule: D1 failure never starves the simulation)
  agent  builds + runs job `output` -> output.odb / output.dat in test_zone

Run:  D:\Study\Abaqus_MCP_Benchmark\.venv\Scripts\python.exe run_case.py cases/03.yaml --seed 7
"""
import os

# The spawned `claude` CLI (Node) ignores the system proxy; route it explicitly.
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7897")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7897")

import argparse
import json
import re
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import anyio

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from generate import load_case, make_instance, load_preamble, DEFAULT_PREAMBLE

PROJECT = Path(__file__).resolve().parent
TEST_ZONE = PROJECT / "test_zone"        # agent's sandboxed file-tool root (gated)
RESULTS = PROJECT / "results"

# Abaqus working directory. CONVENTION: unless explicitly overridden, the agent's
# sandbox AND the Abaqus working/output directory are BOTH test_zone. The harness
# tells the agent this path and it calls set_workdir to it (hiding the cwd is
# pointless -- the kernel can just call os.getcwd()). The grader reads
# output.odb/.dat from here. Override with ABAQUS_WORKDIR.
WORKDIR = Path(os.environ.get("ABAQUS_WORKDIR", TEST_ZONE))

# The D2 extractor runs under `abaqus python`. On Windows the launcher is a .bat
# (e.g. D:\SIMULIA\Commands\abaqus.bat), which CreateProcess cannot exec directly
# -> we route through `cmd /c` (see _abaqus_cmd). Override with ABAQUS_CMD if your
# install lives elsewhere.
def _default_abaqus():
    env = os.environ.get("ABAQUS_CMD")
    if env:
        return env
    for cand in (r"D:\SIMULIA\Commands\abaqus.bat", r"C:\SIMULIA\Commands\abaqus.bat"):
        if Path(cand).exists():
            return cand
    return "abaqus"

ABAQUS_CMD = _default_abaqus()


def _abaqus_cmd(extra):
    """Build a subprocess argv that can launch the (possibly .bat) abaqus command."""
    base = [ABAQUS_CMD, "python"] + extra
    return (["cmd", "/c"] + base) if os.name == "nt" else base


# --------------------------------------------------------------------------- #
# Abaqus kernel reset (harness-side, via the socket bridge)
# --------------------------------------------------------------------------- #
# The harness -- not the agent -- gives each run a blank slate. It talks directly
# to the live CAE socket bridge (same protocol as the abaqus-mcp server: a
# newline-delimited JSON {id, method:"execute", params:{code, timeout}} envelope).
BRIDGE_HOST = os.environ.get("ABAQUS_MCP_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("ABAQUS_MCP_PORT", "48152"))

# Close any open odbs FIRST (releases the file lock on output.odb so it can be
# deleted), THEN reset the model database to empty.
_RESET_CODE = (
    "try:\n"
    "    for _k in list(session.odbs.keys()): session.odbs[_k].close()\n"
    "except Exception as _e:\n"
    "    pass\n"
    "Mdb()\n"
)


def bridge_execute(code, timeout=60.0):
    payload = {"id": str(uuid.uuid4()), "method": "execute",
               "params": {"code": code, "timeout": timeout}}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(raw + b"\n")
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    resp = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    if not resp.get("ok", False):
        err = resp.get("error") or {}
        raise RuntimeError(err.get("message") if isinstance(err, dict) else str(err))
    return resp.get("result")


def reset_kernel():
    """
    Blank slate for the next run, harness-controlled: close odbs (frees the
    output.odb file lock so it can be deleted) + Mdb() (empty model database).

    The harness does NOT set the working directory -- the agent is told the path
    and calls set_workdir itself.
    """
    try:
        bridge_execute(_RESET_CODE)
        print("  kernel reset: odbs closed + Mdb()")
        return True
    except Exception as exc:
        print(f"  warn: kernel reset failed ({type(exc).__name__}: {exc}); "
              "stale file locks may remain")
        return False


# Files that must survive a test_zone wipe: the sandbox config and the MCP server
# wiring the agent needs. Everything else is per-run scratch and gets removed so a
# failed run can never be graded against a previous run's stale output.odb.
_KEEP = {".claude", ".mcp.json"}


def _wipe(directory, keep=frozenset()):
    """
    Remove every entry in `directory` except names in `keep`.

    MUST run AFTER prep_kernel(): if the CAE kernel still has output.odb open,
    Windows holds a lock and the delete fails.
    """
    if not directory.exists():
        return
    for child in directory.iterdir():
        if child.name in keep:
            continue
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        except OSError as exc:
            print(f"  warn: could not remove {child}: {exc}")

# Model + reasoning effort for the agent under test. "opus 4.8 middle" =
# model claude-opus-4-8 + effort medium. Override via env or --model/--effort.
MODEL = os.environ.get("BENCH_MODEL", "claude-opus-4-8")
EFFORT = os.environ.get("BENCH_EFFORT", "medium")   # low|medium|high|xhigh|max

# D4 cost weights (from BENCHMARK design): input x1, cache_create x1.25,
# cache_read x0.1, output x5.
COST_W = {"input_tokens": 1.0, "cache_creation_input_tokens": 1.25,
          "cache_read_input_tokens": 0.1, "output_tokens": 5.0}

# error_type / marker substrings that mean "the agent invoked something that does
# not exist" (D3). Real solver/modelling failures (convergence, overconstraint)
# are intentionally NOT in this list.
HALLUCINATION_MARKERS = (
    "AttributeError", "KeyError", "NameError", "TypeError",
    "possible_members", "possible_keys", "callable_signature",
    "no such tool", "unknown tool", "is not defined",
)


# --------------------------------------------------------------------------- #
# message-stream helpers
# --------------------------------------------------------------------------- #
def _text_of(content):
    """Flatten a ToolResultBlock/Message content (str | list[dict]) to text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for b in content:
        if isinstance(b, dict):
            parts.append(str(b.get("text", b)))
        else:
            parts.append(str(b))
    return " ".join(parts)


class StreamCollector:
    """Accumulates assistant text, tool events, and usage over a session."""

    def __init__(self):
        self.assistant_text = []          # per-turn list of strings
        self.tool_uses = []               # (name, input)
        self.tool_results = []            # (is_error, text)
        self.usage_msgs = []              # list of usage dicts (per assistant msg)
        self.total_cost_usd = 0.0
        self.records = []                 # ordered events for the readable transcript

    async def drain(self, client, turn):
        """Consume one response (until ResultMessage); return the turn's text."""
        turn_text = []
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                if msg.usage:
                    self.usage_msgs.append(msg.usage)
                for b in msg.content:            # preserve real text/tool ordering
                    if isinstance(b, ThinkingBlock) and b.thinking.strip():
                        self.records.append({"turn": turn, "type": "thinking",
                                             "text": b.thinking})
                    elif isinstance(b, TextBlock) and b.text.strip():
                        turn_text.append(b.text)
                        self.records.append({"turn": turn, "type": "assistant_text",
                                             "text": b.text})
                    elif isinstance(b, ToolUseBlock):
                        self.tool_uses.append((b.name, b.input))
                        self.records.append({"turn": turn, "type": "tool_use",
                                             "name": b.name, "input": b.input})
                        print(f"    -> {b.name}")
            elif isinstance(msg, UserMessage):
                content = msg.content if isinstance(msg.content, list) else []
                for b in content:
                    if isinstance(b, ToolResultBlock):
                        err = bool(getattr(b, "is_error", False))
                        txt = _text_of(b.content)
                        self.tool_results.append((err, txt))
                        self.records.append({"turn": turn, "type": "tool_result",
                                             "is_error": err, "text": txt})
            elif isinstance(msg, ResultMessage):
                if msg.total_cost_usd:
                    self.total_cost_usd = msg.total_cost_usd   # cumulative; keep last
        text = "\n".join(turn_text)
        self.assistant_text.append(text)
        return text

    # ---- derived scores ---------------------------------------------------
    def d4_weighted_tokens(self):
        total = 0.0
        for u in self.usage_msgs:
            for k, w in COST_W.items():
                total += float(u.get(k, 0) or 0) * w
        return total

    def d3(self):
        """(#hallucinated calls, #abaqus calls)."""
        abaqus_calls = sum(1 for (n, _) in self.tool_uses
                           if n.startswith("mcp__abaqus-mcp__"))
        halluc = 0
        for err, txt in self.tool_results:
            if err and any(m in txt for m in HALLUCINATION_MARKERS):
                halluc += 1
        return halluc, abaqus_calls


# --------------------------------------------------------------------------- #
# human-readable transcript
# --------------------------------------------------------------------------- #
_RESULT_CAP = 6000   # cap each tool result so a huge odb dump can't bloat the file


def write_transcript_md(records, path, inst, model, effort):
    """
    Render the session as wrapped Markdown (the .jsonl is one-line-per-event
    and unreadable; this is the human-friendly copy saved alongside the report).
    """
    lines = [f"# Transcript — case {inst['case_id']}  seed={inst['seed']}",
             "",
             f"- model: `{model}`  effort: `{effort}`",
             f"- dropped (D1 truth): `{inst['dropped'] or '-'}`",
             ""]
    cur = None
    for r in records:
        if r["turn"] != cur:
            cur = r["turn"]
            lines.append(f"\n---\n\n## Turn {cur}\n")
        if r["type"] == "thinking":
            lines.append("> **THINKING**\n>\n> "
                         + r["text"].strip().replace("\n", "\n> ") + "\n")
        elif r["type"] == "assistant_text":
            lines.append("**ASSISTANT**\n\n" + r["text"].strip() + "\n")
        elif r["type"] == "tool_use":
            inp = json.dumps(r["input"], indent=2, ensure_ascii=False)
            lines.append(f"**TOOL_USE → `{r['name']}`**\n\n```\n{inp}\n```\n")
        elif r["type"] == "tool_result":
            tag = "ERROR" if r["is_error"] else "ok"
            txt = r["text"]
            if len(txt) > _RESULT_CAP:
                txt = txt[:_RESULT_CAP] + f"\n... [truncated {len(txt) - _RESULT_CAP} chars]"
            lines.append(f"**TOOL_RESULT ({tag})**\n\n```\n{txt}\n```\n")
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# D1 parsing
# --------------------------------------------------------------------------- #
def parse_declared_missing(turn1_text):
    """Return True if the agent declared ANY gap (non-empty NEED_INFO or ASSUMED)."""
    m = re.search(r"NEED_INFO:\s*\[(.*?)\]", turn1_text, re.S)
    need = [t.strip() for t in m.group(1).split(",")] if m else []
    need = [t for t in need if t]
    assumed = re.findall(r"ASSUMED:\s*\w+\s*=", turn1_text)
    return bool(need) or bool(assumed), need


# --------------------------------------------------------------------------- #
# turn2 value injection
# --------------------------------------------------------------------------- #
def build_turn2(case, dropped):
    params = case.get("parameters", {})
    if dropped:
        items = []
        for pid in dropped:
            spec = params.get(pid, {})
            items.append(f"{pid} = {spec.get('value')} {spec.get('unit', '')}".strip())
        vals = "; ".join(items)
        head = f"Here are the values you may have asked about: {vals}."
    else:
        head = "Nothing required is missing."
    return (head + " Proceed: build the model, run the Abaqus job named `output`, "
            "and report the requested quantities with units.")


# --------------------------------------------------------------------------- #
# D2 (odb) and D5 (dat)
# --------------------------------------------------------------------------- #
def _band_score(rel_err):
    for thr, sc in ((0.02, 5), (0.05, 4), (0.10, 3), (0.20, 2)):
        if rel_err <= thr:
            return sc
    return 0


def grade_d2(case, odb_path):
    results = []
    for item in case.get("expected", []):
        ex = item.get("extract", {}) or {}
        name = item.get("name")
        if item.get("kind") != "exact" or ex.get("source") != "odb":
            results.append({"name": name, "status": "skipped (trend/non-odb)"})
            continue
        loc = ex.get("location", {}) or {}
        extra = [str(PROJECT / "grade_d2.py"), "--odb", str(odb_path)]
        for flag, key in (("--field", ex.get("field")), ("--component", ex.get("component")),
                          ("--set", loc.get("set")), ("--op", loc.get("op")),
                          ("--quantity", ex.get("quantity")), ("--mode", ex.get("mode"))):
            if key is not None:
                extra += [flag, str(key)]
        cmd = _abaqus_cmd(extra)
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            line = (out.stdout or "").strip().splitlines()
            payload = json.loads(line[-1]) if line else {"error": "no output"}
        except Exception as exc:
            payload = {"error": f"{type(exc).__name__}: {exc}"}

        if "error" in payload:
            results.append({"name": name, "status": "D2=0 (extract failed)",
                            "reason": payload["error"], "score": 0})
            continue
        sim = float(payload["value"])
        ref = float(item["value"])
        rel = abs(sim - ref) / abs(ref) if ref else float("inf")
        results.append({
            "name": name, "sim": sim, "ref": ref, "rel_err": rel,
            "tol": item.get("tol"), "pass": rel <= float(item.get("tol", 0)),
            "score": _band_score(rel), "unit": item.get("unit"),
        })
    return results


def grade_d5(dat_path):
    if not dat_path.exists():
        return {"status": "no .dat found"}
    txt = dat_path.read_text(errors="ignore")
    def find(pat):
        m = re.search(pat, txt, re.I)
        return m.group(1) if m else None
    # Abaqus reports model size as "TOTAL NUMBER OF VARIABLES IN THE MODEL <n>"
    # (= DOF + Lagrange multipliers); fall back to the older DOF wording.
    dof = find(r"TOTAL NUMBER OF VARIABLES IN THE MODEL\s+([0-9,]+)") \
        or find(r"NUMBER OF DEGREES OF FREEDOM[ .]*([0-9,]+)")
    wall = find(r"WALLCLOCK TIME \(SEC\)\s*=\s*([0-9.]+)")
    cpu = find(r"TOTAL CPU TIME \(SEC\)\s*=\s*([0-9.]+)")
    return {"dof": dof and int(dof.replace(",", "")),
            "wallclock_sec": wall and float(wall),
            "cpu_sec": cpu and float(cpu)}


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
async def run(case_path, seed, n_drop, full, model=MODEL, effort=EFFORT):
    case = load_case(case_path)
    preamble = load_preamble(DEFAULT_PREAMBLE)
    inst = make_instance(case, seed=seed, n_drop=n_drop, full=full, preamble=preamble)
    dropped = inst["dropped"]
    print(f"# case {inst['case_id']}  seed={seed}  dropped={dropped or '-'}  "
          f"model={model} effort={effort}")
    RESULTS.mkdir(exist_ok=True)
    reset_kernel()                       # close odbs (free locks) + Mdb() blank slate
    _wipe(TEST_ZONE, keep=_KEEP)         # reset the sandbox (= Abaqus workdir by default)
    if WORKDIR.resolve() != TEST_ZONE.resolve():
        WORKDIR.mkdir(parents=True, exist_ok=True)
        _wipe(WORKDIR)                    # custom workdir: wipe its stale output too
    t0 = time.time()                     # freshness baseline for output.odb/.dat

    # Tell the agent the working directory explicitly and let IT set_workdir there.
    inst["prompt"] += (
        f"\n\n## Environment\n"
        f"- Before building, call set_workdir with this path: `{WORKDIR}` , then create "
        f"your model and run the job named `output` there.\n"
        f"- Keep each kernel operation short; a single run_python call that runs too long "
        f"will block and hang the kernel.")

    options = ClaudeAgentOptions(
        cwd=str(TEST_ZONE),
        setting_sources=["project"],     # load test_zone/.claude/settings.json + gate
        permission_mode="default",
        model=model,
        effort=effort,
        # Opus 4.7+ omits thinking text by default -> request the summarized form
        # so the transcript shows the agent's reasoning, not just its actions.
        thinking={"type": "adaptive", "display": "summarized"},
        max_turns=200,                   # building a model is many tool calls
    )

    coll = StreamCollector()
    async with ClaudeSDKClient(options=options) as client:
        print("== turn1: information check ==")
        await client.query(inst["prompt"])
        turn1 = await coll.drain(client, turn=1)
        print("  agent:", turn1.replace("\n", " ")[:200])

        declared, need = parse_declared_missing(turn1)
        d1_correct = int(bool(declared) == bool(dropped))
        print(f"  D1: declared={declared} {need or ''} | actual_dropped={bool(dropped)} "
              f"-> {'OK' if d1_correct else 'WRONG'}")

        print("== turn2: supply values + proceed ==")
        await client.query(build_turn2(case, dropped))
        await coll.drain(client, turn=2)

    write_transcript_md(coll.records,
                        RESULTS / f"{inst['case_id']}_seed{seed}.transcript.md",
                        inst, model, effort)

    halluc, abaqus_calls = coll.d3()
    odb, dat = WORKDIR / "output.odb", WORKDIR / "output.dat"

    def _fresh(p):                       # produced by THIS run, not a leftover
        return p.exists() and p.stat().st_mtime >= t0 - 2

    report = {
        "case_id": inst["case_id"], "seed": seed, "dropped": dropped,
        "D1": {"score": d1_correct, "declared": declared, "need_info": need},
        "D2": grade_d2(case, odb) if _fresh(odb) else [{"status": "no fresh output.odb"}],
        "D3": {"hallucinated": halluc, "abaqus_calls": abaqus_calls},
        "D4": {"weighted_tokens": round(coll.d4_weighted_tokens(), 1),
               "total_cost_usd": coll.total_cost_usd},
        "D5": grade_d5(dat) if _fresh(dat) else {"status": "no fresh output.dat"},
        "model": model, "effort": effort,
    }

    out_path = RESULTS / f"{inst['case_id']}_seed{seed}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print("\n=== REPORT ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nsaved -> {out_path}  (+ .transcript.md)")
    return report


def _resolve_cases(arg):
    """`arg` may be a single .yaml, a directory, or the word 'all'."""
    if arg in ("all", "cases"):
        return sorted(str(p) for p in (PROJECT / "cases").glob("*.yaml"))
    p = Path(arg)
    if p.is_dir():
        return sorted(str(q) for q in p.glob("*.yaml"))
    return [arg]


async def run_many(cases, seed, n_drop, full, model, effort):
    summary = []
    for i, c in enumerate(cases, 1):
        print(f"\n########## [{i}/{len(cases)}] {c} ##########")
        try:
            rep = await run(c, seed, n_drop, full, model, effort)
            summary.append((rep["case_id"], rep["D1"]["score"], rep["D3"], rep["D4"]))
        except Exception as exc:           # one bad case must not kill the batch
            print(f"!! case {c} FAILED: {type(exc).__name__}: {exc}")
            summary.append((c, "ERR", str(exc), None))
    print("\n===== BATCH SUMMARY =====")
    for row in summary:
        print(row)


def main():
    ap = argparse.ArgumentParser(description="Run and score benchmark case(s).")
    ap.add_argument("case", help="A case YAML (cases/03.yaml), a directory, or 'all'.")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--n-drop", type=int, default=None)
    ap.add_argument("--full", action="store_true", help="Full-info baseline (no drops).")
    ap.add_argument("--model", default=MODEL, help=f"Model id (default {MODEL}).")
    ap.add_argument("--effort", default=EFFORT,
                    help="low|medium|high|xhigh|max (default %(default)s).")
    args = ap.parse_args()

    cases = _resolve_cases(args.case)
    if len(cases) == 1:
        anyio.run(run, cases[0], args.seed, args.n_drop, args.full, args.model, args.effort)
    else:
        anyio.run(run_many, cases, args.seed, args.n_drop, args.full, args.model, args.effort)


if __name__ == "__main__":
    main()
