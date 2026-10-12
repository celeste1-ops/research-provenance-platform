# Method (draft 2)

We model the flow speed v with dv/dt = k (1 - v)^alpha(F), alpha(F) = 1.5 - 0.2 F.

The equation is solved with the FSF solver v0.2 (adaptive step size; commit c05b9e2). A sweep over k and F (35 runs) shows that alpha(F) stays linear within 0.03 for 0.25 <= F <= 2.

Changes after the meeting with the advisor: the lattice cross-check is removed (wrong boundary condition); a sensitivity sweep is added.

*Sample text: the research is fictional.*
