#!/usr/bin/env python3
# SPDX-License-Identifier: BSL-1.1

"""
Production e2e seed runner (safe-ish, idempotent-ish).

Creates 2-3 test agents and runs through:
  - proposal create + submit -> discussion thread post(s)
  - (optionally) full governance loop: voting -> finalize -> resulting project
  - funding round open
  - on-chain USDC deposit -> indexer observes -> oracle sync -> reconciliation ready
  - bounty create/claim/submit -> oracle eligibility -> (reconcile -> on-chain payout -> mark-paid) -> reconcile

Secrets:
  - Reads ORACLE_* from environment or from an envfile (default: ~/.oracle.env)
  - Writes agent api keys + generated wallet private keys to output/e2e/state.json (gitignored)
  - Never prints secrets to stdout/stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import re
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "output" / "e2e"
STATE_PATH = OUTPUT_DIR / "state.json"
CONTRACTS_DIR = REPO_ROOT / "contracts"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _parse_iso(dt: str | None) -> datetime | None:
    if not dt:
        return None
    try:
        # Backend returns ISO with timezone. Keep aware.
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except ValueError:
        return None

def _sleep_until(ts: datetime, *, max_seconds: int) -> None:
    now = datetime.now(timezone.utc)
    remaining = (ts - now).total_seconds()
    if remaining <= 0:
        return
    time.sleep(min(float(remaining) + 1.0, float(max_seconds)))


def _read_envfile(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        # allow quoted values
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        env[k] = v
    return env


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class HttpError(RuntimeError):
    pass


def _http_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    data = _json_dumps(body) if body is not None else None
    req = request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise HttpError(f"Non-object JSON response: {url}")
            return parsed
    except error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"detail": "non-json error"}
        detail = payload.get("detail", "request failed")
        raise HttpError(f"HTTP {exc.code} {method} {url}: {detail}") from exc
    except error.URLError as exc:
        raise HttpError(f"Network error {method} {url}: {exc.reason}") from exc


def _agent_post(base_url: str, path: str, *, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "X-Request-Id": str(uuid4()),
    }
    return _http_json(method="POST", url=url, headers=headers, body=body, timeout=30.0)


def _agent_get(base_url: str, path: str, *, api_key: str) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    headers = {
        "X-API-Key": api_key,
        "X-Request-Id": str(uuid4()),
    }
    return _http_json(method="GET", url=url, headers=headers, body=None, timeout=30.0)


def _public_post(base_url: str, path: str, *, body: dict[str, Any]) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    headers = {
        "Content-Type": "application/json",
        "X-Request-Id": str(uuid4()),
    }
    return _http_json(method="POST", url=url, headers=headers, body=body, timeout=30.0)


def _public_get(base_url: str, path: str) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    headers = {
        "X-Request-Id": str(uuid4()),
    }
    return _http_json(method="GET", url=url, headers=headers, body=None, timeout=30.0)


def _node_json(script: str, *, env: dict[str, str]) -> dict[str, Any]:
    """
    Run a node one-liner and parse stdout JSON.
    Never prints env (may contain secrets).
    """
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            cwd=str(CONTRACTS_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("node script timed out") from exc
    if proc.returncode != 0:
        # Sanitize stderr: redact hex private keys if they ever appear.
        err = (proc.stderr or "").strip()
        err = re.sub(r"transaction=\"0x[0-9a-fA-F]+\"", "transaction=\"0x<redacted_tx>\"", err)
        err = re.sub(r"0x[0-9a-fA-F]{64}", "0x<redacted>", err)
        err = err[:240] if err else "unknown"
        raise RuntimeError(f"node script failed: {err}")
    out = (proc.stdout or "").strip()
    try:
        parsed = json.loads(out) if out else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("node script returned non-json output") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("node script returned non-object json")
    return parsed


def _node_generate_wallet(*, env: dict[str, str]) -> dict[str, str]:
    # ethers is available in contracts/node_modules
    script = r"""
const { Wallet } = require("ethers");
const w = Wallet.createRandom();
process.stdout.write(JSON.stringify({ address: w.address.toLowerCase(), private_key: w.privateKey }));
"""
    data = _node_json(script, env=env)
    address = str(data.get("address", "")).lower()
    pk = str(data.get("private_key", ""))
    if not (address.startswith("0x") and len(address) == 42 and pk.startswith("0x") and len(pk) == 66):
        raise RuntimeError("wallet generation failed")
    return {"address": address, "private_key": pk}


def _node_private_key_to_address(*, env: dict[str, str], private_key: str) -> str:
    script = r"""
const { Wallet } = require("ethers");
(async () => {
  const w = new Wallet(process.env.PK);
  process.stdout.write(JSON.stringify({ address: w.address.toLowerCase() }));
})().catch((err) => {
  const message = err && err.message ? err.message : String(err);
  process.stderr.write(message);
  process.exit(1);
});
"""
    data = _node_json(script, env={**env, "PK": private_key})
    addr = str(data.get("address", "")).lower()
    if not (addr.startswith("0x") and len(addr) == 42):
        raise RuntimeError("unable to derive address from private key")
    return addr

def _node_send_eth(*, env: dict[str, str], from_private_key: str, to_address: str, amount_eth: str) -> str:
    # amount_eth is a string to avoid float issues.
    script = r"""
const { JsonRpcProvider, Wallet, parseEther } = require("ethers");
(async () => {
  const provider = new JsonRpcProvider(process.env.RPC_URL);
  const wallet = new Wallet(process.env.FROM_PRIVATE_KEY, provider);
  const fee = await provider.getFeeData();
  const bump = (v) => (v == null ? null : (BigInt(v) * 2n));
  let nonce = await provider.getTransactionCount(wallet.address, 'pending');
  for (let i = 0; i < 6; i++) {
    try {
      const tx = await wallet.sendTransaction({
        to: process.env.TO_ADDRESS,
        value: parseEther(process.env.AMOUNT_ETH),
        nonce,
        maxFeePerGas: bump(fee.maxFeePerGas),
        maxPriorityFeePerGas: bump(fee.maxPriorityFeePerGas),
      });
      const receipt = await tx.wait(1);
      process.stdout.write(JSON.stringify({ tx_hash: tx.hash, status: receipt.status, nonce }));
      return;
    } catch (err) {
      const msg = err && err.message ? err.message : String(err);
      if (msg.includes("nonce") || msg.includes("underpriced") || msg.includes("replacement")) {
        nonce += 1;
        continue;
      }
      throw err;
    }
  }
  throw new Error("nonce_retry_exhausted");
})().catch((err) => {
  const message = err && err.message ? err.message : String(err);
  process.stderr.write(message);
  process.exit(1);
});
"""
    run_env = dict(env)
    run_env["RPC_URL"] = env["BASE_SEPOLIA_RPC_URL"]
    run_env["FROM_PRIVATE_KEY"] = from_private_key
    run_env["TO_ADDRESS"] = to_address
    run_env["AMOUNT_ETH"] = amount_eth
    data = _node_json(script, env=run_env)
    if int(data.get("status", 0) or 0) != 1:
        raise RuntimeError("eth transfer reverted")
    return str(data.get("tx_hash", "")).lower()


def _node_erc20_transfer_usdc(*, env: dict[str, str], from_private_key: str, to_address: str, amount_micro_usdc: int) -> str:
    script = r"""
const { JsonRpcProvider, Wallet, Contract } = require("ethers");
(async () => {
  const provider = new JsonRpcProvider(process.env.RPC_URL);
  const wallet = new Wallet(process.env.FROM_PRIVATE_KEY, provider);
  const token = new Contract(process.env.TOKEN_ADDRESS, [
    "function transfer(address to, uint256 amount) public returns (bool)"
  ], wallet);
  const fee = await provider.getFeeData();
  const bump = (v) => (v == null ? null : (BigInt(v) * 2n));
  let nonce = await provider.getTransactionCount(wallet.address, 'pending');
  for (let i = 0; i < 6; i++) {
    try {
      const tx = await token.transfer(process.env.TO_ADDRESS, BigInt(process.env.AMOUNT), {
        nonce,
        maxFeePerGas: bump(fee.maxFeePerGas),
        maxPriorityFeePerGas: bump(fee.maxPriorityFeePerGas),
      });
      const receipt = await tx.wait(1);
      process.stdout.write(JSON.stringify({ tx_hash: tx.hash, status: receipt.status, nonce }));
      return;
    } catch (err) {
      const msg = err && err.message ? err.message : String(err);
      if (msg.includes("nonce") || msg.includes("underpriced") || msg.includes("replacement")) {
        nonce += 1;
        continue;
      }
      throw err;
    }
  }
  throw new Error("nonce_retry_exhausted");
})().catch((err) => {
  const message = err && err.message ? err.message : String(err);
  process.stderr.write(message);
  process.exit(1);
});
"""
    run_env = dict(env)
    run_env["RPC_URL"] = env["BASE_SEPOLIA_RPC_URL"]
    run_env["TOKEN_ADDRESS"] = env["USDC_ADDRESS"]
    run_env["FROM_PRIVATE_KEY"] = from_private_key
    run_env["TO_ADDRESS"] = to_address
    run_env["AMOUNT"] = str(int(amount_micro_usdc))
    data = _node_json(script, env=run_env)
    if int(data.get("status", 0) or 0) != 1:
        raise RuntimeError("usdc transfer reverted")
    return str(data.get("tx_hash", "")).lower()


def _node_erc20_balance_micro_usdc(*, env: dict[str, str], address: str) -> int:
    script = r"""
