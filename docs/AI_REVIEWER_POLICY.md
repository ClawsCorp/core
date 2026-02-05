# AI Reviewer Policy (PR Security Gate)

## Goal
Use automated analysis + an LLM reviewer to reduce risk of malicious or unsafe code changes.

## Required checks
- Backend: lint + tests
- Frontend: lint + build
- Contracts: tests + static analysis (slither or equivalent)
- Dependency audit: npm/pip audit
- Secret scan
- AI review: diff-based analysis with explicit red-flag checklist

## AI review must fail the PR if:
- secrets/keys found or logging of secrets introduced
- suspicious network calls / data exfil patterns
- obfuscation, eval/exec, dynamic imports used without justification
- permissions escalations or bypass of auth/audit
- changes in payment/distribution logic without tests
