# Tournament scheduling recommendations

| Format | Scheduling approach |
|---|---|
| Single elimination | Hu's highest-level-first, under the equal-duration assumptions |
| Double elimination | CP-SAT minimizing total tournament duration |

Hu's optimality guarantee assumes equal match durations, identical tables, and
tree-shaped match dependencies without additional rest constraints.

For double elimination, model match dependencies, table capacity, durations,
required rest, byes, and the conditional final reset. Recalculate after each
recorded result while keeping matches already running fixed. Use critical-path
priority as a fallback if the solver cannot finish within its time limit.

Only report a schedule as proven optimal when CP-SAT returns `OPTIMAL` with
optimality tolerances set to zero. A `FEASIBLE` result is not proof of optimality.
When durations are estimates, optimality applies to the modeled estimates.

References:

- [Hu's original paper](https://pubsonline.informs.org/doi/10.1287/opre.9.6.841)
- [OR-Tools resource-constrained scheduling example](https://github.com/google/or-tools/blob/stable/examples/python/rcpsp_sat.py)
- [CP-SAT solver status documentation](https://developers.google.com/optimization/cp/cp_solver)
