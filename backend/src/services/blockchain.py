from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.core.config import get_settings

logger = logging.getLogger(__name__)

_BALANCE_OF_SELECTOR = "70a08231"
_GET_DISTRIBUTION_SELECTOR = "3b345a87"


class BlockchainReadError(Exception):
    pass


class BlockchainConfigError(BlockchainReadError):
    pass


class BlockchainTxError(Exception):
    def __init__(self, message: str, *, error_hint: str | None = None):
        super().__init__(message)
        self.error_hint = error_hint


@dataclass(frozen=True)
class BalanceReadResult:
    balance_micro_usdc: int
    rpc_chain_id: int | None
    rpc_url_name: str


@dataclass(frozen=True)
class DistributionState:
    exists: bool
    total_profit_micro_usdc: int
    distributed: bool


@dataclass(frozen=True)
class TransactionReceiptResult:
    found: bool
    status: int | None
    block_number: int | None


def read_usdc_balance_of_distributor() -> BalanceReadResult:
    settings = get_settings()
    rpc_url = settings.base_sepolia_rpc_url
    usdc_address = settings.usdc_address
    distributor_address = settings.dividend_distributor_contract_address
    if _is_invalid_rpc_config(rpc_url, usdc_address, distributor_address):
        raise BlockchainConfigError(
            "Missing BASE_SEPOLIA_RPC_URL, USDC_ADDRESS, or DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS"
        )

    call_data = f"0x{_BALANCE_OF_SELECTOR}{_encode_address_arg(distributor_address)}"
    balance_hex = _rpc_call(
        rpc_url,
        "eth_call",
        [
            {
                "to": usdc_address,
                "data": call_data,
            },
            "latest",
        ],
    )
    if not isinstance(balance_hex, str) or not balance_hex.startswith("0x"):
        raise BlockchainReadError("Invalid eth_call response for balanceOf")

    try:
        balance = int(balance_hex, 16)
    except ValueError as exc:
        raise BlockchainReadError("Unable to parse eth_call balance response") from exc

    chain_id: int | None = None
    chain_hex = _rpc_call(rpc_url, "eth_chainId", [])
    if isinstance(chain_hex, str) and chain_hex.startswith("0x"):
        try:
            chain_id = int(chain_hex, 16)
        except ValueError:
            chain_id = None

    return BalanceReadResult(
        balance_micro_usdc=balance,
        rpc_chain_id=chain_id,
        rpc_url_name="base_sepolia",
    )


def read_distribution_state(profit_month_value: int) -> DistributionState:
    settings = get_settings()
    rpc_url = settings.base_sepolia_rpc_url
    distributor_address = settings.dividend_distributor_contract_address
    if _is_invalid_rpc_config(rpc_url, settings.usdc_address, distributor_address):
        raise BlockchainConfigError(
            "Missing BASE_SEPOLIA_RPC_URL, USDC_ADDRESS, or DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS"
        )

    data = f"0x{_GET_DISTRIBUTION_SELECTOR}{_encode_uint256_arg(profit_month_value)}"
    result = _rpc_call(
        rpc_url,
        "eth_call",
        [{"to": distributor_address, "data": data}, "latest"],
    )
    if not isinstance(result, str) or not result.startswith("0x"):
        raise BlockchainReadError("Invalid eth_call response for getDistribution")

    words = _decode_words(result)
    if len(words) < 3:
        raise BlockchainReadError("Invalid tuple response for getDistribution")

    return DistributionState(
        total_profit_micro_usdc=words[0],
        distributed=bool(words[1]),
        exists=bool(words[2]),
    )


def read_transaction_receipt(tx_hash: str) -> TransactionReceiptResult:
    settings = get_settings()
    rpc_url = settings.base_sepolia_rpc_url
    if rpc_url is None or _is_placeholder(rpc_url):
        raise BlockchainConfigError("Missing BASE_SEPOLIA_RPC_URL")

    receipt = _rpc_call(rpc_url, "eth_getTransactionReceipt", [tx_hash])
    if receipt is None:
        return TransactionReceiptResult(found=False, status=None, block_number=None)
    if not isinstance(receipt, dict):
        raise BlockchainReadError("Invalid eth_getTransactionReceipt response")

    status_hex = receipt.get("status")
    block_number_hex = receipt.get("blockNumber")
    if not isinstance(status_hex, str) or not status_hex.startswith("0x"):
        raise BlockchainReadError("Invalid receipt status")

    try:
        status = int(status_hex, 16)
    except ValueError as exc:
        raise BlockchainReadError("Unable to parse receipt status") from exc

    block_number: int | None = None
    if isinstance(block_number_hex, str) and block_number_hex.startswith("0x"):
        try:
            block_number = int(block_number_hex, 16)
        except ValueError:
            block_number = None

    return TransactionReceiptResult(found=True, status=status, block_number=block_number)


