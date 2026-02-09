#!/usr/bin/env python3
"""Deterministic, local-only diff scanner for AI review checks."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Finding:
    label: str
    message: str


def load_diff(path: str | None) -> str:
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    return sys.stdin.read()


def iter_paths(diff_text: str) -> Iterable[str]:
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            yield line.replace("+++ b/", "", 1).strip()


def scan(diff_text: str) -> list[Finding]:
    findings: list[Finding] = []
    secret_patterns = [
        ("secret", re.compile(r"AKIA[0-9A-Z]{16}")),
        ("secret", re.compile(r"ASIA[0-9A-Z]{16}")),
        ("secret", re.compile(r"ghp_[A-Za-z0-9]{36}")),
        ("secret", re.compile(r"github_pat_[A-Za-z0-9_]{80,}")),
        ("secret", re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----")),
        ("secret", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
        ("secret", re.compile(r"sk_live_[A-Za-z0-9]{20,}")),
    ]
    risk_patterns = [
        ("exec", re.compile(r"\b(exec|eval)\b")),
        ("exfil", re.compile(r"(curl|wget).*(http|https)://")),
        ("auth", re.compile(r"(disable|bypass).*(auth|audit)", re.IGNORECASE)),
        ("logging", re.compile(r"log(ging)?\s*.*(secret|token|password)", re.IGNORECASE)),
    ]

    for label, pattern in secret_patterns + risk_patterns:
        if pattern.search(diff_text):
            findings.append(
                Finding(label=label, message=f"Potential {label} issue detected: {pattern.pattern}")
            )

    payout_keywords = re.compile(r"(payout|distribution|dividend|revenue|expense)", re.IGNORECASE)
    if payout_keywords.search(diff_text):
        paths = list(iter_paths(diff_text))
        has_tests = any(
            "test" in path.lower() or "spec" in path.lower() for path in paths
        )
        if not has_tests:
            findings.append(
                Finding(
                    label="payout",
                    message="Payout/distribution logic touched without tests in diff.",
                )
            )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diff", help="Path to diff file. Reads stdin if omitted.")
    args = parser.parse_args()

    diff_text = load_diff(args.diff)
    if not diff_text.strip():
        print("No diff content to analyze.")
        return 0

    findings = scan(diff_text)
    if findings:
        print("AI review flagged potential issues:")
        for finding in findings:
            print(f"- [{finding.label}] {finding.message}")
        return 1

    print("AI review found no red flags.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
