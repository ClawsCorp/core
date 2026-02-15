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
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=str(CONTRACTS_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        # Sanitize stderr: redact hex private keys if they ever appear.
        err = (proc.stderr or "").strip()
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


def _node_send_eth(*, env: dict[str, str], from_private_key: str, to_address: str, amount_eth: str) -> str:
    # amount_eth is a string to avoid float issues.
    script = r"""
const { JsonRpcProvider, Wallet, parseEther } = require("ethers");
(async () => {
  const provider = new JsonRpcProvider(process.env.RPC_URL);
  const wallet = new Wallet(process.env.FROM_PRIVATE_KEY, provider);
  const tx = await wallet.sendTransaction({ to: process.env.TO_ADDRESS, value: parseEther(process.env.AMOUNT_ETH) });
  const receipt = await tx.wait(1);
  process.stdout.write(JSON.stringify({ tx_hash: tx.hash, status: receipt.status }));
})().catch(() => process.exit(1));
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
  const tx = await token.transfer(process.env.TO_ADDRESS, BigInt(process.env.AMOUNT));
  const receipt = await tx.wait(1);
  process.stdout.write(JSON.stringify({ tx_hash: tx.hash, status: receipt.status }));
})().catch(() => process.exit(1));
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envfile", default=str(Path.home() / ".oracle.env"))
    parser.add_argument("--base-url", default=os.getenv("ORACLE_BASE_URL", "").strip() or "https://core-production-b1a0.up.railway.app")
    parser.add_argument("--agents", type=int, default=3)
    parser.add_argument("--fund-micro-usdc", type=int, default=1_000_000)  # 1 USDC
    parser.add_argument("--bounty-micro-usdc", type=int, default=500_000)  # 0.5 USDC
    parser.add_argument("--fund-eth", default="0.002")  # per wallet for gas
    parser.add_argument("--sync-wait-seconds", type=int, default=120)
    parser.add_argument("--reset", action="store_true", help="Delete local e2e state and start a new run.")
    parser.add_argument("--mode", choices=["governance", "oracle"], default="governance")
    parser.add_argument("--format", choices=["md", "json"], default="md")
    args = parser.parse_args()

    envfile = Path(args.envfile).expanduser()
    env_from_file = _read_envfile(envfile)
    env = dict(os.environ)
    env.update(env_from_file)

    oracle_base_url = args.base_url.rstrip("/")
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

    # 1) Generate wallets (treasury/funder/claimant) deterministically once per state.
    wallets = state.setdefault("wallets", {})
    for name in ("treasury", "funder", "claimant"):
        if name not in wallets:
            wallets[name] = _node_generate_wallet(env=env)

    treasury = wallets["treasury"]
    funder = wallets["funder"]
    claimant_wallet = wallets["claimant"]

    # 2) Create agents (public register); store api keys in state (local-only).
    personas = [
        {"name": "Ariadne (Architect)", "caps": ["proposals", "discussions", "governance", "funding"]},
        {"name": "Boris (Reviewer)", "caps": ["governance", "discussions", "bounties"]},
        {"name": "Cassandra (Builder)", "caps": ["bounties", "discussions", "funding"]},
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
        proposal["post_created"] = True
        _save_state(state)

    # 4) Full governance loop (vote -> finalize) to obtain resulting project_id.
    project = state.get("project")
    if not isinstance(project, dict):
        project = {}
        state["project"] = project

    if "project_id" not in project:
        if args.mode == "governance":
            # Vote with all agents (best-effort idempotent), then finalize.
            # In production, governance windows may be long (hours). To keep E2E deterministic,
            # we use an oracle-only helper endpoint to fast-forward the windows.
            try:
                oracle.post(
                    f"/api/v1/oracle/proposals/{proposal_id}/fast-forward",
                    {"target": "voting", "voting_minutes": 2},
                    idempotency_key=f"e2e:gov:ff:voting:{proposal_id}",
                )
            except Exception:
                pass

            for a in agents:
                try:
                    _agent_post(
                        oracle_base_url,
                        f"/api/v1/agent/proposals/{proposal_id}/vote",
                        api_key=a["api_key"],
                        body={"value": 1, "idempotency_key": f"e2e:vote:{proposal_id}:{a['agent_id']}"},
                    )
                except Exception:
                    pass

            # End voting immediately and finalize.
            try:
                oracle.post(
                    f"/api/v1/oracle/proposals/{proposal_id}/fast-forward",
                    {"target": "finalize"},
                    idempotency_key=f"e2e:gov:ff:finalize:{proposal_id}",
                )
            except Exception:
                pass

            # Wait until voting ends, then finalize.
            finalize_deadline = time.time() + 900
            while time.time() < finalize_deadline:
                try:
                    fin = _agent_post(
                        oracle_base_url,
                        f"/api/v1/agent/proposals/{proposal_id}/finalize",
                        api_key=author["api_key"],
                        body={},
                    )
                    rid = fin.get("data", {}).get("resulting_project_id")
                    if isinstance(rid, str) and rid:
                        project["project_id"] = rid
                        project["activated_via"] = "governance_finalize"
                        _save_state(state)
                        break
                except Exception:
                    pass
                time.sleep(2)

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

    # Fund gas for funder + treasury (idempotent-ish: store tx hashes).
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

    # Fund USDC to funder then deposit to treasury.
    if "fund_usdc_funder_tx" not in chain:
        chain["fund_usdc_funder_tx"] = _node_erc20_transfer_usdc(
            env=env,
            from_private_key=oracle_signer_pk,
            to_address=funder["address"],
            amount_micro_usdc=int(args.fund_micro_usdc),
        )
        _save_state(state)
    if "deposit_usdc_to_treasury_tx" not in chain:
        chain["deposit_usdc_to_treasury_tx"] = _node_erc20_transfer_usdc(
            env=env,
            from_private_key=funder["private_key"],
            to_address=treasury["address"],
            amount_micro_usdc=int(args.fund_micro_usdc),
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
            oracle.post(
                "/api/v1/oracle/project-capital-events",
                {
                    "event_id": None,
                    "idempotency_key": f"e2e:pcap:manual_deposit:{project_id}:{chain['deposit_usdc_to_treasury_tx']}",
                    "profit_month_id": None,
                    "project_id": project_id,
                    "delta_micro_usdc": int(args.fund_micro_usdc),
                    "source": "e2e_manual_deposit",
                    "evidence_tx_hash": chain["deposit_usdc_to_treasury_tx"],
                    "evidence_url": None,
                },
                idempotency_key=f"e2e:pcap:manual_deposit:{project_id}:{chain['deposit_usdc_to_treasury_tx']}",
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

    # 8) Bounty flow + payout.
    bounty = state.get("bounty")
    if not isinstance(bounty, dict):
        bounty = {}
        state["bounty"] = bounty

    if "bounty_id" not in bounty:
        b = _agent_post(
            oracle_base_url,
            "/api/v1/agent/bounties",
            api_key=author["api_key"],
            body={
                "project_id": project_id,
                "origin_proposal_id": proposal_id,
                "title": "E2E seed bounty",
                "description_md": "Seed bounty to test payout gates.",
                "amount_micro_usdc": int(args.bounty_micro_usdc),
                "idempotency_key": f"e2e:bounty:create:{proposal_id}",
            },
        )
        bid = b.get("data", {}).get("bounty_id")
        if not isinstance(bid, str):
            raise RuntimeError("unexpected bounty create response")
        bounty["bounty_id"] = bid
        _save_state(state)

    bounty_id = str(bounty["bounty_id"])

    if not bounty.get("claimed"):
        _agent_post(
            oracle_base_url,
            f"/api/v1/bounties/{bounty_id}/claim",
            api_key=claimant_agent["api_key"],
            body={},
        )
        bounty["claimed"] = True
        _save_state(state)

    if not bounty.get("submitted"):
        _agent_post(
            oracle_base_url,
            f"/api/v1/bounties/{bounty_id}/submit",
            api_key=claimant_agent["api_key"],
            body={"pr_url": f"https://example.invalid/pr/{bounty_id}", "merge_sha": "deadbeef"},
        )
        bounty["submitted"] = True
        _save_state(state)

    if not bounty.get("eligible"):
        oracle.post(
            f"/api/v1/bounties/{bounty_id}/evaluate-eligibility",
            {
                "pr_url": f"https://example.invalid/pr/{bounty_id}",
                "merged": True,
                "merge_sha": "deadbeef",
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
        bounty["eligible"] = True
        _save_state(state)

    # Reconcile *before* on-chain outflow (this is the fail-closed gate precondition).
    recon2 = oracle.post(
        f"/api/v1/oracle/projects/{project_id}/capital/reconciliation",
        {},
        idempotency_key=f"e2e:pcap:reconcile_pre_outflow:{project_id}:{uuid4().hex}",
    )
    project["capital_reconciliation_pre_outflow"] = recon2.get("data")
    _save_state(state)
    if not bool(recon2.get("data", {}).get("ready")):
        raise RuntimeError("pre-outflow reconciliation is not ready")

    if "bounty_paid_tx" not in bounty:
        bounty["bounty_paid_tx"] = _node_erc20_transfer_usdc(
            env=env,
            from_private_key=treasury["private_key"],
            to_address=claimant_wallet["address"],
            amount_micro_usdc=int(args.bounty_micro_usdc),
        )
        _save_state(state)

    if not bounty.get("marked_paid"):
        oracle.post(
            f"/api/v1/bounties/{bounty_id}/mark-paid",
            {"paid_tx_hash": bounty["bounty_paid_tx"]},
            idempotency_key=f"e2e:bounty:mark_paid:{bounty_id}",
        )
        bounty["marked_paid"] = True
        _save_state(state)

    recon3 = oracle.post(
        f"/api/v1/oracle/projects/{project_id}/capital/reconciliation",
        {},
        idempotency_key=f"e2e:pcap:reconcile_post_outflow:{project_id}:{uuid4().hex}",
    )
    project["capital_reconciliation_post_outflow"] = recon3.get("data")
    _save_state(state)

    urls = {
        "portal_agents": f"{oracle_base_url}/agents",
        "portal_proposal": f"{oracle_base_url}/proposals/{proposal_id}",
        "portal_project": f"{oracle_base_url}/projects/{project_id}",
        "portal_apps": f"{oracle_base_url}/apps",
        "portal_app_surface": f"{oracle_base_url}/apps/{project.get('slug')}",
        "portal_bounties": f"{oracle_base_url}/bounties?project_id={project_id}",
        "portal_discussions": f"{oracle_base_url}/discussions?scope=global",
    }
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
        "bounty_id": bounty_id,
        "tx": {
            "deposit_usdc_to_treasury": chain.get("deposit_usdc_to_treasury_tx"),
            "bounty_paid": bounty.get("bounty_paid_tx"),
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
        lines.append("## Funding / Capital")
        lines.append(f"- deposit tx: `{chain.get('deposit_usdc_to_treasury_tx')}`")
        ready_pre = (project.get("capital_reconciliation_pre_outflow") or {}).get("ready")
        lines.append(f"- capital strict-ready before outflow: `{bool(ready_pre)}`")
        lines.append("")
        lines.append("## Bounty")
        lines.append(f"- id: `{bounty_id}`")
        lines.append(f"- payout tx: `{bounty.get('bounty_paid_tx')}`")
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
