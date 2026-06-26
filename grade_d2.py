#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""D2 ground-truth extractor -- runs under ABAQUS PYTHON, not the .venv.

    abaqus python grade_d2.py --odb output.odb --field S --component S33 \
        --set INNER_WALL --op max_abs

Reads ONE scalar from an .odb exactly where the case's `expected[].extract` says,
bypassing whatever the agent reported in prose. Prints a single JSON line to
stdout:  {"value": <float>}  on success, or  {"error": "<reason>"}  on failure
(missing set, missing field, etc.). A failure here => the orchestrator scores D2=0
for that quantity, which is the intended "cannot identify -> zero" behaviour.

Kept deliberately small; extend as more `extract` shapes are exercised. Known
not-yet-handled: coordsys=cylindrical transforms (hoop/radial in global frame).
This is Python 2/3 compatible because Abaqus ships its own interpreter.
"""
import argparse
import json
import sys

try:
    from odbAccess import openOdb
    from abaqusConstants import NODAL, ELEMENT_NODAL, INTEGRATION_POINT
except Exception as exc:                       # not under abaqus python
    print(json.dumps({"error": "odbAccess unavailable: %s" % exc}))
    sys.exit(0)


def _reduce(values, op):
    """Collapse a list of scalars per the extract op."""
    if not values:
        return None
    if op == "max":
        return max(values)
    if op == "min":
        return min(values)
    if op == "mean":
        return sum(values) / float(len(values))
    if op in ("max_abs", "node"):              # 'node' (single node) -> just take extreme
        return max(values, key=abs)
    raise ValueError("unknown op '%s'" % op)


def _region(odb, set_name):
    """Find a named set: assembly-level first, then any instance-level set.

    Agents legitimately create sets on a part/instance (e.g. INNER_WALL on
    CYLINDER-1) rather than on the root assembly, so we must search both or we
    would wrongly score a correctly-built model as zero.
    """
    ra = odb.rootAssembly
    if set_name in ra.nodeSets.keys():
        return ra.nodeSets[set_name], "node"
    if set_name in ra.elementSets.keys():
        return ra.elementSets[set_name], "element"
    for inst in ra.instances.values():
        if set_name in inst.nodeSets.keys():
            return inst.nodeSets[set_name], "node"
        if set_name in inst.elementSets.keys():
            return inst.elementSets[set_name], "element"
    return None, None


def _last_step_frame(odb, step_name=None):
    keys = list(odb.steps.keys())
    sk = step_name if (step_name and step_name in odb.steps) else keys[-1]
    return odb.steps[sk], odb.steps[sk].frames[-1]


def extract(args):
    odb = openOdb(args.odb, readOnly=True)
    try:
        # --- eigenfrequency: value lives on the frame, not a field --------
        if args.quantity == "eigenfrequency":
            step, _ = _last_step_frame(odb, args.step)
            fr = step.frames[int(args.mode)]   # mode 1 -> frames[1] (frames[0] is base state)
            return float(fr.frequency)

        # --- field component at a named set ------------------------------
        region, kind = _region(odb, args.set)
        if region is None:
            return {"error": "set '%s' not found in odb" % args.set}

        step, frame = _last_step_frame(odb, args.step)
        if args.field not in frame.fieldOutputs.keys():
            return {"error": "field '%s' not in last frame" % args.field}
        fo = frame.fieldOutputs[args.field]

        # nodal fields (U, RF, NT) read at NODAL; stress/strain need ELEMENT_NODAL
        pos = NODAL if args.field in ("U", "RF", "NT", "UR", "CF") else ELEMENT_NODAL
        try:
            fo = fo.getSubset(region=region, position=pos)
        except Exception:
            fo = fo.getSubset(region=region)   # fall back to native position

        comp = args.component
        labels = list(fo.componentLabels) if fo.componentLabels else []
        vals = []
        for v in fo.values:
            if comp in ("Mises", "mises"):
                vals.append(float(v.mises))
            elif comp in ("Magnitude", "magnitude"):
                vals.append(float(v.magnitude))
            elif comp in labels:
                vals.append(float(v.data[labels.index(comp)]))
            elif comp is None and v.data is not None:
                vals.append(float(v.data))
            else:
                return {"error": "component '%s' not in %s" % (comp, labels)}

        red = _reduce(vals, args.op)
        if red is None:
            return {"error": "no values extracted for set '%s'" % args.set}
        return float(red)
    finally:
        odb.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--odb", required=True)
    ap.add_argument("--field")                 # S | U | RF | NT | ...
    ap.add_argument("--component")             # S33 | U1 | Mises | Magnitude | ...
    ap.add_argument("--set")                   # named set, e.g. INNER_WALL
    ap.add_argument("--op", default="max_abs") # max | min | max_abs | mean | node
    ap.add_argument("--step", default=None)
    ap.add_argument("--quantity", default=None)  # eigenfrequency (with --mode)
    ap.add_argument("--mode", default=1)
    args = ap.parse_args()

    try:
        out = extract(args)
    except Exception as exc:
        out = {"error": "%s: %s" % (type(exc).__name__, exc)}

    print(json.dumps(out if isinstance(out, dict) else {"value": out}))


if __name__ == "__main__":
    main()
