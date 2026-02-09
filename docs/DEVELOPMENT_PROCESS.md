# Development Process

## PR-only flow

All changes must land via pull request. Direct pushes to protected branches are not allowed.

## Required checks

The repository enforces required checks that map to the CI workflow jobs created in Prompt #2.1:

- `backend`
- `frontend`
- `contracts`
- `ai-review`

Any additional checks mandated in Prompt #2.1 should also be marked as required in branch
protection settings.

## Early-stage CI behavior

- AI review is diff-only, runs with a locally generated git diff, and makes no network calls or
  secret usage.
- Backend tests treat pytest exit code 5 as a skip with the message "No tests yet; skipping."
- Contracts checks may be non-enforcing until Prompt #9/#10 establishes the canonical Hardhat
  configuration and test harness.

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