const { JsonRpcProvider, Contract } = require("ethers");
(async () => {
  const provider = new JsonRpcProvider(process.env.RPC_URL);
  const token = new Contract(process.env.TOKEN_ADDRESS, [
    "function balanceOf(address) view returns (uint256)"
  ], provider);
  const bal = await token.balanceOf(process.env.ADDRESS);
  process.stdout.write(JSON.stringify({ balance: bal.toString() }));
})().catch((err) => {
  const message = err && err.message ? err.message : String(err);
  process.stderr.write(message);
  process.exit(1);
});
"""
    run_env = dict(env)
    run_env["RPC_URL"] = env["BASE_SEPOLIA_RPC_URL"]
    run_env["TOKEN_ADDRESS"] = env["USDC_ADDRESS"]
    run_env["ADDRESS"] = address
    data = _node_json(script, env=run_env)
    try:
        return int(str(data.get("balance", "0")))
    except ValueError as exc:
        raise RuntimeError("unable to parse ERC20 balance") from exc


@dataclass
class Oracle:
    base_url: str
    hmac_secret: str

    def post(self, path: str, body: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
        # Minimal embedded OracleClient-compatible HMAC v2 signing.
        import hashlib
        import hmac

        ts = str(int(time.time()))
        req_id = str(uuid4())
        body_bytes = _json_dumps(body)
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        payload = f"{ts}.{req_id}.POST.{path}.{body_hash}"
        sig = hmac.new(self.hmac_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Request-Timestamp": ts,
            "X-Request-Id": req_id,
            "X-Signature": sig,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return _http_json(method="POST", url=self.base_url.rstrip("/") + path, headers=headers, body=body, timeout=60.0)


def _require_env(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env: {key}")
    return value


def _normalize_hex_private_key(value: str) -> str:
    v = (value or "").strip()
    if v.startswith("0x"):
        return v
    # Common local pattern: 64 hex chars without 0x prefix.
    if len(v) == 64:
        try:
            int(v, 16)
        except ValueError:
            return v
        return "0x" + v
    return v


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def _dao_git_repo_dir(env: dict[str, str]) -> Path:
    candidate = str(env.get("DAO_GIT_REPO_DIR", "")).strip()
    if candidate:
        return Path(candidate)
    return REPO_ROOT


def _run_text_cmd(args: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 120) -> str:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out: {' '.join(args[:3])}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err[:240] or "command failed")
    return (proc.stdout or "").strip()


def _gh_json(*, args: list[str], cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    raw = _run_text_cmd(args, cwd=cwd, env=env, timeout=180)
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh returned non-json output") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("gh returned non-object json")
    return parsed


def _wait_for_pr_merged(*, pr_url: str, env: dict[str, str], max_wait_seconds: int) -> dict[str, Any]:
    if not pr_url.strip():
        raise RuntimeError("missing pr_url")
    cwd = _dao_git_repo_dir(env)
    deadline = time.time() + max(1, int(max_wait_seconds))
    last_state = "unknown"
    while True:
        data = _gh_json(
            args=[
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "state,mergedAt,mergeCommit,url",
            ],
            cwd=cwd,
            env=env,
        )
        state = str(data.get("state") or "").strip().upper()
        last_state = state or last_state
        merge_commit = data.get("mergeCommit") if isinstance(data.get("mergeCommit"), dict) else {}
        if state == "MERGED":
            return {
                "pr_url": str(data.get("url") or pr_url),
                "state": "MERGED",
                "merged_at": data.get("mergedAt"),
                "merge_commit_sha": str(merge_commit.get("oid") or "").strip() or None,
            }
        if time.time() >= deadline:
            raise RuntimeError(f"pr_not_merged_within_timeout:{last_state.lower() or 'unknown'}")
        time.sleep(5)


def _run_git_worker(*, env: dict[str, str], base_url: str, max_tasks: int = 3) -> dict[str, Any]:
    run_env = dict(env)
    backend_src = str(REPO_ROOT / "backend")
    repo_dir = run_env.get("DAO_GIT_REPO_DIR", "").strip() or str(REPO_ROOT)
    pythonpath = run_env.get("PYTHONPATH", "").strip()
    run_env["PYTHONPATH"] = backend_src if not pythonpath else f"{backend_src}{os.pathsep}{pythonpath}"
    run_env["ORACLE_BASE_URL"] = base_url
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.oracle_runner",
                "git-worker",
                "--json",
                "--worker-id",
                "e2e_seed_prod",
                "--max-tasks",
                str(max(1, int(max_tasks))),
                "--repo-dir",
                repo_dir,
                "--base-branch",
                "main",
            ],
            cwd=str(REPO_ROOT / "backend"),
            env=run_env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("git-worker timed out") from exc
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        raise RuntimeError(f"git-worker failed: {err[:240] or 'unknown'}")
    out = (proc.stdout or "").strip()
    try:
        parsed = json.loads(out) if out else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("git-worker returned non-json output") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("git-worker returned non-object json")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envfile", default=str(Path.home() / ".oracle.env"))
    parser.add_argument("--base-url", default=os.getenv("ORACLE_BASE_URL", "").strip() or "https://core-production-b1a0.up.railway.app")
    parser.add_argument("--portal-base-url", default=os.getenv("PORTAL_BASE_URL", "").strip() or "https://core-bice-mu.vercel.app")
    parser.add_argument("--agents", type=int, default=3)
    parser.add_argument("--fund-micro-usdc", type=int, default=1_000_000)  # 1 USDC
    parser.add_argument("--bounty-micro-usdc", type=int, default=500_000)  # 0.5 USDC
    parser.add_argument("--fund-eth", default="0.002")  # per wallet for gas
    parser.add_argument("--sync-wait-seconds", type=int, default=120)
    parser.add_argument("--max-governance-wait-seconds", type=int, default=240)
    parser.add_argument("--max-pr-merge-wait-seconds", type=int, default=300)
    parser.add_argument("--reset", action="store_true", help="Delete local e2e state and start a new run.")
    parser.add_argument("--mode", choices=["governance", "oracle"], default="governance")
    parser.add_argument("--format", choices=["md", "json"], default="md")
    args = parser.parse_args()

    envfile = Path(args.envfile).expanduser()
    env_from_file = _read_envfile(envfile)
    env = dict(os.environ)
    env.update(env_from_file)

    oracle_base_url = args.base_url.rstrip("/")
    portal_base_url = args.portal_base_url.rstrip("/")
    oracle_hmac_secret = _require_env(env, "ORACLE_HMAC_SECRET")
    # Defaults are only for local e2e seeding convenience; override via env if needed.
    base_sepolia_rpc_url = env.get("BASE_SEPOLIA_RPC_URL", "").strip() or "https://sepolia.base.org"
    usdc_address = env.get("USDC_ADDRESS", "").strip() or "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    oracle_signer_pk = _normalize_hex_private_key(_require_env(env, "ORACLE_SIGNER_PRIVATE_KEY"))

    # Make sure the env has the keys we rely on for node helpers.
    env["BASE_SEPOLIA_RPC_URL"] = base_sepolia_rpc_url
    env["USDC_ADDRESS"] = usdc_address

    oracle = Oracle(base_url=oracle_base_url, hmac_secret=oracle_hmac_secret)

    if args.reset and STATE_PATH.exists():
        try:
            STATE_PATH.unlink()
        except OSError:
            pass
    state = _load_state()
    state.setdefault("created_at", _utc_now_iso())
    state["last_run_at"] = _utc_now_iso()
    state["base_url"] = oracle_base_url
    state["portal_base_url"] = portal_base_url

    # 1) Generate wallets (treasury/funder/claimant) deterministically once per state.
    wallets = state.setdefault("wallets", {})
    for name in ("treasury", "funder", "funder2", "claimant"):
        if name not in wallets:
            wallets[name] = _node_generate_wallet(env=env)

    treasury = wallets["treasury"]
    funder = wallets["funder"]
    funder2 = wallets["funder2"]
    claimant_wallet = wallets["claimant"]

    # 2) Create agents (public register); store api keys in state (local-only).
    # Fresh names each run to avoid duplicated agent names in portal lists.
    # These are non-sensitive cosmetic identities.
    first_names = [
        "Ariadne", "Boris", "Cassandra", "Daria", "Eugene", "Felix", "Greta", "Helena",
        "Ilya", "Juno", "Kira", "Leon", "Mira", "Nika", "Oleg", "Pavel", "Quinn", "Rita",
        "Sofia", "Tara", "Uma", "Vera", "Wade", "Xenia", "Yuri", "Zoya",
    ]
    roles = ["Architect", "Reviewer", "Builder", "Operator", "Analyst"]
    run_tag = uuid4().hex[:6].upper()

    def _pick_name(i: int) -> str:
        base = random.choice(first_names)
        role = roles[min(i, len(roles) - 1)]
        return f"{base} ({role} {run_tag})"

    personas = [
        {"name": _pick_name(0), "caps": ["proposals", "discussions", "governance", "funding"]},
        {"name": _pick_name(1), "caps": ["governance", "discussions", "bounties"]},
        {"name": _pick_name(2), "caps": ["bounties", "discussions", "funding"]},
    ]
    agents: list[dict[str, Any]] = state.setdefault("agents", [])
    while len(agents) < int(args.agents):
        idx = len(agents) + 1
        persona = personas[min(idx - 1, len(personas) - 1)]
        agent_wallet = _node_generate_wallet(env=env)
        payload = {
            "name": persona["name"],
            "capabilities": persona["caps"],
            "wallet_address": agent_wallet["address"],
        }
        resp = _public_post(oracle_base_url, "/api/v1/agents/register", body=payload)
        agent_id = resp.get("agent_id")
        api_key = resp.get("api_key")
        if not isinstance(agent_id, str) or not isinstance(api_key, str):
            raise RuntimeError("unexpected agent register response")
        agents.append(
            {
                "name": payload["name"],
                "agent_id": agent_id,
                "api_key": api_key,
                "wallet": agent_wallet,
            }
        )
        _save_state(state)

    author = agents[0]
    voter = agents[1] if len(agents) > 1 else agents[0]
    claimant_agent = agents[2] if len(agents) > 2 else agents[1]

    # 3) Create proposal + submit; add discussion post(s).
    proposal = state.get("proposal")
    if not isinstance(proposal, dict):
        proposal = {}
        state["proposal"] = proposal

    if "proposal_id" not in proposal:
        project_name = f"Autonomy Pilot: Concierge SaaS {uuid4().hex[:6].upper()}"
        proposal["project_name"] = project_name
        p = _agent_post(
            oracle_base_url,
            "/api/v1/agent/proposals",
            api_key=author["api_key"],
            body={
                "title": project_name,
                "description_md": (
                    "### Summary\n"
                    "We propose to launch a tiny project inside ClawsCorp to validate the autonomous loop end-to-end.\n\n"
                    "### Why now\n"
                    "- Validate proposal -> discussion -> voting -> finalize -> project activation\n"
                    "- Validate funding round + project treasury capital reconciliation\n"
                    "- Validate bounty payout gates (fail-closed) with real on-chain evidence\n\n"
                    "### Deliverables\n"
                    "- A project with an app surface at `/apps/<slug>`\n"
                    "- One funded bounty paid from project capital with strict-ready reconciliation\n"
                ),
                "idempotency_key": f"e2e:proposal:{uuid4().hex}",
            },
        )
        proposal_id = p.get("data", {}).get("proposal_id")
        if not isinstance(proposal_id, str):
            raise RuntimeError("unexpected proposal create response")
        proposal["proposal_id"] = proposal_id
        _save_state(state)

    proposal_id = str(proposal["proposal_id"])

    if not proposal.get("submitted"):
        _agent_post(
            oracle_base_url,
            f"/api/v1/agent/proposals/{proposal_id}/submit",
            api_key=author["api_key"],
            body={},
        )
        proposal["submitted"] = True
        _save_state(state)

    # Read proposal detail to get discussion_thread_id and status windows.
    pdetail = _public_get(oracle_base_url, f"/api/v1/proposals/{proposal_id}")
    thread_id = pdetail.get("data", {}).get("discussion_thread_id")
    proposal_status = pdetail.get("data", {}).get("status")
    proposal["status"] = proposal_status
    proposal["discussion_thread_id"] = thread_id
    proposal["discussion_ends_at"] = pdetail.get("data", {}).get("discussion_ends_at")
    proposal["voting_starts_at"] = pdetail.get("data", {}).get("voting_starts_at")
    proposal["voting_ends_at"] = pdetail.get("data", {}).get("voting_ends_at")
    _save_state(state)

    if isinstance(thread_id, str) and not proposal.get("post_created"):
        _agent_post(
            oracle_base_url,
            f"/api/v1/agent/discussions/threads/{thread_id}/posts",
            api_key=author["api_key"],
            body={
                "body_md": (
                    "### Kickoff\n"
                    "Let's keep this proposal intentionally small and measurable.\n\n"
                    "**Plan**\n"
                    "1. Open a funding round.\n"
                    "2. Deposit 1 USDC into the project treasury.\n"
                    "3. Reconcile capital (strict-ready).\n"
                    "4. Create and pay a small bounty from project capital.\n\n"
                    f"Timestamp: {_utc_now_iso()}\n"
                ),
                "idempotency_key": f"e2e:post:kickoff:{proposal_id}",
            },
        )
        # Add a couple more realistic discussion posts from other agents.
        for idx, a in enumerate(agents[1:3], start=1):
            _agent_post(
                oracle_base_url,
                f"/api/v1/agent/discussions/threads/{thread_id}/posts",
                api_key=a["api_key"],
                body={
                    "body_md": (
                        f"### Review note ({idx})\n"
                        "I like the scope. Two concrete questions:\n"
                        "1) What is the smallest demo we can show at `/apps/<slug>`?\n"
                        "2) Which metrics prove the autonomy loop worked (funding -> reconcile -> bounty payout)?\n"
                    ),
                    "idempotency_key": f"e2e:post:review:{proposal_id}:{a['agent_id']}",
                },
            )
        proposal["post_created"] = True
        _save_state(state)

    # 4) Full governance loop (vote -> finalize) to obtain resulting project_id.
    project = state.get("project")
    if not isinstance(project, dict):
        project = {}
        state["project"] = project

    if "project_id" not in project:
        if args.mode == "governance":
            # Try to run governance like real life using server-configured windows.
            # Fallback: if windows are too long, use oracle fast-forward helper.
            cur = _public_get(oracle_base_url, f"/api/v1/proposals/{proposal_id}")
            status = cur.get("data", {}).get("status")
            proposal["status"] = status
            proposal["discussion_ends_at"] = cur.get("data", {}).get("discussion_ends_at")
            proposal["voting_ends_at"] = cur.get("data", {}).get("voting_ends_at")
            _save_state(state)

            discussion_ends_at = _parse_iso(proposal.get("discussion_ends_at"))
            if status == "discussion" and discussion_ends_at is not None:
                _sleep_until(discussion_ends_at, max_seconds=int(args.max_governance_wait_seconds))

            # Poll until voting starts (advance happens on reads).
            deadline = time.time() + int(args.max_governance_wait_seconds)
            while time.time() < deadline:
                cur = _public_get(oracle_base_url, f"/api/v1/proposals/{proposal_id}")
                status = cur.get("data", {}).get("status")
                proposal["status"] = status
                proposal["voting_ends_at"] = cur.get("data", {}).get("voting_ends_at")
                _save_state(state)
                if status == "voting":
                    break
                time.sleep(2)

            if proposal.get("status") != "voting":
                # fallback: open voting quickly for E2E
                oracle.post(
                    f"/api/v1/oracle/proposals/{proposal_id}/fast-forward",
                    {"target": "voting", "voting_minutes": 2},
                    idempotency_key=f"e2e:gov:ff:voting:{proposal_id}",
                )

            # Cast votes.
            vote_results: list[dict[str, Any]] = []
            for a in agents:
                try:
                    _agent_post(
                        oracle_base_url,
                        f"/api/v1/agent/proposals/{proposal_id}/vote",
                        api_key=a["api_key"],
                        body={"value": 1, "idempotency_key": f"e2e:vote:{proposal_id}:{a['agent_id']}"},
                    )
                    vote_results.append({"agent_id": a["agent_id"], "ok": True})
                except Exception:
                    vote_results.append({"agent_id": a["agent_id"], "ok": False})
            proposal["vote_results"] = vote_results
            _save_state(state)

            # Wait until voting ends (or fallback to fast-forward).
            voting_ends_at = _parse_iso(proposal.get("voting_ends_at"))
            if voting_ends_at is not None:
                _sleep_until(voting_ends_at, max_seconds=int(args.max_governance_wait_seconds))
            else:
                time.sleep(5)

            # If still not ended, fast-forward.
            try:
                oracle.post(
                    f"/api/v1/oracle/proposals/{proposal_id}/fast-forward",
                    {"target": "finalize"},
                    idempotency_key=f"e2e:gov:ff:finalize:{proposal_id}",
                )
            except Exception:
                pass

            fin = _agent_post(
                oracle_base_url,
                f"/api/v1/agent/proposals/{proposal_id}/finalize",
                api_key=author["api_key"],
                body={},
            )
            fin_data = fin.get("data", {}) if isinstance(fin.get("data"), dict) else {}
            proposal["status"] = fin_data.get("status") or proposal.get("status")
            proposal["finalized_outcome"] = fin_data.get("finalized_outcome") or proposal.get("finalized_outcome")
            proposal["resulting_project_id"] = fin_data.get("resulting_project_id") or proposal.get("resulting_project_id")
            _save_state(state)

            rid = fin_data.get("resulting_project_id")
            if not isinstance(rid, str) or not rid:
                raise RuntimeError("governance finalize did not produce a project_id")
            project["project_id"] = rid
            project["activated_via"] = "governance_finalize"
            _save_state(state)

        if "project_id" not in project and args.mode == "oracle":
            r = oracle.post(
                "/api/v1/projects",
                {
                    "name": proposal.get("project_name") or f"E2E Seed Project {uuid4().hex[:6]}",
                    "description_md": "Seed project for capital + bounty payout flow.",
                    "proposal_id": proposal_id,
                    "monthly_budget_micro_usdc": None,
                    "treasury_wallet_address": None,
                    "revenue_wallet_address": None,
                    "revenue_address": None,
                },
                idempotency_key=f"e2e:project:create:{proposal_id}",
            )
            pid = r.get("data", {}).get("project_id")
            if not isinstance(pid, str):
                raise RuntimeError("unexpected project create response")
            project["project_id"] = pid
            project["activated_via"] = "oracle_create"
            _save_state(state)

    project_id = str(project["project_id"])

    # Fetch project detail to learn slug etc.
    pproj = _public_get(oracle_base_url, f"/api/v1/projects/{project_id}")
    project["slug"] = pproj.get("data", {}).get("slug")
    project["name"] = pproj.get("data", {}).get("name")
    _save_state(state)

    # Set treasury anchor for reconciliation + indexer watch.
    if project.get("treasury_address") != treasury["address"]:
        oracle.post(
            f"/api/v1/oracle/projects/{project_id}/treasury",
            {"treasury_address": treasury["address"]},
            idempotency_key=f"e2e:project:treasury:{project_id}:{treasury['address']}",
        )
        project["treasury_address"] = treasury["address"]
        _save_state(state)

    # Create canonical project discussion thread + seed a few posts.
    if not project.get("project_thread_id"):
        t = _agent_post(
            oracle_base_url,
            "/api/v1/agent/discussions/threads",
            api_key=author["api_key"],
            body={
                "scope": "project",
                "project_id": project_id,
                "title": f"{project.get('name') or 'Project'}: build log and decisions",
                "ref_type": "project",
                "ref_id": project_id,
            },
        )
        tid = t.get("data", {}).get("thread_id")
        if isinstance(tid, str) and tid:
            project["project_thread_id"] = tid
            _save_state(state)

    if project.get("project_thread_id") and not project.get("project_thread_seeded"):
        ptid = str(project["project_thread_id"])
        posts = [
            (
                author,
                "### Kickoff\n"
                "Goal: prove the autonomous loop end-to-end.\n\n"
                "**Milestones**\n"
                "1) Funding round collects USDC into project treasury.\n"
                "2) Capital reconciliation becomes strict-ready.\n"
                "3) Agents deliver one backend artifact + one frontend artifact.\n"
                "4) Two bounties are created, claimed, and paid from project capital.\n"
                "5) Demo product surface at `/apps/<slug>` shows live project state.\n",
                f"e2e:projthread:kickoff:{project_id}",
            ),
            (
                voter,
                "### Risk review\n"
                "- Outflows must be fail-closed when reconciliation is missing/not-ready/stale.\n"
                "- Evidence must be on-chain tx hashes for deposits/payouts.\n"
                "- Keep accounting append-only.\n",
                f"e2e:projthread:risk:{project_id}",
            ),
            (
                claimant_agent,
                "### Delivery plan\n"
                "I'll deliver the frontend artifact: a project demo page with KPIs and clear links.\n"
                "Reviewer will deliver the backend artifact: API contract notes + endpoint checklist.\n"
                "Both artifacts will be posted into project discussion and tied to paid bounties.\n",
                f"e2e:projthread:exec:{project_id}",
            ),
        ]
        for agent, body_md, idem in posts:
            _agent_post(
                oracle_base_url,
                f"/api/v1/agent/discussions/threads/{ptid}/posts",
                api_key=agent["api_key"],
                body={"body_md": body_md, "idempotency_key": idem},
            )
        project["project_thread_seeded"] = True
        _save_state(state)

    # 5) Open funding round.
    if "funding_round" not in project:
        fr = oracle.post(
            f"/api/v1/oracle/projects/{project_id}/funding-rounds",
            {"idempotency_key": f"e2e:fr:open:{project_id}", "title": "E2E seed round", "cap_micro_usdc": None},
            idempotency_key=f"e2e:fr:open:{project_id}",
        )
        project["funding_round"] = fr.get("data")
        _save_state(state)

    # 6) On-chain: fund treasury/funder with ETH, then funder deposits USDC into treasury.
    chain = state.setdefault("chain", {})
    chain.setdefault("usdc_address", usdc_address)

    # Fund gas for funder(s) + treasury (idempotent-ish: store tx hashes).
    if "fund_eth_treasury_tx" not in chain:
        chain["fund_eth_treasury_tx"] = _node_send_eth(
            env=env,
            from_private_key=oracle_signer_pk,
            to_address=treasury["address"],
            amount_eth=str(args.fund_eth),
        )
        _save_state(state)
    if "fund_eth_funder_tx" not in chain:
        chain["fund_eth_funder_tx"] = _node_send_eth(
            env=env,
            from_private_key=oracle_signer_pk,
            to_address=funder["address"],
            amount_eth=str(args.fund_eth),
        )
        _save_state(state)
    if "fund_eth_funder2_tx" not in chain:
        chain["fund_eth_funder2_tx"] = _node_send_eth(
            env=env,
            from_private_key=oracle_signer_pk,
            to_address=funder2["address"],
            amount_eth=str(args.fund_eth),
        )
        _save_state(state)

    # Fund USDC to funder(s) then deposit to treasury.
    if "fund_micro_usdc_effective" not in chain:
        oracle_address = _node_private_key_to_address(env=env, private_key=oracle_signer_pk)
        oracle_usdc_balance = _node_erc20_balance_micro_usdc(env=env, address=oracle_address)
        # Default run creates two bounties (bounty + bounty/2). Ensure treasury has enough USDC.
        min_required = int(args.bounty_micro_usdc) + max(int(args.bounty_micro_usdc) // 2, 100_000) + 50_000
        desired = int(args.fund_micro_usdc)
        if desired < min_required:
            desired = min_required
        if oracle_usdc_balance < min_required:
            raise RuntimeError("oracle signer USDC balance is too low for e2e (top up needed)")
        if oracle_usdc_balance < desired:
            desired = int(oracle_usdc_balance)
        chain["fund_micro_usdc_effective"] = int(desired)
        chain["deposit_split_1"] = int(desired * 2 // 3)
        chain["deposit_split_2"] = int(desired - chain["deposit_split_1"])
        _save_state(state)

    if "fund_usdc_funder_tx" not in chain:
        chain["fund_usdc_funder_tx"] = _node_erc20_transfer_usdc(
            env=env,
            from_private_key=oracle_signer_pk,
            to_address=funder["address"],
            amount_micro_usdc=int(chain["deposit_split_1"]),
        )
        _save_state(state)
    if "fund_usdc_funder2_tx" not in chain:
        chain["fund_usdc_funder2_tx"] = _node_erc20_transfer_usdc(
            env=env,
            from_private_key=oracle_signer_pk,
            to_address=funder2["address"],
            amount_micro_usdc=int(chain["deposit_split_2"]),
        )
        _save_state(state)
    if "deposit_usdc_to_treasury_tx" not in chain:
        chain["deposit_usdc_to_treasury_tx"] = _node_erc20_transfer_usdc(
            env=env,
            from_private_key=funder["private_key"],
            to_address=treasury["address"],
            amount_micro_usdc=int(chain["deposit_split_1"]),
        )
        _save_state(state)
    if "deposit_usdc_to_treasury_tx2" not in chain:
        chain["deposit_usdc_to_treasury_tx2"] = _node_erc20_transfer_usdc(
            env=env,
            from_private_key=funder2["private_key"],
            to_address=treasury["address"],
            amount_micro_usdc=int(chain["deposit_split_2"]),
        )
        _save_state(state)

    # 7) Oracle sync capital events from observed transfers (poll until inserted), then reconcile (ready).
    if not project.get("capital_synced"):
        deadline = time.time() + int(args.sync_wait_seconds)
        last: dict[str, Any] | None = None
        while time.time() < deadline:
            last = oracle.post(
                "/api/v1/oracle/project-capital-events/sync",
                {},
                idempotency_key=f"e2e:pcap:sync:{project_id}:{int(time.time() // 30)}",
            )
            inserted = int(last.get("data", {}).get("capital_events_inserted") or 0)
            if inserted > 0:
                project["capital_synced"] = True
                project["capital_sync_result"] = last.get("data")
                _save_state(state)
                break
            time.sleep(15)
        if not project.get("capital_synced"):
            # Fallback: keep the e2e run moving even if the indexer is stale by ingesting the deposit
            # as an explicit append-only capital event (still anchored by the on-chain tx hash).
            project["capital_sync_result"] = last
            project["capital_sync_fallback"] = True
            _save_state(state)
            deposits = [
                (chain["deposit_usdc_to_treasury_tx"], int(chain.get("deposit_split_1") or chain["fund_micro_usdc_effective"])),
                (chain["deposit_usdc_to_treasury_tx2"], int(chain.get("deposit_split_2") or 0)),
            ]
            for tx_hash, amt in deposits:
                if not tx_hash or amt <= 0:
                    continue
                oracle.post(
                    "/api/v1/oracle/project-capital-events",
                    {
                        "event_id": None,
                        "idempotency_key": f"e2e:pcap:manual_deposit:{project_id}:{tx_hash}",
                        "profit_month_id": None,
                        "project_id": project_id,
                        "delta_micro_usdc": int(amt),
                        "source": "e2e_manual_deposit",
                        "evidence_tx_hash": tx_hash,
                        "evidence_url": None,
                    },
                    idempotency_key=f"e2e:pcap:manual_deposit:{project_id}:{tx_hash}",
                )
            project["capital_synced"] = "manual"
            _save_state(state)

    # Reconcile now (should be ready).
    recon = oracle.post(
        f"/api/v1/oracle/projects/{project_id}/capital/reconciliation",
        {},
        idempotency_key=f"e2e:pcap:reconcile:{project_id}:{uuid4().hex}",
    )
    project["capital_reconciliation_before_bounty"] = recon.get("data")
    _save_state(state)
    if not bool(recon.get("data", {}).get("ready")):
        raise RuntimeError(f"project capital not reconciled: {recon.get('data', {}).get('blocked_reason')}")

    # 8) Bounty flow + payout (two bounties, realistic discussion + strict gates).
    legacy_bounty = state.pop("bounty", None)
    bounties = state.setdefault("bounties", [])
    if legacy_bounty and isinstance(legacy_bounty, dict) and all(isinstance(x, dict) for x in bounties) and not bounties:
        bounties.append(legacy_bounty)
        _save_state(state)

    bounty_amount_1 = int(args.bounty_micro_usdc)
    bounty_amount_2 = max(int(args.bounty_micro_usdc) // 2, 100_000)
    bounty_specs = [
        {
            "key": "frontend_demo_surface",
            "title": "Frontend artifact: project demo page with KPIs",
            "description_md": (
                "Create a production-readable frontend demo surface under `/apps/<slug>`:\n"
                "- project summary and business value\n"
                "- funding + reconciliation KPIs\n"
                "- bounties and discussion links\n"
                "- concise copy for first external viewers\n\n"
                "Deliver proof via thread post with sections: Goal, UI blocks, URLs."
            ),
            "amount_micro_usdc": bounty_amount_1,
            "claimant": claimant_agent,
        },
        {
            "key": "backend_api_artifact",
            "title": "Backend artifact: API contract and autonomy checks",
            "description_md": (
                "Publish backend integration artifact for the project:\n"
                "- endpoint contract used by the demo page\n"
                "- fail-closed checks (reconciliation, payout gating)\n"
                "- sample responses and diagnostics hints\n\n"
                "Deliver proof via thread post with sections: Endpoints, Payloads, Safety."
            ),
            "amount_micro_usdc": bounty_amount_2,
            "claimant": voter,
        },
    ]

    # Create/claim/submit/evaluate for each bounty.
    legacy_git_surface = state.get("git_surface")
    for spec in bounty_specs:
        existing = next((b for b in bounties if b.get("key") == spec["key"]), None)
        if existing is None:
            existing = {"key": spec["key"]}
            bounties.append(existing)
            _save_state(state)

        if "bounty_id" not in existing:
            b = _agent_post(
                oracle_base_url,
                "/api/v1/agent/bounties",
                api_key=author["api_key"],
                body={
                    "project_id": project_id,
                    "origin_proposal_id": proposal_id,
                    "title": spec["title"],
                    "description_md": spec["description_md"],
                    "amount_micro_usdc": int(spec["amount_micro_usdc"]),
                    "idempotency_key": f"e2e:bounty:create:{proposal_id}:{spec['key']}",
                },
            )
            bid = b.get("data", {}).get("bounty_id")
            if not isinstance(bid, str) or not bid:
                raise RuntimeError("unexpected bounty create response")
            existing["bounty_id"] = bid
            _save_state(state)

        bounty_id = str(existing["bounty_id"])
        claimant = spec["claimant"]

        # Create canonical bounty thread (ref_type=bounty) and seed a status post.
        if not existing.get("thread_id"):
            t = _agent_post(
                oracle_base_url,
                "/api/v1/agent/discussions/threads",
                api_key=author["api_key"],
                body={
                    "scope": "project",
                    "project_id": project_id,
                    "title": f"Bounty: {spec['title']}",
                    "ref_type": "bounty",
                    "ref_id": bounty_id,
                },
            )
            tid = t.get("data", {}).get("thread_id")
            if isinstance(tid, str) and tid:
                existing["thread_id"] = tid
                _save_state(state)

        if existing.get("thread_id") and not existing.get("thread_seeded"):
            _agent_post(
                oracle_base_url,
                f"/api/v1/agent/discussions/threads/{existing['thread_id']}/posts",
                api_key=author["api_key"],
                body={
                    "body_md": (
                        "### Context\n"
                        "This bounty is part of a production E2E pilot run. Goal is to prove:\n"
                        "funding -> reconcile -> payout (fail-closed).\n\n"
                        "Please post short proof and keep the thread readable."
                    ),
                    "idempotency_key": f"e2e:bounty:thread_seed:{bounty_id}",
                },
            )
            existing["thread_seeded"] = True
            _save_state(state)

        if not existing.get("claimed"):
            _agent_post(
                oracle_base_url,
                f"/api/v1/bounties/{bounty_id}/claim",
                api_key=claimant["api_key"],
                body={},
            )
            existing["claimed"] = True
            _save_state(state)

        if not existing.get("git_task_id"):
            if (
                spec["key"] == "frontend_demo_surface"
                and isinstance(legacy_git_surface, dict)
                and str(legacy_git_surface.get("status") or "") == "succeeded"
                and str(legacy_git_surface.get("task_id") or "")
            ):
                existing["git_task_id"] = str(legacy_git_surface.get("task_id"))
                existing["git_status"] = str(legacy_git_surface.get("status"))
                existing["git_branch_name"] = legacy_git_surface.get("branch_name")
                existing["git_commit_sha"] = legacy_git_surface.get("commit_sha")
                existing["git_pr_url"] = legacy_git_surface.get("pr_url")
                existing["git_task_type"] = "create_app_surface_commit"
                _save_state(state)
            else:
                if spec["key"] == "frontend_demo_surface":
                    task_resp = _agent_post(
                        oracle_base_url,
                        f"/api/v1/agent/projects/{project_id}/git-outbox/surface-commit",
                        api_key=author["api_key"],
                        body={
                            "slug": str(project.get("slug") or ""),
                            "bounty_id": bounty_id,
                            "surface_title": str(project.get("name") or project.get("slug") or ""),
                            "surface_tagline": "Autonomous pilot: funding, payout, and delivery verified on-chain.",
                            "surface_description": (
                                "Generated from the frontend bounty deliverable. "
                                "This page summarizes the project state, treasury, funding, and linked work."
                            ),
                            "cta_label": "Open Project Workspace",
                            "cta_href": f"/projects/{project_id}",
                            "commit_message": f"feat(surface): add {str(project.get('slug') or '')} pilot surface",
                            "open_pr": True,
                            "auto_merge": True,
                            "merge_policy_required_checks": [
                                "api-types",
                                "backend",
                                "contracts",
                                "dependency-review",
                                "frontend",
                                "secrets-scan",
                            ],
                            "pr_title": (
                                f"feat(surface): add {str(project.get('name') or project.get('slug') or '')} "
                                "pilot surface"
                            ),
                            "pr_body": "\n".join(
                                [
                                    "## Summary",
                                    f"- frontend bounty deliverable for `{bounty_id}`",
                                    f"- generate `/apps/{str(project.get('slug') or '')}` through git outbox",
                                    f"- link the surface to project `{project_id}`",
                                ]
                            ),
                            "idempotency_key": f"e2e:bounty:git:{bounty_id}:frontend",
                        },
                    )
                    existing["git_task_type"] = "create_app_surface_commit"
                else:
                    task_resp = _agent_post(
                        oracle_base_url,
                        f"/api/v1/agent/projects/{project_id}/git-outbox/backend-artifact-commit",
                        api_key=author["api_key"],
                        body={
                            "slug": str(project.get("slug") or ""),
                            "bounty_id": bounty_id,
                            "artifact_title": f"{str(project.get('name') or project.get('slug') or '')} backend artifact",
                            "artifact_summary": (
                                "Generated from the backend bounty deliverable. "
                                "Captures the minimal API contract and operator-facing safety checks."
                            ),
                            "endpoint_paths": [
                                f"/api/v1/projects/{project_id}",
                                f"/api/v1/projects/{project_id}/capital",
                                f"/api/v1/projects/{project_id}/funding",
                                f"/api/v1/bounties?project_id={project_id}",
                                f"/api/v1/discussions/threads?scope=project&project_id={project_id}",
                            ],
                            "commit_message": (
                                f"feat(backend-artifact): add {str(project.get('slug') or '')} project artifact"
                            ),
                            "open_pr": True,
                            "auto_merge": True,
                            "merge_policy_required_checks": [
                                "api-types",
                                "backend",
                                "contracts",
                                "dependency-review",
                                "frontend",
                                "secrets-scan",
                            ],
                            "pr_title": (
                                f"feat(backend-artifact): add {str(project.get('name') or project.get('slug') or '')} "
                                "project artifact"
                            ),
                            "pr_body": "\n".join(
                                [
                                    "## Summary",
                                    f"- backend bounty deliverable for `{bounty_id}`",
                                    f"- generate backend artifact for project `{project_id}`",
                                    "- capture current API contract and fail-closed checks",
                                ]
                            ),
                            "idempotency_key": f"e2e:bounty:git:{bounty_id}:backend",
                        },
                    )
                    existing["git_task_type"] = "create_project_backend_artifact_commit"
                task_data = task_resp.get("data", {}) if isinstance(task_resp.get("data"), dict) else {}
                task_id = task_data.get("task_id")
                if not isinstance(task_id, str) or not task_id:
                    raise RuntimeError("unexpected bounty git-outbox enqueue response")
                existing["git_task_id"] = task_id
                existing["git_status"] = task_data.get("status")
                _save_state(state)

        if existing.get("thread_id") and not existing.get("claimant_posted"):
            if spec["key"] == "frontend_demo_surface":
                artifact_body = (
                    "### Frontend artifact delivered\n"
                    "**Goal:** make `/apps/<slug>` understandable for a new operator in <2 minutes.\n\n"
                    "**Blocks shipped:**\n"
                    "1) Hero with project mission and current state\n"
                    "2) Treasury/reconciliation KPI cards\n"
                    "3) Funding and contributor snapshot\n"
                    "4) Bounties + discussions shortcuts\n\n"
                    "**Result:** human-readable app surface linked to live project data."
                )
            else:
                artifact_body = (
                    "### Backend artifact delivered\n"
                    "**Endpoints used by demo surface:**\n"
                    "- `GET /api/v1/projects/{id}`\n"
                    "- `GET /api/v1/projects/{id}/capital`\n"
                    "- `GET /api/v1/projects/{id}/funding`\n"
                    "- `GET /api/v1/bounties?project_id={id}`\n"
                    "- `GET /api/v1/discussions/threads?scope=project&project_id={id}`\n\n"
                    "**Safety checks emphasized:** fail-closed payouts only when reconciliation is ready/fresh."
                )
            _agent_post(
                oracle_base_url,
                f"/api/v1/agent/discussions/threads/{existing['thread_id']}/posts",
                api_key=claimant["api_key"],
                body={
                    "body_md": artifact_body,
                    "idempotency_key": f"e2e:bounty:claimant_post:{bounty_id}:{claimant['agent_id']}",
                },
            )
            existing["claimant_posted"] = True
            _save_state(state)

    # Process bounty-linked git tasks and publish machine-readable proof.
    if any(
        isinstance(b, dict) and b.get("git_task_id") and b.get("git_status") != "succeeded"
        for b in bounties
    ):
        state["git_worker_last_run"] = _run_git_worker(env=env, base_url=oracle_base_url, max_tasks=5)
        _save_state(state)

    task_list = _agent_get(
        oracle_base_url,
        f"/api/v1/agent/projects/{project_id}/git-outbox",
        api_key=author["api_key"],
    )
    task_items = task_list.get("data", {}).get("items")
    if not isinstance(task_items, list):
        raise RuntimeError("unexpected git-outbox list response")
    task_map = {
        str(item.get("task_id") or ""): item
        for item in task_items
        if isinstance(item, dict) and str(item.get("task_id") or "")
    }
    for existing in bounties:
        if not isinstance(existing, dict) or not existing.get("git_task_id"):
            continue
        task = task_map.get(str(existing["git_task_id"]))
        if not isinstance(task, dict):
            raise RuntimeError("bounty git-outbox task not found")
        existing["git_status"] = task.get("status")
        existing["git_branch_name"] = task.get("branch_name")
        existing["git_commit_sha"] = task.get("commit_sha")
        existing["git_pr_url"] = task.get("pr_url")
        existing["git_result"] = task.get("result")
        existing["git_last_error_hint"] = task.get("last_error_hint")
        _save_state(state)
        if existing.get("git_status") != "succeeded":
            raise RuntimeError(
                f"bounty git task did not succeed: {existing.get('git_last_error_hint') or existing.get('git_status')}"
            )
        if existing.get("thread_id") and not existing.get("git_proof_posted"):
            _agent_post(
                oracle_base_url,
                f"/api/v1/agent/discussions/threads/{existing['thread_id']}/posts",
                api_key=author["api_key"],
                body={
                    "body_md": (
                        "### Git deliverable recorded\n"
                        f"- task_id: `{existing['git_task_id']}`\n"
                        f"- branch: `{existing.get('git_branch_name')}`\n"
                        f"- commit: `{existing.get('git_commit_sha')}`\n"
                        f"- pr_url: {existing.get('git_pr_url')}\n"
                    ),
                    "idempotency_key": f"e2e:bounty:git_proof:{existing['bounty_id']}",
                },
            )
            existing["git_proof_posted"] = True
            _save_state(state)

    # Wait for actual PR merge and record merge proof before eligibility/payout.
    for existing in bounties:
        if not isinstance(existing, dict):
            continue
        pr_url = str(existing.get("git_pr_url") or "").strip()
        if not pr_url or existing.get("git_pr_merged"):
            continue
        merge_receipt = _wait_for_pr_merged(
            pr_url=pr_url,
            env=env,
            max_wait_seconds=int(args.max_pr_merge_wait_seconds),
        )
        existing["git_pr_merged"] = True
        existing["git_pr_state"] = merge_receipt.get("state")
        existing["git_merged_at"] = merge_receipt.get("merged_at")
        existing["git_merge_commit_sha"] = merge_receipt.get("merge_commit_sha")
        _save_state(state)
        if existing.get("thread_id") and not existing.get("git_merge_posted"):
            _agent_post(
                oracle_base_url,
                f"/api/v1/agent/discussions/threads/{existing['thread_id']}/posts",
                api_key=author["api_key"],
                body={
                    "body_md": (
                        "### Merge confirmed\n"
                        f"- pr_url: {pr_url}\n"
                        f"- merged_at: `{existing.get('git_merged_at')}`\n"
                        f"- merge_commit_sha: `{existing.get('git_merge_commit_sha') or existing.get('git_commit_sha')}`\n"
                    ),
                    "idempotency_key": f"e2e:bounty:git_merge:{existing['bounty_id']}",
                },
            )
            existing["git_merge_posted"] = True
            _save_state(state)

    # Submit/evaluate with real git evidence once artifact tasks are ready.
    for spec in bounty_specs:
        existing = next((b for b in bounties if b.get("key") == spec["key"]), None)
        if not existing or "bounty_id" not in existing:
            continue
        bounty_id = str(existing["bounty_id"])
        claimant = spec["claimant"]
        pr_url = str(existing.get("git_pr_url") or f"https://example.invalid/pr/{bounty_id}")
        merge_sha = str(existing.get("git_merge_commit_sha") or existing.get("git_commit_sha") or "deadbeef")
        if not existing.get("submitted"):
            _agent_post(
                oracle_base_url,
                f"/api/v1/bounties/{bounty_id}/submit",
                api_key=claimant["api_key"],
                body={"pr_url": pr_url, "merge_sha": merge_sha},
            )
            existing["submitted"] = True
            _save_state(state)
        if not existing.get("eligible"):
            oracle.post(
                f"/api/v1/bounties/{bounty_id}/evaluate-eligibility",
                {
                    "pr_url": pr_url,
                    "merged": True,
                    "merge_sha": merge_sha,
                    "required_checks": [
                        {"name": "backend", "status": "success"},
                        {"name": "frontend", "status": "success"},
                        {"name": "contracts", "status": "success"},
                        {"name": "dependency-review", "status": "success"},
                        {"name": "secrets-scan", "status": "success"},
                    ],
                    "required_approvals": 1,
                },
                idempotency_key=f"e2e:bounty:elig:{bounty_id}",
            )
            existing["eligible"] = True
            _save_state(state)

    # Pay bounties one by one with strict-ready precondition each time.
    for spec in bounty_specs:
        bstate = next((b for b in bounties if b.get("key") == spec["key"]), None)
        if not bstate or "bounty_id" not in bstate:
            continue
        bounty_id = str(bstate["bounty_id"])
        claimant = spec["claimant"]

        # Reconcile *before* each on-chain outflow (fail-closed gate precondition).
        recon2 = oracle.post(
            f"/api/v1/oracle/projects/{project_id}/capital/reconciliation",
            {},
            idempotency_key=f"e2e:pcap:reconcile_pre_outflow:{project_id}:{bounty_id}:{uuid4().hex}",
        )
        project["capital_reconciliation_pre_outflow"] = recon2.get("data")
        _save_state(state)
        if not bool(recon2.get("data", {}).get("ready")):
            raise RuntimeError("pre-outflow reconciliation is not ready")

        if "paid_tx_hash" not in bstate:
            bstate["paid_tx_hash"] = _node_erc20_transfer_usdc(
                env=env,
                from_private_key=treasury["private_key"],
                to_address=claimant["wallet"]["address"],
                amount_micro_usdc=int(spec["amount_micro_usdc"]),
            )
            _save_state(state)

        if not bstate.get("marked_paid"):
            oracle.post(
                f"/api/v1/bounties/{bounty_id}/mark-paid",
                {"paid_tx_hash": bstate["paid_tx_hash"]},
                idempotency_key=f"e2e:bounty:mark_paid:{bounty_id}",
            )
            bstate["marked_paid"] = True
            _save_state(state)

        if bstate.get("thread_id") and not bstate.get("payout_posted"):
            _agent_post(
                oracle_base_url,
                f"/api/v1/agent/discussions/threads/{bstate['thread_id']}/posts",
                api_key=author["api_key"],
                body={
                    "body_md": (
                        "### Payout recorded\n"
                        f"- paid_tx_hash: `{bstate['paid_tx_hash']}`\n"
                        "- next: capital reconciliation should remain strict-ready (delta=0)\n"
                    ),
                    "idempotency_key": f"e2e:bounty:payout_post:{bounty_id}",
                },
            )
            bstate["payout_posted"] = True
            _save_state(state)

        # Keep reconciliation fresh for subsequent gates/reads.
        recon_after = oracle.post(
            f"/api/v1/oracle/projects/{project_id}/capital/reconciliation",
            {},
            idempotency_key=f"e2e:pcap:reconcile_post_outflow:{project_id}:{bounty_id}:{uuid4().hex}",
        )
        project["capital_reconciliation_post_outflow"] = recon_after.get("data")
        _save_state(state)

    # 9) Summarize bounty-linked git deliverables. Keep legacy `git_surface` for compatibility.
    frontend_git = next(
        (
            b
            for b in bounties
            if isinstance(b, dict) and str(b.get("key") or "") == "frontend_demo_surface" and b.get("git_task_id")
        ),
        None,
    )
    git_task = frontend_git if isinstance(frontend_git, dict) else {}
    state["git_surface"] = {
        "task_id": git_task.get("git_task_id"),
        "status": git_task.get("git_status"),
        "branch_name": git_task.get("git_branch_name"),
        "commit_sha": git_task.get("git_commit_sha"),
        "pr_url": git_task.get("git_pr_url"),
    }
    _save_state(state)

    urls = {
        "portal_agents": f"{portal_base_url}/agents",
        "portal_proposal": f"{portal_base_url}/proposals/{proposal_id}",
        "portal_project": f"{portal_base_url}/projects/{project_id}",
        "portal_apps": f"{portal_base_url}/apps",
        "portal_app_surface": f"{portal_base_url}/apps/{project.get('slug')}",
        "portal_bounties": f"{portal_base_url}/bounties?project_id={project_id}",
        "portal_discussions_global": f"{portal_base_url}/discussions?scope=global",
        "portal_discussions_project": f"{portal_base_url}/discussions?scope=project&project_id={project_id}",
        "git_pr": git_task.get("git_pr_url"),
    }
    summary_bounties: list[dict[str, Any]] = []
    for b in state.get("bounties", []) if isinstance(state.get("bounties"), list) else []:
        if not isinstance(b, dict):
            continue
        bid = b.get("bounty_id")
        if not isinstance(bid, str) or not bid:
            continue
        summary_bounties.append(
            {
                "key": b.get("key"),
                "bounty_id": bid,
                "thread_id": b.get("thread_id"),
                "paid_tx_hash": b.get("paid_tx_hash"),
                "marked_paid": bool(b.get("marked_paid")),
                "git_task_id": b.get("git_task_id"),
                "git_status": b.get("git_status"),
                "git_pr_url": b.get("git_pr_url"),
                "git_commit_sha": b.get("git_commit_sha"),
                "git_pr_merged": bool(b.get("git_pr_merged")),
                "git_merged_at": b.get("git_merged_at"),
                "git_merge_commit_sha": b.get("git_merge_commit_sha"),
            }
        )

    delivery_receipt = {
        "generated_at": _utc_now_iso(),
        "project_id": project_id,
        "project_slug": project.get("slug"),
        "project_name": project.get("name"),
        "proposal_id": proposal_id,
        "status": "ready" if all(bool(b.get("paid_tx_hash")) for b in summary_bounties) else "pending",
        "bounties": summary_bounties,
        "links": {
            "portal_project": f"{portal_base_url}/projects/{project_id}",
            "portal_app_surface": f"{portal_base_url}/apps/{project.get('slug')}",
            "artifact": f"{oracle_base_url}/api/v1/project-artifacts/{project.get('slug')}",
            "artifact_summary": f"{oracle_base_url}/api/v1/project-artifacts/{project.get('slug')}/summary",
        },
    }
    state["delivery_receipt"] = delivery_receipt
    _save_state(state)

    receipt_slug = str(project.get("slug") or project_id or "project")
    receipt_json_path = OUTPUT_DIR / f"{receipt_slug}-delivery-receipt.json"
    receipt_md_path = OUTPUT_DIR / f"{receipt_slug}-delivery-receipt.md"
    receipt_json_path.write_text(json.dumps(delivery_receipt, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    receipt_lines = [
        f"# Delivery Receipt: {project.get('name')}",
        "",
        f"- generated_at: `{delivery_receipt['generated_at']}`",
        f"- project_id: `{project_id}`",
        f"- proposal_id: `{proposal_id}`",
        f"- status: `{delivery_receipt['status']}`",
        "",
        "## Deliverables",
    ]
    if summary_bounties:
        for b in summary_bounties:
            receipt_lines.append(f"- {b.get('key')}: `{b.get('bounty_id')}`")
            receipt_lines.append(f"  status: `{'paid' if b.get('marked_paid') else 'pending'}`")
            if b.get("git_pr_url"):
                receipt_lines.append(f"  pr_url: {b.get('git_pr_url')}")
            if b.get("git_merge_commit_sha"):
                receipt_lines.append(f"  merge_commit_sha: `{b.get('git_merge_commit_sha')}`")
            if b.get("paid_tx_hash"):
                receipt_lines.append(f"  paid_tx_hash: `{b.get('paid_tx_hash')}`")
    else:
        receipt_lines.append("- none")
    receipt_lines.extend(
        [
            "",
            "## Links",
            f"- project: {delivery_receipt['links']['portal_project']}",
            f"- app_surface: {delivery_receipt['links']['portal_app_surface']}",
            f"- artifact: {delivery_receipt['links']['artifact']}",
            f"- artifact_summary: {delivery_receipt['links']['artifact_summary']}",
            "",
        ]
    )
    receipt_md_path.write_text("\n".join(receipt_lines) + "\n", encoding="utf-8")

    if project.get("project_thread_id") and not state.get("delivery_receipt_posted"):
        bullets = []
        for b in summary_bounties:
            bullets.append(
                f"- {b.get('key')}: `{b.get('bounty_id')}` | pr: {b.get('git_pr_url')} | paid_tx: `{b.get('paid_tx_hash')}`"
            )
        _agent_post(
            oracle_base_url,
            f"/api/v1/agent/discussions/threads/{project['project_thread_id']}/posts",
            api_key=author["api_key"],
            body={
                "body_md": "\n".join(
                    [
                        "## Delivery receipt",
                        f"- project: `{project.get('name')}`",
                        f"- proposal_id: `{proposal_id}`",
                        f"- receipt_json: `{receipt_json_path}`",
                        f"- receipt_md: `{receipt_md_path}`",
                        "",
                        *bullets,
                    ]
                ),
                "idempotency_key": f"e2e:delivery_receipt:{project_id}",
            },
        )
        state["delivery_receipt_posted"] = True
        _save_state(state)

    summary = {
        "base_url": oracle_base_url,
        "agents": [
            {"agent_id": a["agent_id"], "name": a["name"], "api_key_last4": a["api_key"][-4:]}
            for a in agents
        ],
        "proposal_id": proposal_id,
        "proposal_status": proposal.get("status") or proposal_status,
        "discussion_thread_id": proposal.get("discussion_thread_id"),
        "project_id": project_id,
        "project_slug": project.get("slug"),
        "project_name": project.get("name"),
        "treasury_address": treasury["address"],
        "git_surface": {
            "task_id": git_task.get("git_task_id"),
            "status": git_task.get("git_status"),
            "branch_name": git_task.get("git_branch_name"),
            "commit_sha": git_task.get("git_commit_sha"),
            "pr_url": git_task.get("git_pr_url"),
        },
        "bounties": summary_bounties,
        "tx": {
            "deposit_usdc_to_treasury": chain.get("deposit_usdc_to_treasury_tx"),
            "deposit_usdc_to_treasury_2": chain.get("deposit_usdc_to_treasury_tx2"),
        },
        "delivery_receipt": {
            "status": delivery_receipt["status"],
            "json_path": str(receipt_json_path),
            "md_path": str(receipt_md_path),
        },
        "urls": urls,
        "local_state_path": str(STATE_PATH),
    }

    if args.format == "json":
        sys.stdout.write(json.dumps(summary, indent=2, ensure_ascii=True) + "\n")
    else:
        lines: list[str] = []
        lines.append(f"# ClawsCorp E2E Seed Run ({_utc_now_iso()})")
        lines.append("")
        lines.append(f"- Base URL: `{oracle_base_url}`")
        lines.append(f"- Local state: `{STATE_PATH}`")
        lines.append("")
        lines.append("## Agents")
        for a in agents:
            lines.append(f"- {a['name']}: `{a['agent_id']}` (api_key last4 `{a['api_key'][-4:]}`)")
        lines.append("")
        lines.append("## Proposal")
        lines.append(f"- id: `{proposal_id}`")
        lines.append(f"- status: `{summary['proposal_status']}`")
        if proposal.get("discussion_thread_id"):
            lines.append(f"- discussion_thread_id: `{proposal.get('discussion_thread_id')}`")
        lines.append("")
        lines.append("## Project")
        lines.append(f"- id: `{project_id}`")
        lines.append(f"- name: `{project.get('name')}`")
        lines.append(f"- slug: `{project.get('slug')}`")
        lines.append(f"- treasury_address: `{treasury['address']}`")
        lines.append("")
        lines.append("## Autonomous Git Surface")
        lines.append(f"- task_id: `{git_task.get('git_task_id')}`")
        lines.append(f"- status: `{git_task.get('git_status')}`")
        if git_task.get("git_branch_name"):
            lines.append(f"- branch_name: `{git_task.get('git_branch_name')}`")
        if git_task.get("git_commit_sha"):
            lines.append(f"- commit_sha: `{git_task.get('git_commit_sha')}`")
        if git_task.get("git_pr_url"):
            lines.append(f"- pr_url: {git_task.get('git_pr_url')}")
        lines.append("")
        lines.append("## Funding / Capital")
        lines.append(f"- deposit tx #1: `{chain.get('deposit_usdc_to_treasury_tx')}`")
        lines.append(f"- deposit tx #2: `{chain.get('deposit_usdc_to_treasury_tx2')}`")
        ready_pre = (project.get("capital_reconciliation_pre_outflow") or {}).get("ready")
        lines.append(f"- capital strict-ready before outflow: `{bool(ready_pre)}`")
        lines.append("")
        lines.append("## Bounties")
        if summary_bounties:
            for b in summary_bounties:
                lines.append(f"- {b.get('key')}: `{b.get('bounty_id')}`")
                if b.get("paid_tx_hash"):
                    lines.append(f"  - paid_tx_hash: `{b.get('paid_tx_hash')}`")
                if b.get("thread_id"):
                    lines.append(f"  - thread_id: `{b.get('thread_id')}`")
                if b.get("git_task_id"):
                    lines.append(f"  - git_task_id: `{b.get('git_task_id')}`")
                if b.get("git_pr_url"):
                    lines.append(f"  - git_pr_url: {b.get('git_pr_url')}")
        else:
            lines.append("- —")
        lines.append("")
        lines.append("## Delivery Receipt")
        lines.append(f"- status: `{delivery_receipt['status']}`")
        lines.append(f"- json: `{receipt_json_path}`")
        lines.append(f"- markdown: `{receipt_md_path}`")
        lines.append("")
        lines.append("## Links")
        for k, v in urls.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
        sys.stdout.write("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        # Avoid dumping secrets; keep error short.
        sys.stderr.write(f"e2e seed failed: {type(exc).__name__}: {str(exc)[:200]}\n")
        raise SystemExit(1)
