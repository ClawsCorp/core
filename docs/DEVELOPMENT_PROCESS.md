# Development Process

## PR-only flow

All changes must land via pull request. Direct pushes to protected branches are not allowed.

## Required checks

The repository enforces required checks that map to the CI workflow jobs created in Prompt #2.1:

- `backend`
- `frontend`
- `contracts`

Any additional checks mandated in Prompt #2.1 should also be marked as required in branch
protection settings.

## Early-stage CI behavior

- AI review runs on a locally generated diff only. It does not make network calls, does not
  use secrets, and produces a pass/fail status without comments or approvals.
- Backend pytest checks treat exit code 5 (no tests collected) as a successful skip with a
  clear message.
- Contracts checks are intentionally non-enforcing while Hardhat config is being finalized.
  Until Prompt #9/#10 establish the canonical setup, the workflow may skip if the Hardhat
  project markers are missing or if the config imports `hardhat` directly.

## Branch protection expectations

Protected branches must require:

- Pull request reviews before merge.
- Required status checks (`backend`, `frontend`, `contracts`, plus Prompt #2.1 additions).
- CODEOWNERS reviews for protected paths.
- Linear history (when feasible) and no force pushes.

## Governance expectations

- Changes to CI, deployment, or payout/distribution logic require CODEOWNER review.
- Secrets must never be committed.
- All write operations are audited, and admin/oracle endpoints follow HMAC v1.
