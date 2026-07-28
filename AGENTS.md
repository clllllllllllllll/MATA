# Agent Guidelines

Behavioral guidelines for reducing common LLM coding mistakes in MATA.
The project documentation defines the system architecture and business rules.

**Tradeoff:** These guidelines favor correctness and focused changes over
speed. Use judgment for trivial tasks.

## 1. Read Before Coding

**Do not guess how MATA should behave.**

Before implementing:

- Read the relevant existing code and tests.
- Read the applicable project documentation:
  - `docs/schema.md` for models, migrations, and database queries.
  - `docs/api.md` for endpoints and request/response contracts.
  - `docs/business-logic.md` for calculations and domain behavior.
  - `docs/parsing.md` for workbook uploads and parsing.
  - `docs/security.md` for cross-cutting authentication, authorization,
    session, RLS, privacy, deployment, and security-maintenance contracts.
- Read every applicable document when a change crosses domains.
- Treat the documentation as authoritative over existing implementation.
- Check whether the requested behavior is marked TBD or deferred.

Do not implement a business rule from memory or infer one from nearby code.

## 2. Think Before Coding

**Do not assume. Do not hide uncertainty. Surface material tradeoffs.**

Before making changes:

- State assumptions that affect behavior, data, authorization, or APIs.
- If multiple reasonable interpretations exist, explain them.
- Ask when the choice would materially change the result.
- Point out conflicts between the request, documentation, tests, and code.
- Suggest a simpler approach when one clearly exists.
- Push back when a request would violate a documented invariant.

Investigate first. Ask only when the answer cannot be established safely from
the repository.

## 3. Simplicity First

**Write the minimum code needed to solve the requested problem.**

- Do not add features that were not requested.
- Do not introduce speculative flexibility or configurability.
- Do not create abstractions for one-off behavior.
- Do not add fallbacks for unsupported or undocumented scenarios.
- Reuse existing services and helpers when they already fit.
- Prefer explicit domain logic over clever generalization.
- Do not implement requirements marked TBD or deferred.

If the solution is substantially larger than the problem, reconsider it.

## 4. Make Surgical Changes

**Touch only what the requested outcome requires.**

When editing existing code:

- Do not refactor unrelated code.
- Do not reformat or rewrite adjacent files unnecessarily.
- Match the repository’s existing style and structure.
- Preserve unrelated and user-authored changes.
- Mention unrelated problems instead of fixing them silently.
- Remove only the imports, variables, functions, and files made obsolete by
  your own change.
- Do not rewrite existing migrations unless explicitly requested.

Every changed line should have a clear connection to the requested outcome.

## 5. Respect Project Boundaries

**Put changes in the layer that owns the behavior.**

- Routers handle HTTP concerns and authorization.
- Services contain business logic.
- Schemas define API contracts.
- Models and migrations define persistence.
- Tests verify observable behavior.

When a change affects multiple layers, update them consistently. Do not place
business calculations in routers or duplicate domain logic across endpoints.

## 6. Preserve Invariants

**Do not weaken guarantees to make implementation easier.**

- Preserve authorization and programme/posting scope enforcement.
- Preserve database constraints and transactional behavior.
- Do not silently change API response or error contracts.
- Do not weaken validation without an explicit requirement.
- Do not invent compatibility behavior for undocumented cases.
- Do not add secrets, credentials, production data, or sensitive personal
  information to the repository.

If a requested change conflicts with a documented invariant, stop and surface
the conflict.

## 7. Work Toward Verifiable Goals

**Define success before implementation and loop until it is verified.**

Translate requests into observable outcomes:

- “Fix the bug” → reproduce it with a test, then make the test pass.
- “Add validation” → test accepted and rejected inputs.
- “Change an endpoint” → verify authorization, response shape, and errors.
- “Change persistence” → verify the model, migration, constraints, and queries.
- “Refactor” → establish passing behavior before and after the change.

For non-trivial work, use a brief plan:

1. Inspect the relevant implementation and requirements.
2. Make the smallest coherent change.
3. Add or update regression coverage.
4. Run the relevant verification.

Do not stop at “the code looks correct.”

## 8. Verify Before Reporting Completion

**Never claim success without evidence.**

Before reporting completion:

- Run the most relevant tests.
- Run broader tests when shared behavior may be affected.
- Run formatting, linting, type checking, and migration checks when applicable.
- Inspect failures rather than assuming they are unrelated.
- State exactly what was verified.
- Clearly report checks that could not be run and why.

A behavioral change should normally include regression coverage.

---

**These guidelines are working when:**

- Diffs contain only changes required by the task.
- Implementations follow the documented MATA behavior.
- Clarifying questions happen before incorrect assumptions are coded.
- Solutions are simpler and contain fewer speculative abstractions.
- Completion claims are supported by tests or other concrete verification.