def submit_create_distribution_tx(profit_month_value: int, total_profit_micro_usdc: int) -> str:
    settings = get_settings()
    rpc_url = settings.base_sepolia_rpc_url
    distributor_address = settings.dividend_distributor_contract_address
    signer_private_key = settings.oracle_signer_private_key

    if _is_invalid_rpc_config(rpc_url, settings.usdc_address, distributor_address):
        raise BlockchainConfigError(
            "Missing BASE_SEPOLIA_RPC_URL, USDC_ADDRESS, or DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS"
        )
    if signer_private_key is None or _is_placeholder(signer_private_key):
        raise BlockchainConfigError("Missing ORACLE_SIGNER_PRIVATE_KEY")

    node_script = """
const { JsonRpcProvider, Wallet, Contract } = require('ethers');
(async () => {
  const rpcUrl = process.env.RPC_URL;
  const privateKey = process.env.PRIVATE_KEY;
  const contractAddress = process.env.CONTRACT_ADDRESS;
  const profitMonthId = BigInt(process.env.PROFIT_MONTH_ID);
  const totalProfit = BigInt(process.env.TOTAL_PROFIT);
  const provider = new JsonRpcProvider(rpcUrl);
  const wallet = new Wallet(privateKey, provider);
  const contract = new Contract(contractAddress, [
    'function createDistribution(uint256 profitMonthId, uint256 totalProfit) external'
  ], wallet);
  const tx = await contract.createDistribution(profitMonthId, totalProfit);
  process.stdout.write(JSON.stringify({ tx_hash: tx.hash }));
})().catch((err) => {
  const message = err && err.message ? err.message : String(err);
  process.stderr.write(message);
  process.exit(1);
});
"""

    env = os.environ.copy()
    env.update({
        "RPC_URL": rpc_url,
        "PRIVATE_KEY": signer_private_key,
        "CONTRACT_ADDRESS": distributor_address,
        "PROFIT_MONTH_ID": str(profit_month_value),
        "TOTAL_PROFIT": str(total_profit_micro_usdc),
    })

    contracts_dir = settings.contracts_dir

    try:
        proc = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=contracts_dir,
            timeout=45,
        )
    except subprocess.CalledProcessError as exc:
        error_hint = _sanitize_subprocess_error(stdout=exc.stdout, stderr=exc.stderr)
        logger.warning("createDistribution submission failed hint=%s", error_hint)
        raise BlockchainTxError("Failed to submit createDistribution transaction", error_hint=error_hint) from exc
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        error_hint = _sanitize_subprocess_error(stderr=str(exc))
        logger.warning("createDistribution submission failed hint=%s", error_hint)
        raise BlockchainTxError("Failed to submit createDistribution transaction", error_hint=error_hint) from exc

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BlockchainTxError("Unable to parse transaction response") from exc

    tx_hash = payload.get("tx_hash")
    if not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
        raise BlockchainTxError("Missing transaction hash")
    return tx_hash


def submit_execute_distribution_tx(
    profit_month_value: int,
    stakers: list[str],
    staker_shares: list[int],
    authors: list[str],
    author_shares: list[int],
) -> str:
    settings = get_settings()
    rpc_url = settings.base_sepolia_rpc_url
    distributor_address = settings.dividend_distributor_contract_address
    signer_private_key = settings.oracle_signer_private_key

    if _is_invalid_rpc_config(rpc_url, settings.usdc_address, distributor_address):
        raise BlockchainConfigError(
            "Missing BASE_SEPOLIA_RPC_URL, USDC_ADDRESS, or DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS"
        )
    if signer_private_key is None or _is_placeholder(signer_private_key):
        raise BlockchainConfigError("Missing ORACLE_SIGNER_PRIVATE_KEY")

    node_script = """
const { JsonRpcProvider, Wallet, Contract } = require('ethers');
(async () => {
  const rpcUrl = process.env.RPC_URL;
  const privateKey = process.env.PRIVATE_KEY;
  const contractAddress = process.env.CONTRACT_ADDRESS;
  const profitMonthId = BigInt(process.env.PROFIT_MONTH_ID);
  const stakers = JSON.parse(process.env.STAKERS_JSON || '[]');
  const stakerSharesRaw = JSON.parse(process.env.STAKER_SHARES_JSON || '[]');
  const authors = JSON.parse(process.env.AUTHORS_JSON || '[]');
  const authorSharesRaw = JSON.parse(process.env.AUTHOR_SHARES_JSON || '[]');
  const stakerShares = stakerSharesRaw.map((v) => BigInt(v));
  const authorShares = authorSharesRaw.map((v) => BigInt(v));
  const provider = new JsonRpcProvider(rpcUrl);
  const wallet = new Wallet(privateKey, provider);
  const contract = new Contract(contractAddress, [
    'function executeDistribution(uint256,address[],uint256[],address[],uint256[]) external'
  ], wallet);
  const tx = await contract.executeDistribution(profitMonthId, stakers, stakerShares, authors, authorShares);
  process.stdout.write(JSON.stringify({ tx_hash: tx.hash }));
})().catch((err) => {
  const message = err && err.message ? err.message : String(err);
  process.stderr.write(message);
  process.exit(1);
});
"""

    env = os.environ.copy()
    env.update(
        {
            "RPC_URL": rpc_url,
            "PRIVATE_KEY": signer_private_key,
            "CONTRACT_ADDRESS": distributor_address,
            "PROFIT_MONTH_ID": str(profit_month_value),
            "STAKERS_JSON": json.dumps(stakers),
            "STAKER_SHARES_JSON": json.dumps(staker_shares),
            "AUTHORS_JSON": json.dumps(authors),
            "AUTHOR_SHARES_JSON": json.dumps(author_shares),
        }
    )

    contracts_dir = settings.contracts_dir

    try:
        proc = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=contracts_dir,
            timeout=45,
        )
    except subprocess.CalledProcessError as exc:
        error_hint = _sanitize_subprocess_error(stdout=exc.stdout, stderr=exc.stderr)
        logger.warning("executeDistribution submission failed hint=%s", error_hint)
        raise BlockchainTxError("Failed to submit executeDistribution transaction", error_hint=error_hint) from exc
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        error_hint = _sanitize_subprocess_error(stderr=str(exc))
        logger.warning("executeDistribution submission failed hint=%s", error_hint)
        raise BlockchainTxError("Failed to submit executeDistribution transaction", error_hint=error_hint) from exc

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BlockchainTxError("Unable to parse transaction response") from exc

    tx_hash = payload.get("tx_hash")
    if not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
        raise BlockchainTxError("Missing transaction hash")
    return tx_hash



