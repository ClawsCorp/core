#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mode="${1:-}"
if [[ -n "${mode}" && "${mode}" != "--check" ]]; then
  echo "usage: scripts/generate_openapi_types.sh [--check]" >&2
  exit 2
fi

tmp_json="$(mktemp)"
cleanup() { rm -f "${tmp_json}"; }
trap cleanup EXIT

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    PYTHON_BIN="python3"
  fi
fi

PYTHONPATH=backend "${PYTHON_BIN}" - <<'PY' >"${tmp_json}"
import json
from src.main import app

print(json.dumps(app.openapi()))
PY

npm --prefix frontend exec -- openapi-typescript "${tmp_json}" -o frontend/src/types/openapi.gen.ts

if [[ "${mode}" == "--check" ]]; then
  git diff --exit-code -- frontend/src/types/openapi.gen.ts
fi
