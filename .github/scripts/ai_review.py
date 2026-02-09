#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diff-only AI review stub.")
    parser.add_argument("--diff-file", required=True, help="Path to the diff file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    diff_path = Path(args.diff_file)
    if not diff_path.exists():
        print(f"Diff file not found: {diff_path}")
        return 1

    diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
    if not diff_text.strip():
        print("No diff to review.")
        return 0

    line_count = len(diff_text.splitlines())
    print(f"AI review stub: loaded diff with {line_count} lines.")
    print("Diff-only review complete. No comments or approvals issued.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
