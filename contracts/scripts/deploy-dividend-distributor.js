const hre = require("hardhat");

async function main() {
  const { USDC_ADDRESS, TREASURY_WALLET_ADDRESS, FOUNDER_WALLET_ADDRESS } =
    process.env;

  if (!USDC_ADDRESS || !TREASURY_WALLET_ADDRESS || !FOUNDER_WALLET_ADDRESS) {
    throw new Error(
      "Missing required env vars: USDC_ADDRESS, TREASURY_WALLET_ADDRESS, FOUNDER_WALLET_ADDRESS"
    );
  }

  const DividendDistributor = await hre.ethers.getContractFactory(
    "DividendDistributor"
  );
  const distributor = await DividendDistributor.deploy(
    USDC_ADDRESS,
    TREASURY_WALLET_ADDRESS,
    FOUNDER_WALLET_ADDRESS
  );

  await distributor.waitForDeployment();

  console.log("DividendDistributor deployed to:", await distributor.getAddress());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
