# sales-integrated

An autonomous client-acquisition agent for freelancers. The agent finds
in-ICP prospects, drafts and (within limits the user sets) sends compliant
outreach, drafts content, books calls and reports back, for a flat
subscription with no take rate and no ad-spend margin.

Working title for the product: **Current** (placeholder, not final).

## Status

Brainstorm converged; nothing is built yet. This repo currently holds the
decisions and the plan for testing the riskiest assumption before code.

| Doc | What it is |
| --- | --- |
| [docs/00-product-decisions.md](docs/00-product-decisions.md) | What was decided in the brainstorm, and what is still open |
| [docs/01-validation-plan.md](docs/01-validation-plan.md) | Concierge test with 5 freelancers: success and kill thresholds |
| [docs/02-architecture-notes.md](docs/02-architecture-notes.md) | Model tiering on a VPS, send guard, compliance engine, autonomy dial |

A clickable visual prototype of the dashboard, onboarding interview,
decisions inbox and funnel run view lives in a design artifact linked from
the session that produced these docs.

## Principles

1. **An outcome, not a toolbox.** One promise: calls booked with the right people.
2. **Autonomy is a dial, not a switch.** Everything starts at "approve first".
3. **The LLM writes and classifies. It never decides money, rates or compliance.**
4. **Compliance blocks, it does not warn.** EU first, per-country rules.
5. **One living metaphor, one hot accent, huge numerals.** Strong, simple, memorable.
