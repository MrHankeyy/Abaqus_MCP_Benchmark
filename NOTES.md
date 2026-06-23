# Open notes & questions (for later discussion)

Running log of design concerns and observed agent behaviours. Not yet resolved — captured here
so we can revisit and turn into concrete changes.

---

## N1 — Closed-form cases may be "memorized", not solved

**Observation.** Several first-batch cases (e.g. #03 axisymmetric thick-cylinder Lamé stress,
#20 constrained-bar thermal stress) have textbook closed-form answers the model has likely seen
many times in training. The model may reproduce the expected number by *recall / analytical
derivation* rather than by actually building and solving the FE model. If so, a high D2 score
does not prove the ABAQUS-MCP tool-use path works — it only proves the model knows the formula.

**Why it matters.** The benchmark's purpose is to test the *agent + MCP + Abaqus* pipeline, not
the model's memory of standard results. Over-easy, closed-form cases inflate D2 and weaken the
signal.

**Candidate directions (to discuss).**
1. **Randomize the numeric inputs per run.** We already template `parameters`; extend them with
   value *ranges*, sample within range each seed, and have the grader recompute the reference
   from the stored formula. The agent then faces a number it cannot recall and must compute via
   the model; the grader still has private ground truth. (Cheapest, high leverage.)
2. **Add cases with no elementary closed form**, graded against a trusted reference instead:
   a once-computed converged fine-mesh "gold" solution, a published numerical benchmark, or
   experimental data. Tension: this reintroduces "grade against a simulation", so the gold
   solution must be frozen and independently trusted.
3. **Cross-check that the .odb actually exists and was produced this run** (not just that the
   reported number matches) — i.e. require evidence of the tool path, not only the answer.

**Status:** open. Likely adopt (1) broadly + a few (2) cases for the harder tiers.

---

## N2 — Script vs GUI behaviour gap (implicit steps the GUI auto-completes)

**Observation.** The agent's `run_python` scripts sometimes omit steps that Abaqus/CAE adds
automatically in the GUI. Concrete example: when creating an **axisymmetric** sketch, the script
did not draw the **construction symmetry axis**; the interactive GUI inserts/assumes it, but the
scripted `ConstrainedSketch` path does not, so the part is ill-defined.

**Why it matters.** This is a genuine, recurring scripted-modelling failure mode — and an
interesting one: it is not a hallucinated API (the calls are valid), but a *missing implicit
step* the model doesn't know the script must do explicitly. It will surface as a modelling error
(not a D3 API hallucination), and may unfairly fail otherwise-correct reasoning.

**Open questions (to discuss).**
- Is this best treated as (a) a legitimate thing the benchmark *should* catch (agent must know
  the scripting requirement), or (b) noise we should neutralize by documenting the requirement
  in the preamble / an Abaqus skill so all runs start on equal footing?
- Inventory other known GUI-implicit-vs-script-explicit gaps (axisymmetric construction line;
  default section assignment; auto-created sets; default field outputs; etc.) and decide which
  to document vs leave as a test.
- Could feed back into the ABAQUS-MCP server's `instructions.md` / a skill: a checklist of
  "things the script must do that the GUI does for you."

**Status:** open. Leaning toward documenting the most common gaps in a skill, while still
letting the benchmark record them as modelling errors (a separate tally from D3).