def _sanitize_subprocess_error(*, stdout: str | None = None, stderr: str | None = None) -> str:
    combined = " ".join(part for part in [stderr, stdout] if part).strip()
    if not combined:
        return "unknown_subprocess_error"

    redacted = combined
    secret_patterns = [
        r"0x[a-fA-F0-9]{64}",
        r"(?i)(private[_-]?key|hmac|secret|authorization)\s*[:=]\s*[^\s,;]+",
    ]
    for pattern in secret_patterns:
        redacted = re.sub(pattern, "[redacted]", redacted)

    lowered = redacted.lower()
    if "cannot find module" in lowered and "ethers" in lowered:
        return "module_not_found_ethers"
    if "node" in lowered and "not found" in lowered:
        return "node_runtime_not_found"
    if "invalid private key" in lowered:
        return "invalid_private_key"
    if "insufficient funds" in lowered:
        return "insufficient_funds"
    if "nonce" in lowered and "low" in lowered:
        return "nonce_too_low"
    if "execution reverted" in lowered or "revert" in lowered:
        return "reverted"
    if "rpc" in lowered or "network" in lowered:
        return "rpc_error"

    return "unknown"

def _rpc_call(rpc_url: str, method: str, params: list[object]) -> object:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(
        "utf-8"
    )
    request = Request(rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise BlockchainReadError(f"RPC request failed for method={method}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BlockchainReadError("RPC response is not valid JSON") from exc

    if parsed.get("error") is not None:
        raise BlockchainReadError(f"RPC error for method={method}")

    return parsed.get("result")


def _encode_address_arg(address: str) -> str:
    cleaned = address.lower()
    if not cleaned.startswith("0x"):
        raise BlockchainReadError("Address must be 0x-prefixed")
    raw = cleaned[2:]
    if len(raw) != 40:
        raise BlockchainReadError("Address must be 20 bytes")
    try:
        int(raw, 16)
    except ValueError as exc:
        raise BlockchainReadError("Address must be hex") from exc
    return raw.rjust(64, "0")


def _encode_uint256_arg(value: int) -> str:
    if value < 0:
        raise BlockchainReadError("uint256 value must be non-negative")
    return f"{value:064x}"


def _decode_words(data: str) -> list[int]:
    payload = data[2:]
    if len(payload) % 64 != 0:
        raise BlockchainReadError("Invalid ABI response length")
    words: list[int] = []
    for idx in range(0, len(payload), 64):
        chunk = payload[idx : idx + 64]
        try:
            words.append(int(chunk, 16))
        except ValueError as exc:
            raise BlockchainReadError("Invalid ABI response chunk") from exc
    return words


def _is_invalid_rpc_config(
    rpc_url: str | None, usdc_address: str | None, distributor_address: str | None
) -> bool:
    return any(
        value is None or _is_placeholder(value)
        for value in (rpc_url, usdc_address, distributor_address)
    )


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return True
    if "<" in normalized or ">" in normalized:
        return True
    return "your" in normalized or "placeholder" in normalized
