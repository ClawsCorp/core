# Development Process

## PR-only flow

All changes must land via pull request. Direct pushes to protected branches are not allowed.

## Required checks & merge policy

All changes must land via pull request. Direct pushes to protected branches are not allowed.

Required checks (match GitHub UI check names exactly):

- `backend`
- `frontend`
- `contracts`
- `dependency-review`
- `secrets-scan`
- `ai-review` (recommended required; Optional (enable later) if AI review is not yet enforced)

Notes:

- In GitHub branch protection UI, checks may appear without the `(pull_request)` suffix; select the
  closest matching check name.
- If any check names differ from the list above in the UI, update this document to match the
  actual check name (preferred). Only rename workflow/job `name:` fields if needed to stabilize
  check naming.

### Enable Dependency Graph to enforce dependency-review

Dependency Review only blocks high/critical advisories when GitHub Dependency graph is enabled.
Enable it in **Settings → Security & analysis → Dependency graph**. When Dependency graph is
disabled, the workflow will pass with a warning instead of blocking merges.

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
- CODEOWNERS reviews for protected paths.
- Required status checks:
  - `backend`
  - `frontend`
  - `contracts`
  - `dependency-review`
  - `secrets-scan`
  - `ai-review` (or mark as Optional (enable later))
- Linear history (when feasible) and no force pushes.
- (Optional) Restrict who can push to matching branches (e.g., release managers only).

If GitHub Advanced Security checks (e.g., CodeQL) are not enabled, note them as “enable when
ready” without blocking merges until they are available.

### Branch protection setup (GitHub UI)

1. Navigate to **Settings → Branches → Branch protection rules**.
2. Create or edit the rule for the default branch (e.g., `main`).
3. Enable:
   - **Require a pull request before merging**.
   - **Require approvals** and **Require review from Code Owners**.
   - **Require status checks to pass before merging** and select the checks listed above.
4. (Optional) Enable **Restrict who can push to matching branches**.

## Governance expectations

- Changes to CI, deployment, or payout/distribution logic require CODEOWNER review.
- Secrets must never be committed.
- All write operations are audited, and admin/oracle endpoints follow HMAC v1.
