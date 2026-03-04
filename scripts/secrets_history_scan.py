#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    revision: str
    path: str
    line_number: int
    pattern: str


PATTERNS: list[tuple[str, str]] = [
    ("AWS Access Key ID", r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("Private Key Header", r"BEGIN (RSA|DSA|EC|OPENSSH|PGP)? ?PRIVATE KEY"),
    ("GitHub Token", r"\b(ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ("Slack Token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ("Google API Key", r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    ("Stripe Live Secret", r"\bsk_live_[0-9a-zA-Z]{24,}\b"),
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _revision_chunks(size: int) -> list[list[str]]:
    revs_cmd = _run(["git", "rev-list", "--all"])
    if revs_cmd.returncode != 0:
        raise RuntimeError(f"git rev-list failed: {revs_cmd.stderr.strip()}")
    revisions = [line.strip() for line in revs_cmd.stdout.splitlines() if line.strip()]
    chunks: list[list[str]] = []
    for i in range(0, len(revisions), max(1, int(size))):
        chunks.append(revisions[i : i + max(1, int(size))])
    return chunks


def _scan_pattern(pattern_name: str, pattern: str, chunks: list[list[str]], max_findings: int) -> list[Finding]:
    findings: list[Finding] = []
    for chunk in chunks:
        cmd = ["git", "grep", "-nI", "-E", pattern] + chunk
        completed = _run(cmd)
        if completed.returncode not in {0, 1}:
            raise RuntimeError(f"git grep failed: {completed.stderr.strip()}")
        if completed.returncode == 1:
            continue
        for line in completed.stdout.splitlines():
            # format: <rev>:<path>:<line>:<content>
            parts = line.split(":", 3)
            if len(parts) < 4:
                continue
            rev, path, line_no_s, _ = parts
            try:
                line_no = int(line_no_s)
            except ValueError:
                continue
            findings.append(
                Finding(
                    revision=rev.strip(),
                    path=path.strip(),
                    line_number=line_no,
                    pattern=pattern_name,
                )
            )
            if len(findings) >= max_findings:
                return findings
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan full git revision history for high-confidence secret patterns.")
    parser.add_argument("--max-findings", type=int, default=50)
    parser.add_argument("--revision-chunk-size", type=int, default=150)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    max_findings = max(1, int(args.max_findings))
    chunk_size = max(10, int(args.revision_chunk_size))
    chunks = _revision_chunks(chunk_size)

    findings: list[Finding] = []
    for name, pattern in PATTERNS:
        remaining = max_findings - len(findings)
        if remaining <= 0:
            break
        findings.extend(_scan_pattern(name, pattern, chunks, remaining))

    payload = {
        "success": len(findings) == 0,
        "patterns_checked": [name for name, _ in PATTERNS],
        "revisions_scanned": sum(len(chunk) for chunk in chunks),
        "revision_chunk_size": chunk_size,
        "findings_count": len(findings),
        "findings": [
            {
                "revision": f.revision,
                "path": f.path,
                "line_number": f.line_number,
                "pattern": f.pattern,
            }
            for f in findings
        ],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    else:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if len(findings) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
