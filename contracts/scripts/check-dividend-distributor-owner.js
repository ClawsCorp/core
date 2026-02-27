/* eslint-disable no-console */

async function main() {
  const { ethers } = require("hardhat");

  const contractAddress =
    (process.env.DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS || "").trim() || process.argv[2];
  const expectedOwner = (process.env.SAFE_OWNER_ADDRESS || "").trim() || process.argv[3] || "";

  if (!contractAddress || !contractAddress.startsWith("0x")) {
    throw new Error(
      "Missing contract address. Set DIVIDEND_DISTRIBUTOR_CONTRACT_ADDRESS or pass as argv[2]."
    );
  }

  const distributor = await ethers.getContractAt("DividendDistributor", contractAddress);
  const owner = await distributor.owner();

  console.log(`contract=${contractAddress}`);
  console.log(`owner=${owner}`);
  if (expectedOwner) {
    console.log(`expected_owner=${expectedOwner}`);
    console.log(`matches_expected_owner=${owner.toLowerCase() === expectedOwner.toLowerCase()}`);
  } else {
    console.log("expected_owner=");
    console.log("matches_expected_owner=unknown");
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
