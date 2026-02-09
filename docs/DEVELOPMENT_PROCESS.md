# Development Process

## PR-only flow

All changes must land via pull request. Direct pushes to protected branches are not allowed.

## Required checks

The repository enforces required checks that map to the CI workflow jobs created in Prompt #2.1:

- `backend`
- `frontend`
- `contracts`
- `dependency-review`
- `secrets-scan`

Optional checks that are enabled when ready (and then marked required):

- `ai-review` (diff-only guardrail, non-approving)
- `codeql` (enable when the repo is public or GitHub Advanced Security is available)

Any additional checks mandated in Prompt #2.1 should also be marked as required in branch
protection settings.

## Branch protection expectations

Protected branches must require:

- Pull request reviews before merge.
- Required status checks (`backend`, `frontend`, `contracts`, plus Prompt #2.1 additions).
- CODEOWNERS reviews for protected paths.
- Linear history (when feasible) and no force pushes.
- PR-only merge policy (no direct pushes to protected branches).

## Governance expectations

- Changes to CI, deployment, or payout/distribution logic require CODEOWNER review.
- Secrets must never be committed.
- All write operations are audited, and admin/oracle endpoints follow HMAC v1.
