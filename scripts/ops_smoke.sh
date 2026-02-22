#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

ENV_FILE=""
MONTH="auto"
TX_TASKS="${TX_TASKS:-5}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="${2:-}"
      shift 2
      ;;
    --month)
      MONTH="${2:-auto}"
      shift 2
      ;;
    --tx-max-tasks)
      TX_TASKS="${2:-5}"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      echo "Usage: scripts/ops_smoke.sh [--env-file /path/to/.env] [--month YYYYMM|auto] [--tx-max-tasks N]" >&2
      exit 2
      ;;
  esac
done

if [[ -n "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

if [[ -z "${ORACLE_BASE_URL:-}" ]]; then
  ORACLE_BASE_URL="https://core-production-b1a0.up.railway.app"
fi
export ORACLE_BASE_URL
if [[ -z "${ORACLE_HMAC_SECRET:-}" ]]; then
  echo "ORACLE_HMAC_SECRET is required (or pass --env-file)." >&2
  exit 2
fi

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PY_BIN="$ROOT_DIR/.venv/bin/python"
else
  PY_BIN="python3"
fi

echo "[ops-smoke] api=${ORACLE_BASE_URL} month=${MONTH} tx_max_tasks=${TX_TASKS}" >&2

cd "$BACKEND_DIR"

echo "[ops-smoke] billing-sync" >&2
"$PY_BIN" -m src.oracle_runner billing-sync --json || true

echo "[ops-smoke] sync-project-capital" >&2
"$PY_BIN" -m src.oracle_runner sync-project-capital --json || true

echo "[ops-smoke] tx-worker" >&2
"$PY_BIN" -m src.oracle_runner tx-worker --max-tasks "$TX_TASKS" --json || true

echo "[ops-smoke] reconcile month=${MONTH}" >&2
"$PY_BIN" -m src.oracle_runner reconcile --month "$MONTH" --json || true

echo "[ops-smoke] alerts" >&2
ALERTS_JSON="$(curl -fsS "${ORACLE_BASE_URL%/}/api/v1/alerts")"
echo "$ALERTS_JSON"

ALERTS_JSON="$ALERTS_JSON" "$PY_BIN" - <<'PY'
import json
import os
import sys

data = json.loads(os.environ["ALERTS_JSON"])
items = ((data.get("data") or {}).get("items") or [])
critical = [x for x in items if str(x.get("severity")) == "critical"]

if critical:
    print(f"[ops-smoke] critical alerts: {len(critical)}", file=sys.stderr)
    for item in critical:
        print(
            f"[ops-smoke] - {item.get('alert_type')} ref={item.get('ref')} message={item.get('message')}",
            file=sys.stderr,
        )
    raise SystemExit(1)

print(f"[ops-smoke] ok: no critical alerts (total alerts={len(items)})", file=sys.stderr)
PY
