/* eslint-disable no-console */

async function main() {
  const { ethers } = require("hardhat");

  const ownersRaw = (process.env.SAFE_OWNER_ADDRESSES || "").trim();
  const thresholdRaw = (process.env.SAFE_THRESHOLD || "").trim() || "2";
  const singleton = (process.env.SAFE_SINGLETON_ADDRESS || "").trim();
  const proxyFactoryAddress = (process.env.SAFE_PROXY_FACTORY_ADDRESS || "").trim();
  const fallbackHandler = (process.env.SAFE_FALLBACK_HANDLER_ADDRESS || "").trim();
  const saltNonceRaw = (process.env.SAFE_SALT_NONCE || "").trim() || `${Date.now()}`;

  if (!ownersRaw) {
    throw new Error("Missing SAFE_OWNER_ADDRESSES (comma-separated 3 owner addresses).");
  }
  const owners = ownersRaw
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (owners.length !== 3) {
    throw new Error("SAFE_OWNER_ADDRESSES must contain exactly 3 addresses.");
  }
  const uniqueOwners = new Set(owners.map((value) => value.toLowerCase()));
  if (uniqueOwners.size !== owners.length) {
    throw new Error("SAFE_OWNER_ADDRESSES contains duplicate addresses.");
  }
  const threshold = Number(thresholdRaw);
  if (!Number.isInteger(threshold) || threshold < 1 || threshold > owners.length) {
    throw new Error("SAFE_THRESHOLD must be an integer between 1 and owners.length.");
  }
  if (!singleton || !singleton.startsWith("0x")) {
    throw new Error("Missing SAFE_SINGLETON_ADDRESS.");
  }
  if (!proxyFactoryAddress || !proxyFactoryAddress.startsWith("0x")) {
    throw new Error("Missing SAFE_PROXY_FACTORY_ADDRESS.");
  }
  if (!fallbackHandler || !fallbackHandler.startsWith("0x")) {
    throw new Error("Missing SAFE_FALLBACK_HANDLER_ADDRESS.");
  }

  const [deployer] = await ethers.getSigners();
  if (!deployer) {
    throw new Error("No deployer signer available.");
  }

  const safeAbi = [
    "function setup(address[] calldata owners,uint256 threshold,address to,bytes data,address fallbackHandler,address paymentToken,uint256 payment,address paymentReceiver) external",
  ];
  const proxyFactoryAbi = [
    "event ProxyCreation(address proxy, address singleton)",
    "function createProxyWithNonce(address singleton, bytes initializer, uint256 saltNonce) external returns (address proxy)",
  ];

  const safeInterface = new ethers.Interface(safeAbi);
  const factory = new ethers.Contract(proxyFactoryAddress, proxyFactoryAbi, deployer);

  const initializer = safeInterface.encodeFunctionData("setup", [
    owners,
    threshold,
    ethers.ZeroAddress,
    "0x",
    fallbackHandler,
    ethers.ZeroAddress,
    0,
    ethers.ZeroAddress,
  ]);

  const saltNonce = BigInt(saltNonceRaw);
  let safeAddress = "";
  try {
    safeAddress = await factory.createProxyWithNonce.staticCall(singleton, initializer, saltNonce);
  } catch (_err) {
    // Fallback to receipt parsing below if static simulation is unavailable on the RPC.
  }
  const tx = await factory.createProxyWithNonce(singleton, initializer, saltNonce);
  const receipt = await tx.wait();

  if (!safeAddress) {
    for (const log of receipt.logs || []) {
      try {
        const parsed = factory.interface.parseLog(log);
        if (parsed && parsed.name === "ProxyCreation") {
          safeAddress = parsed.args.proxy;
          break;
        }
      } catch (_err) {
        // ignore unrelated logs
      }
    }
  }
  if (!safeAddress || !safeAddress.startsWith("0x")) {
    throw new Error("Failed to extract Safe proxy address from ProxyCreation event.");
  }

  console.log(`deployer=${await deployer.getAddress()}`);
  console.log(`safe_address=${safeAddress}`);
  console.log(`threshold=${threshold}`);
  console.log(`owners=${owners.join(",")}`);
  console.log(`tx_hash=${tx.hash}`);
  console.log(`singleton=${singleton}`);
  console.log(`proxy_factory=${proxyFactoryAddress}`);
  console.log(`fallback_handler=${fallbackHandler}`);
  console.log(`salt_nonce=${saltNonce.toString()}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
