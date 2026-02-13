from __future__ import annotations

import re
from pathlib import Path


def test_alembic_revision_ids_are_short_enough() -> None:
    """
    Railway runs Alembic against PostgreSQL. By default, Alembic uses
    `alembic_version.version_num VARCHAR(32)`, so revision identifiers longer than
    32 chars will crash deploys when Alembic tries to update the version table.
    """

    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    assert versions_dir.exists(), f"Missing alembic versions dir: {versions_dir}"

    rev_re = re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.M)

    bad: list[tuple[str, str, int]] = []
    for path in sorted(versions_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        match = rev_re.search(text)
        if not match:
            continue
        rev = match.group(1)
        if len(rev) > 32:
            bad.append((path.name, rev, len(rev)))

    assert not bad, "Alembic revision id(s) > 32 chars: " + ", ".join(
        f"{name}({length}):{rev}" for name, rev, length in bad
    )

