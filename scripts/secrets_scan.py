#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS Access Key ID", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "AWS Secret Access Key",
        re.compile(
            r"\baws_secret_access_key\b\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?",
            re.IGNORECASE,
        ),
    ),
    (
        "Private Key Header",
        re.compile(r"BEGIN (RSA|DSA|EC|OPENSSH|PGP)? ?PRIVATE KEY"),
    ),
    (
        "GitHub Token",
        re.compile(r"\b(ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    ("Slack Token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("Stripe Live Secret", re.compile(r"\bsk_live_[0-9a-zA-Z]{24,}\b")),
    (
        "JWT",
        re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"),
    ),
]


def scan_diff(diff_text: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    current_file: str | None = None
    new_line_num: int | None = None

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("@@"):
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if match:
                new_line_num = int(match.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            if current_file and new_line_num is not None:
                for name, pattern in PATTERNS:
                    if pattern.search(content):
                        findings.append((current_file, new_line_num, name))
            if new_line_num is not None:
                new_line_num += 1
            continue
        if line.startswith("-") and not line.startswith("---"):
            continue
        if line.startswith(" ") and new_line_num is not None:
            new_line_num += 1
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a git diff for potential secrets.")
    parser.add_argument(
        "--diff-range",
        default="origin/main...HEAD",
        help="Git diff range to scan (default: origin/main...HEAD)",
    )
    args = parser.parse_args()

    try:
        diff = subprocess.check_output(
            ["git", "diff", "--no-color", "--unified=0", args.diff_range],
            text=True,
            errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        print(f"Failed to read git diff for range '{args.diff_range}': {exc}", file=sys.stderr)
        return 2

    findings = scan_diff(diff)
    if findings:
        print("Potential secrets detected in git diff:")
        for path, line_number, name in findings:
            print(f"- {name} in {path}:{line_number}")
        return 1

    print("No secrets detected in git diff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
