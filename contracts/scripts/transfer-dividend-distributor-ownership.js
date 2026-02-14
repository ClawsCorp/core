/* eslint-disable no-console */

async function main() {
  const { ethers } = require("hardhat");

  const contractAddress =
    (process.env.DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS || "").trim() || process.argv[2];
  const newOwner = (process.env.SAFE_OWNER_ADDRESS || "").trim() || process.argv[3];

  if (!contractAddress || !contractAddress.startsWith("0x")) {
    throw new Error(
      "Missing contract address. Set DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS or pass as argv[2]."
    );
  }
  if (!newOwner || !newOwner.startsWith("0x")) {
    throw new Error("Missing new owner. Set SAFE_OWNER_ADDRESS or pass as argv[3].");
  }

  const [signer] = await ethers.getSigners();
  if (!signer) {
    throw new Error("No signer available. Configure a funded private key for the selected network.");
  }

  const distributor = await ethers.getContractAt("DividendDistributor", contractAddress, signer);

  const currentOwner = await distributor.owner();
  console.log(`contract=${contractAddress}`);
  console.log(`signer=${await signer.getAddress()}`);
  console.log(`owner_before=${currentOwner}`);
  console.log(`new_owner=${newOwner}`);

  if (currentOwner.toLowerCase() === newOwner.toLowerCase()) {
    console.log("noop: already owned by new_owner");
    return;
  }

  const tx = await distributor.transferOwnership(newOwner);
  console.log(`tx_hash=${tx.hash}`);
  await tx.wait();

  const ownerAfter = await distributor.owner();
  console.log(`owner_after=${ownerAfter}`);
  if (ownerAfter.toLowerCase() !== newOwner.toLowerCase()) {
    throw new Error("Ownership transfer did not take effect.");
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});

