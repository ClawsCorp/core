# Deployment

## Contracts

Set the following environment variables before deploying:

- `USDC_ADDRESS`
- `TREASURY_WALLET_ADDRESS`
- `FOUNDER_WALLET_ADDRESS`

Deploy with Hardhat:

```bash
npm --prefix contracts install
npx --prefix contracts hardhat compile
npx --prefix contracts hardhat run scripts/deploy-dividend-distributor.js --network <network>
```
