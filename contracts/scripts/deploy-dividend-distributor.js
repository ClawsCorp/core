const hre = require("hardhat");

async function main() {
  const usdcAddress = process.env.USDC_ADDRESS;
  const treasuryWallet = process.env.TREASURY_WALLET_ADDRESS;
  const founderWallet = process.env.FOUNDER_WALLET_ADDRESS;

  if (!usdcAddress || !treasuryWallet || !founderWallet) {
    throw new Error(
      "Missing env vars: USDC_ADDRESS, TREASURY_WALLET_ADDRESS, FOUNDER_WALLET_ADDRESS"
    );
  }

  const Distributor = await hre.ethers.getContractFactory("DividendDistributor");
  const distributor = await Distributor.deploy(
    usdcAddress,
    treasuryWallet,
    founderWallet
  );

  await distributor.waitForDeployment();
  console.log("DividendDistributor deployed to:", await distributor.getAddress());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
