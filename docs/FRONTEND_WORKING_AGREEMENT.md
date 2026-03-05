# Frontend Working Agreement (UI/UX Agent)

Purpose: keep frontend improvements fast, useful, and safe for core money invariants.

## Scope (allowed)

- `frontend/**`
- `docs/**` for UI/UX behavior and operator guidance

## Scope (do not change without explicit backend approval)

- `backend/**`
- `contracts/**`
- `backend/alembic/**`
- money-moving logic, settlement logic, fail-closed gates
- API response semantics (`{ success, data }`, `blocked_reason` behavior)

## Product goals

1. Improve readability for humans:
   - prioritize names/titles over long ids/hashes
   - show concise context near actions (what/why/next step)
2. Keep deterministic status visibility:
   - clear badges for `ready / stale / missing / blocked`
   - no ambiguous wording for money or reconciliation states
3. Keep timeline and activity useful:
   - meaningful headings and excerpts
   - links to the exact relevant section
4. Keep mobile usable:
   - no overflowed tables without fallback
   - key actions visible on small screens

## Onboarding Contract (skill-first)

- Canonical onboarding source for external agents is `frontend/public/skill.md` served as `/skill.md`.
- Home/onboarding UI should point agents to `/skill.md` first (simple self-serve flow), not to parallel custom instruction files.
- Do not introduce extra onboarding docs like `frontend/SKILLS.md`; this creates drift and confuses external agents.
- If onboarding copy changes, keep technical steps in sync with `frontend/public/skill.md` in the same PR.

## Display conventions

- Date/time display format in UI: `YYYY-MM-DD, HH:mm:ss`
- Agent label where possible: `Name (agent_id)`
- Avoid raw hash-first presentation when a human-readable field exists

## API and typing contract

- Do not hand-edit generated OpenAPI typings.
- If API shapes changed, regenerate types and include in same PR.
- Prefer typed API helpers over ad-hoc `fetch` in page components.

## PR quality bar

- One UX theme per PR (small and reviewable).
- Include before/after screenshots for changed pages.
- Explicitly list impacted routes.
- Mention potential regressions and how they were checked.

## Required checks before PR

```bash
cd frontend
npm run lint
npm run build
```

If API surface was touched:

```bash
scripts/generate_openapi_types.sh --check
```

## Coordination rules with backend agent

- Rebase on latest `main` before opening PR.
- If backend integration is in progress, avoid overlapping edits in:
  - `frontend/src/lib/api.ts`
  - `frontend/src/types/openapi.gen.ts`
- If overlap is unavoidable, sync first and merge in this order:
  1. backend contract PR
  2. frontend UX PR
