# ABAQUS-MCP Validation Benchmark v1

> Purpose: a **classification benchmark** for ABAQUS-MCP (an agent driving Abaqus through MCP
> tools). Each case's problem statement is fed to the agent as a prompt; the reference solution
> is used for automatic / semi-automatic scoring.
> First batch: 22 cases spanning 5 analyses × 5 geometries × 4 materials, with a 5-dimension
> scoring scheme and a randomized information-gap track.
>
> **中文版本：** [BENCHMARK_v1.md](BENCHMARK_v1.md) ·
> **The authoritative case definitions live in** [`cases/NN.yaml`](cases); this document gives
> the rationale and a reference-value overview.

---

## 1. Design principles

1. **Auditable references.** Prefer classic problems with **closed-form solutions** or
   **published NAFEMS targets**. Each case states a formula + substituted numbers, so accuracy
   is graded against ground truth, not against another simulation.
2. **Orthogonal classification.** Every case carries three tags `analysis / geometry / material`;
   together they cover each class along all three axes (covering sampling of 22, not the full
   100-cell cross product).
3. **Realistic prompts.** Problems are written in engineering language, not as "FEA steps", so
   the agent must make the modelling decisions itself (element type, mesh, BCs, solver).
4. **Difficulty gradient.** From static linear-elastic problems up to buckling, hyperelastic,
   viscoelastic and thermal-mechanical problems — spanning a range from basic to strongly
   constrained and strongly nonlinear.
5. **Information gaps generated at run time.** See §5. Each run randomly removes some key
   parameters to test whether the agent identifies the gap and asks / declares assumptions
   instead of silently fabricating.

---

## 2. Five scoring dimensions

| Dim | Meaning | Scale (suggested 0–5) | Source |
|---|---|---|---|
| **D1 Info-gap ID** | Does it identify missing info and ask / declare assumptions, instead of fabricating? | 5=all gaps identified; 3=partial or assumed-but-declared; 0=silently invented | transcript + generator's `expected_missing` |
| **D2 Accuracy** | Error of the key output(s) vs reference | ≤2%→5; ≤5%→4; ≤10%→3; ≤20%→2; >20% or wrong→0 | the produced `.odb` (per `extract`) |
| **D3 Hallucinated calls** | Calls to nonexistent MCP tools / invented params / fictional Abaqus API | 0→5; −1 each, floor 0 | transcript: failed `run_python` `error_type` |
| **D4 Token cost** | Total tokens (cost-weighted) | within-tier percentile: best 25%→5, worst 25%→1 | transcript `usage` |
| **D5 Solver cost** | Solver CPU / wallclock (and mesh-size sanity) | given D2 is met, time/DOF percentile | Abaqus `.dat` JOB TIME SUMMARY + DOF |

> D4 cost weighting: `effective = input×1 + cache_creation×1.25 + cache_read×0.1 + output×5`.
> D4/D5 are relative — compare within the same batch; set percentile thresholds after the first
> batch runs.
> Run each case over **several random seeds**; report mean ± variance to reflect agent stability.

---

## 3. Coverage matrix

Tag abbreviations: analysis `S static / M modal / B buckling / D dynamics / T thermal-mechanical`;
geometry `Tr truss / Pl plane / Ax axisymmetric / Sh plate-shell / 3D solid`; material
`LE linear-elastic / HE hyperelastic / EP elastoplastic / VE viscoelastic`.

**Coverage check (counted from cases/ tags)**
- Analysis: S×10, M×3, B×3, D×3, T×3 ✔ (all 5 covered)
- Geometry: Tr×1, Pl×3, Ax×4, Sh×4, 3D×10 ✔ (all 5 covered; #11/#14/#17/#18 also use 1-D
  line/beam elements)
- Material: LE×15, HE×2, EP×3, VE×2 ✔ (all 4 covered)

---

## 4. Case overview

> Each case's full definition (prompt template, `extract` rules, randomly-droppable parameters),
> together with its key outputs and reference values, lives in the corresponding
> [`cases/NN.yaml`](cases). Default material: steel E=200 GPa, ν=0.3, ρ=7850 kg/m³, α=12e-6 /°C.

