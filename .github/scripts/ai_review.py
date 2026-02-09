#!/usr/bin/env python3
import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Finding:
    message: str
    line: str


SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|PRIVATE) KEY-----"),
]

LOGGING_SECRET_PATTERNS = [
    re.compile(r"\b(print|logger\.|log\.|console\.log)\b", re.IGNORECASE),
    re.compile(r"\b(secret|token|password|api[_-]?key|private[_-]?key)\b", re.IGNORECASE),
]

EXEC_PATTERNS = [
    re.compile(r"\beval\(", re.IGNORECASE),
    re.compile(r"\bexec\(", re.IGNORECASE),
    re.compile(r"\bos\.system\(", re.IGNORECASE),
    re.compile(r"subprocess\..*shell\s*=\s*True", re.IGNORECASE),
]

NETWORK_PATTERNS = [
    re.compile(r"\brequests\.(get|post|put|delete|patch)\(", re.IGNORECASE),
    re.compile(r"\bfetch\(", re.IGNORECASE),
    re.compile(r"\baxios\.", re.IGNORECASE),
    re.compile(r"\bwget\b", re.IGNORECASE),
    re.compile(r"\bcurl\b", re.IGNORECASE),
]

BYPASS_PATTERNS = [
    re.compile(r"\b(bypass|disable|skip|ignore)\s+(auth|authorization|authentication)\b", re.IGNORECASE),
    re.compile(r"\b(disable|skip|ignore)\s+audit\b", re.IGNORECASE),
]

PAYOUT_KEYWORDS = re.compile(r"(payout|distribution|dividend|revenue|expense)", re.IGNORECASE)
TEST_PATH_HINTS = re.compile(r"(^|/)(test|tests|__tests__|spec)(/|$)|\.spec\.|\.test\.", re.IGNORECASE)


def load_diff(diff_path: Path | None) -> str:
    if diff_path is None:
        return sys.stdin.read()
    return diff_path.read_text(encoding="utf-8")


def iter_added_lines(diff_text: str):
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            yield line[1:]


def changed_files(diff_text: str):
    files = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = parts[3]
                if path.startswith("b/"):
                    files.append(path[2:])
    return files


def scan(diff_text: str):
    findings: list[Finding] = []

    for added_line in iter_added_lines(diff_text):
        for pattern in SECRET_PATTERNS:
            if pattern.search(added_line):
                findings.append(Finding("Possible secret material detected", added_line))
                break

        if all(pattern.search(added_line) for pattern in LOGGING_SECRET_PATTERNS):
            findings.append(Finding("Logging of secret-like data detected", added_line))

        for pattern in EXEC_PATTERNS:
            if pattern.search(added_line):
                findings.append(Finding("Dynamic code execution detected", added_line))
                break

        for pattern in NETWORK_PATTERNS:
            if pattern.search(added_line):
                findings.append(Finding("Suspicious network call introduced", added_line))
                break

        for pattern in BYPASS_PATTERNS:
            if pattern.search(added_line):
                findings.append(Finding("Auth/audit bypass wording detected", added_line))
                break

    files = changed_files(diff_text)
    touches_payout = any(PAYOUT_KEYWORDS.search(path) for path in files)
    touches_tests = any(TEST_PATH_HINTS.search(path) for path in files)
    if touches_payout and not touches_tests:
        findings.append(
            Finding(
                "Payout/distribution-related changes without accompanying tests",
                "Affected files: " + ", ".join(sorted(set(files))),
            )
        )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline diff-only AI review gate")
    parser.add_argument("--diff-file", type=Path, help="Path to a unified diff")
    args = parser.parse_args()

    diff_text = load_diff(args.diff_file)
    if not diff_text.strip():
        print("No diff content provided; skipping AI review checks.")
        return 0

    findings = scan(diff_text)
    if not findings:
        print("AI review: no red flags found.")
        return 0

    print("AI review: red flags detected:")
    for finding in findings:
        print(f"- {finding.message}: {finding.line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
