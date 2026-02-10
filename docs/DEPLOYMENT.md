# Deployment

## Contracts

From the repository root, deploy the `DividendDistributor` with environment variables set for the target network:

```bash
export USDC_ADDRESS=0x...
export TREASURY_WALLET_ADDRESS=0x...
export FOUNDER_WALLET_ADDRESS=0x...

npx --prefix contracts hardhat run scripts/deploy-dividend-distributor.js --network <network>
```

Deploy the `FundingPool` with the USDC address for the target network:

```bash
export USDC_ADDRESS=0x...

npx --prefix contracts hardhat run scripts/deploy-funding-pool.js --network <network>
```