| # | Name | A/G/M | Source |
|---|---|---|---|
| 01 | Two-bar planar truss | S/Tr/LE | determinate truss |
| 02 | NAFEMS LE1 elliptic membrane | S/Pl/LE | NAFEMS LE1 |
| 03 | Thick cylinder, internal pressure (Lamé) | S/Ax/LE | Lamé |
| 04 | SS square plate, uniform pressure | S/Sh/LE | Timoshenko |
| 05 | NAFEMS LE10 thick plate | S/3D/LE | NAFEMS LE10 |
| 06 | Rubber block uniaxial tension | S/3D/HE | Neo-Hookean |
| 07 | O-ring seal compression | S/Ax/HE | seal benchmark (to pin) |
| 08 | Plate with hole, elastoplastic | S/Pl/EP | Peterson + limit analysis |
| 09 | Thick cylinder, elastoplastic | S/Ax/EP | Hill |
| 10 | Viscoelastic bar relaxation | S/3D/VE | Prony |
| 11 | Cantilever beam frequencies | M/3D/LE | Euler-Bernoulli |
| 12 | SS square plate, modal | M/Sh/LE | thin-plate vibration |
| 13 | SS solid square plate, modal (FV52) | M/3D/LE | NAFEMS FV52 / thin-plate baseline |
| 14 | Euler column buckling | B/3D/LE | Euler |
| 15 | Axially compressed plate buckling | B/Sh/LE | Timoshenko (k=4) |
| 16 | Cylindrical shell buckling | B/Sh/LE | classical shell buckling |
| 17 | Stress wave in a bar | D/3D/LE | 1-D wave theory |
| 18 | Beam under step load, transient | D/3D/LE | SDOF step |
| 19 | Viscoelastic strip, damped decay | D/Pl/VE | viscoelastic damping (to pin) |
| 20 | Constrained bar, thermal stress | T/3D/LE | σ=−EαΔT |
| 21 | Heated thick cylinder, thermal stress | T/Ax/LE | thermoelastic cylinder |
| 22 | Constrained bar, thermal plasticity | T/3D/EP | constrained thermo-plastic |

> Trend cases (#07/#19, and some items of #08/#16/#21) have no simple closed form; they are
> graded on sign + order-of-magnitude interval / monotonicity, not on strict D2 error. Their
> intervals are flagged as provisional (`value_status: needs_literature_pinning / needs_verification`).

---

## 5. Information-gap track (D1): generated at run time

Instead of fixed "delete-a-parameter" variants, gaps are **generated per run**: each case's prompt
is built from "optional segments + parameters"; `drop_policy.eligible` lists the key parameters
that may be randomly removed. The generator (`generate.py`) drops 0–N of them each run and
**records which** — that record is the D1 ground truth (`expected_missing`).

- Each parameter carries `on_drop`: `ask` (no sensible default → the agent should ask) or
  `assume_ok` (a standard default exists, e.g. steel density → may assume and declare).
- The global instructions ([`instructions_en.md`](instructions_en.md)) require the agent to emit
  `NEED_INFO:[...]` or `ASSUMED: name=value` when info is missing, making D1 machine-checkable
  (set comparison).
- **Failure mode couples to D3:** if a missing parameter is neither asked nor declared yet is
  hard-coded inside `run_python`, that is "silent fabrication" — D1 zero for that item plus a D3
  penalty.
- Run info-gap instances **unattended and separately**: the correct behaviour is to stop and ask,
  so the agent should terminate the case after emitting `NEED_INFO` rather than assuming and
  continuing (otherwise D1 cannot be measured).

---

## 6. Running and recording

1. **Generate a prompt:** `python generate.py cases/NN.yaml [--full | --seed S | --n-drop K]`;
   the global instructions (preamble) are prepended by default.
2. **Feed the agent:** use a **fresh session** per run (one session = one run, so the transcript
   and token accounting stay clean). The agent produces an `.odb` via ABAQUS-MCP.
3. **Grade:**
   - D2: read the `.odb` per `expected[].extract`, compare to `reference` within `tol`.
   - D1/D3/D4: parse the session transcript (`~/.claude/projects/.../*.jsonl`).
   - D5: read the Abaqus `.dat` JOB TIME SUMMARY + model DOF.
4. **Repeat & aggregate:** several random seeds per case; report D1–D5 mean ± variance.
5. **Regression baseline:** freeze these reference values as the gold standard for comparing
   future MCP / model upgrades.

> The grading scripts (`grade_d2.py` reads the odb and compares; `parse_transcript.py` produces
> D1/D3/D4) are the next deliverable. The case set, schema and prompt generator are complete and
> validated.

---

## 7. Sources

- NAFEMS, *The Standard NAFEMS Benchmarks* (LE1, LE10)
- NAFEMS R0015, *Selected Benchmarks for Natural Frequency Analysis* (FV series)
- Abaqus Benchmarks Manual §4.2 (LE1=92.7 MPa / LE10=−5.38 MPa)
- Timoshenko, *Theory of Plates and Shells* / *Theory of Elastic Stability* / *Theory of Elasticity* / *Theory of Thermal Stresses*
- Hill, *The Mathematical Theory of Plasticity* (elastoplastic thick cylinder)
- Boley & Weiner, *Theory of Thermal Stresses*
- Holzapfel, *Nonlinear Solid Mechanics* (hyperelastic constitutive models)
- Blevins, *Formulas for Natural Frequency and Mode Shape* (beam/plate frequencies)

> v1 to-do: ① tighten the order-of-magnitude intervals for trend cases (#07/#19, ...) with
> literature/converged references; ② verify the closed-form coefficient of #21 thermal stress;
> ③ add 1–2 viscoelastic+thermal (time–temperature superposition) and explicit large-deformation
> impact cases to balance HE/VE; ④ implement `grade_d2.py` and `parse_transcript.py`.
