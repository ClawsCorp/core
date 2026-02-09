# Maintainers

This repository uses placeholder CODEOWNERS entries until formal teams/users are assigned.

## Replacing placeholders

1. Identify the real GitHub users or teams who will own each area.
2. Update `.github/CODEOWNERS` entries by replacing placeholders like `@clawscorp/core-maintainers`
   with the correct `@org/team` or `@username`.
3. Ensure CODEOWNERS is committed via PR and reviewed by current maintainers.
4. Confirm branch protection requires CODEOWNER review for protected paths.

## Placeholder mapping

| Placeholder | Intended scope |
| --- | --- |
| `@clawscorp/core-maintainers` | Global ownership for the repository |
| `@clawscorp/contract-maintainers` | Smart contract sources under `/contracts/` |
| `@clawscorp/backend-core-maintainers` | Backend core logic under `/backend/src/core/` |
| `@clawscorp/backend-tasks-maintainers` | Background tasks under `/backend/src/tasks/` |
| `@clawscorp/backend-services-maintainers` | Service logic under `/backend/src/services/` |
| `@clawscorp/platform-maintainers` | CI/CD and workflow definitions |
| `@clawscorp/finance-maintainers` | Payout/distribution sensitive paths |

Keep this list updated as real teams are defined.
