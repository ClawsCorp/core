const hre = require("hardhat");

async function main() {
  const usdcAddress = process.env.USDC_ADDRESS;

  if (!usdcAddress) {
    throw new Error("Missing env vars: USDC_ADDRESS");
  }

  const FundingPool = await hre.ethers.getContractFactory("FundingPool");
  const pool = await FundingPool.deploy(usdcAddress);

  await pool.waitForDeployment();
  console.log("FundingPool deployed to:", await pool.getAddress());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
