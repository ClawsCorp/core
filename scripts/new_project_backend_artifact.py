#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = REPO_ROOT / "backend" / "src" / "project_artifacts"


def _validate_slug(value: str) -> str:
    slug = str(value or "").strip().lower()
    if not slug:
        raise SystemExit("missing slug")
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is None:
        raise SystemExit("invalid slug")
    if len(slug) > 64:
        raise SystemExit("slug too long")
    return slug


def _trim(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title")
    parser.add_argument("--summary")
    parser.add_argument("--endpoint", action="append", dest="endpoints", default=[])
    args = parser.parse_args()

    slug = _validate_slug(args.slug)
    title = _trim(args.title, 160)
    summary = _trim(args.summary, 1200)
    endpoints = [str(item).strip()[:200] for item in args.endpoints if str(item).strip()]

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_file = ARTIFACTS_DIR / f"{slug}.py"
    route_module_stem = slug.replace("-", "_")
    route_file = ARTIFACTS_DIR / f"{route_module_stem}_route.py"
    if artifact_file.exists() and route_file.exists():
        raise SystemExit(f"artifact already exists: {artifact_file}")

    payload = {
        "slug": slug,
        "title": title,
        "summary": summary,
        "endpoints": endpoints,
        "kind": "backend_artifact",
    }
    created_files: list[str] = []

    if not artifact_file.exists():
        source = "\n".join(
            [
                "# SPDX-License-Identifier: BSL-1.1",
                "",
                '"""Generated project backend artifact."""',
                "",
                "PROJECT_BACKEND_ARTIFACT = " + json.dumps(payload, indent=2, ensure_ascii=True),
                "",
            ]
        )
        artifact_file.write_text(source, encoding="utf-8")
        created_files.append(str(artifact_file.relative_to(REPO_ROOT)))

    if not route_file.exists():
        route_source = "\n".join(
            [
                "# SPDX-License-Identifier: BSL-1.1",
                "",
                '"""Generated executable project artifact route."""',
                "",
                "from __future__ import annotations",
                "",
                "from fastapi import APIRouter",
                "",
                "router = APIRouter(tags=['generated-project-artifacts'])",
                "",
                "_ARTIFACT = " + json.dumps(payload, indent=2, ensure_ascii=True),
                "",
                f"@router.get('/api/v1/project-artifacts/{slug}', include_in_schema=False)",
                "def get_generated_project_artifact() -> dict[str, object]:",
                "    data = dict(_ARTIFACT)",
                "    data['route_kind'] = 'template'",
                "    return {'success': True, 'data': data}",
                "",
            ]
        )
        route_file.write_text(route_source, encoding="utf-8")
        created_files.append(str(route_file.relative_to(REPO_ROOT)))

    print(
        json.dumps(
            {
                "ok": True,
                "slug": slug,
                "files": created_files,
                "endpoints": endpoints,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
