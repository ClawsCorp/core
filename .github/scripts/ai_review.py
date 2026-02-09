#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff-only AI review stub.")
    parser.add_argument("--diff-file", required=True, help="Path to diff file")
    args = parser.parse_args()

    diff_path = Path(args.diff_file)
    if not diff_path.exists():
        print(f"Diff file not found: {diff_path}")
        return 1

    diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
    diff_lines = [line for line in diff_text.splitlines() if line.strip()]
    print(f"AI review stub: loaded {len(diff_lines)} non-empty diff lines.")
    print("Diff-only review complete. No network calls were made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
