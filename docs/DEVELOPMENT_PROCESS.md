# Development Process

## PR-only flow

All changes must land via pull request. Direct pushes to protected branches are not allowed.

## Required checks

The repository enforces required checks that map to the CI workflow jobs created in Prompt #2.1:

- `backend`
- `frontend`
- `contracts`
- `dependency-review`
- `secrets-scan` (if configured)
- `ai-review` (optional, non-privileged diff gate)
- `codeql` (optional, when enabled)

Any additional checks mandated in Prompt #2.1 should also be marked as required in branch
protection settings.

## Branch protection expectations

Protected branches must require:

- Pull request reviews before merge.
- Required status checks (`backend`, `frontend`, `contracts`, plus Prompt #2.1 additions).
- CODEOWNERS reviews for protected paths.
- Linear history (when feasible) and no force pushes.

## Enablement notes

- Dependency Review requires Dependency Graph to be enabled in **Settings → Security & analysis**.
  When disabled, the workflow will emit a warning and pass so early repos are not blocked.
- AI review is a diff-only, non-privileged check that does not comment, approve, or merge.
- If no tests exist yet, the backend and contracts jobs will skip tests instead of failing.

## Governance expectations

- Changes to CI, deployment, or payout/distribution logic require CODEOWNER review.
- Secrets must never be committed.
- All write operations are audited, and admin/oracle endpoints follow HMAC v1.
