#!/usr/bin/env bash
set -euo pipefail

# Local checks mirroring .github/workflows/ci.yml.
#
# Usage:
#   scripts/check.sh              # run all
#   scripts/check.sh backend      # only backend
#   scripts/check.sh frontend     # only frontend
#   scripts/check.sh contracts    # only contracts
#   scripts/check.sh secrets      # only secrets diff scan

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

targets=()
if [[ "$#" -eq 0 ]]; then
  targets=(backend frontend contracts secrets)
else
  for arg in "$@"; do
    case "$arg" in
      backend|frontend|contracts|secrets) targets+=("$arg") ;;
      *)
        echo "error: unknown target '$arg' (expected: backend|frontend|contracts|secrets)" >&2
        exit 1
        ;;
    esac
  done
fi

need_bootstrap=0

if [[ " ${targets[*]} " == *" backend "* ]]; then
  if [[ ! -x ".venv/bin/python" ]]; then
    need_bootstrap=1
  fi
fi

if [[ " ${targets[*]} " == *" frontend "* ]]; then
  if [[ ! -d "frontend/node_modules" || ! -x "frontend/node_modules/.bin/eslint" || ! -x "frontend/node_modules/.bin/next" ]]; then
    need_bootstrap=1
  fi
fi

if [[ " ${targets[*]} " == *" contracts "* ]]; then
  if [[ ! -d "contracts/node_modules" || ! -x "contracts/node_modules/.bin/hardhat" ]]; then
    need_bootstrap=1
  fi
fi

if [[ "${need_bootstrap}" -eq 1 ]]; then
  echo "error: missing local deps (.venv and/or node_modules). Run: scripts/bootstrap.sh" >&2
  exit 1
fi

for t in "${targets[@]}"; do
  case "$t" in
    backend)
      echo "[check] backend: pytest"
      PYTHONPATH=backend .venv/bin/python -m pytest -q
      ;;
    frontend)
      echo "[check] frontend: lint"
      npm --prefix frontend run lint
      echo "[check] frontend: build"
      npm --prefix frontend run build
      ;;
    contracts)
      echo "[check] contracts: compile"
      npm --prefix contracts run compile
      echo "[check] contracts: test"
      npm --prefix contracts test
      ;;
    secrets)
      echo "[check] secrets: diff scan"
      python3 scripts/secrets_scan.py --diff-range "origin/main...HEAD"
      ;;
  esac
done

echo "[check] ok"
