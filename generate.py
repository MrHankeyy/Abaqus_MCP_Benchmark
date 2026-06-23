#!/usr/bin/env python3
"""Generate prompt instances from a templated benchmark case.

Each case YAML defines `prompt_segments` (ordered fragments, some gated by a
`requires:` parameter), a `parameters` table, and a `drop_policy`. This script
randomly drops eligible parameters to produce an information-gap instance while
recording exactly which parameters were dropped -- that record is the ground
truth for the D1 (information-gap identification) score.

Usage:
    python generate.py cases/07.yaml --seed 42
    python generate.py cases/07.yaml --seed 42 --json
    python generate.py cases/07.yaml --full      # full-info baseline, no drops

Importable:
    from generate import load_case, make_instance
    inst = make_instance(load_case("cases/07.yaml"), seed=42)
    inst["prompt"], inst["dropped"], inst["expected_missing"]
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

import yaml


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


DEFAULT_PREAMBLE = Path(__file__).with_name("instructions_en.md")


def load_case(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_preamble(path: str | Path | None) -> str | None:
    """Load the global operating-instructions text prepended to every case prompt."""
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip()


def validate_case(case: dict[str, Any]) -> list[str]:
    """Static checks so an authoring mistake fails loudly instead of randomly.

    Rule: any *eligible* (droppable) parameter must live in its own segment gated by
    `requires: <itself>`. Otherwise dropping it leaves a dangling {placeholder} in a
    segment that is still rendered.
    """
    eligible = set((case.get("drop_policy", {}) or {}).get("eligible", []))
    params = set(case.get("parameters", {}) or {})
    errs: list[str] = []
    for i, seg in enumerate(case.get("prompt_segments", [])):
        req = seg.get("requires")
        refs = set(_PLACEHOLDER.findall(str(seg["text"])))
        unknown = refs - params
        if unknown:
            errs.append(f"seg{i}: unknown placeholder(s) {sorted(unknown)}")
        for p in refs & eligible:
            if p != req:
                errs.append(
                    f"seg{i}: eligible param '{{{p}}}' must be in its own segment "
                    f"with requires:{p} (segment currently requires:{req})"
                )
    return errs


def render(case: dict[str, Any], dropped: set[str]) -> str:
    """Concatenate segments, omitting any fragment whose `requires` is dropped."""
    params = case.get("parameters", {})
    values = {pid: spec["value"] for pid, spec in params.items() if pid not in dropped}
    pieces: list[str] = []
    for seg in case["prompt_segments"]:
        req = seg.get("requires")
        if req is not None and req in dropped:
            continue
        text = re.sub(r"\s+", " ", str(seg["text"])).strip()   # normalise each fragment
        if text:
            pieces.append(text.format(**values))
    # join with a space, except when the next fragment starts with attaching punctuation
    prompt = ""
    for i, t in enumerate(pieces):
        sep = "" if (i == 0 or t[:1] in ",.;:%)") else " "
        prompt += sep + t
    prompt = re.sub(r"\s+([,.;:])", r"\1", prompt)      # no space before punctuation
    return prompt.strip()


def make_instance(case: dict[str, Any], seed: int | None = None,
                  n_drop: int | None = None, full: bool = False,
                  preamble: str | None = None) -> dict[str, Any]:
    """Produce one randomized prompt instance plus its ground-truth drop record.

    `prompt` = global operating instructions (preamble) + the case problem statement.
    `case_prompt` is the problem statement alone.
    """
    policy = case.get("drop_policy", {}) or {}
    eligible = list(policy.get("eligible", []))
    rng = random.Random(seed)

    if full or not eligible:
        dropped: list[str] = []
    else:
        if n_drop is None:
            nd = policy.get("n_drop", {}) or {}
            lo, hi = int(nd.get("min", 0)), int(nd.get("max", len(eligible)))
            k = rng.randint(lo, min(hi, len(eligible)))
        else:
            k = min(int(n_drop), len(eligible))
        dropped = sorted(rng.sample(eligible, k))
        dropped = _respect_guards(dropped, policy.get("never_drop_together", []) or [], rng)

    params = case.get("parameters", {})
    expected_missing = [
        {
            "param": pid,
            "on_drop": params.get(pid, {}).get("on_drop", "ask"),
            "critical": params.get(pid, {}).get("critical", False),
        }
        for pid in dropped
    ]
    case_prompt = render(case, set(dropped))
    if preamble:
        prompt = f"{preamble.strip()}\n\n## Problem\n\n{case_prompt}"
    else:
        prompt = case_prompt
    return {
        "case_id": case.get("id"),
        "seed": seed,
        "dropped": dropped,             # == expected_missing params; the D1 ground truth
        "expected_missing": expected_missing,
        "case_prompt": case_prompt,     # problem statement only
        "prompt": prompt,               # preamble + problem statement (what the agent receives)
    }


def _respect_guards(dropped: list[str], guards: list[list[str]], rng: random.Random) -> list[str]:
    """If a forbidden co-drop group is fully dropped, randomly keep one of them."""
    dset = set(dropped)
    for group in guards:
        g = [p for p in group if p in dset]
        if len(g) == len(group) and len(group) > 1:
            keep = rng.choice(group)
            dset.discard(keep)
    return sorted(dset)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a prompt instance from a templated case.")
    ap.add_argument("case", help="Path to a case YAML, e.g. cases/07.yaml")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed (for reproducibility).")
    ap.add_argument("--n-drop", type=int, default=None, help="Force exactly this many drops.")
    ap.add_argument("--full", action="store_true", help="Full-info baseline (drop nothing).")
    ap.add_argument("--json", action="store_true", help="Emit the full instance as JSON.")
    ap.add_argument("--preamble", default=str(DEFAULT_PREAMBLE),
                    help="Path to global operating-instructions file (default: instructions_en.md).")
    ap.add_argument("--no-preamble", action="store_true",
                    help="Emit the bare problem statement without the global instructions.")
    args = ap.parse_args()

    case = load_case(args.case)
    preamble = None if args.no_preamble else load_preamble(args.preamble)
    inst = make_instance(case, seed=args.seed, n_drop=args.n_drop, full=args.full, preamble=preamble)

    if args.json:
        print(json.dumps(inst, ensure_ascii=False, indent=2))
    else:
        print(f"# case {inst['case_id']}  seed={inst['seed']}  dropped={inst['dropped'] or '-'}")
        print(inst["prompt"])


if __name__ == "__main__":
    main()
