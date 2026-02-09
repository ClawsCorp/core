const { expect } = require("chai");
const { ethers } = require("hardhat");

const BASIS_POINTS = 10_000n;
const STAKERS_BPS = 6_600n;
const TREASURY_BPS = 1_900n;
const AUTHORS_BPS = 1_000n;
const FOUNDER_BPS = 500n;

const calculateSplit = (totalProfit) => {
  const stakersAmount = (totalProfit * STAKERS_BPS) / BASIS_POINTS;
  const treasuryAmount = (totalProfit * TREASURY_BPS) / BASIS_POINTS;
  const authorsAmount = (totalProfit * AUTHORS_BPS) / BASIS_POINTS;
  const founderAmount = (totalProfit * FOUNDER_BPS) / BASIS_POINTS;
  const splitTotal = stakersAmount + treasuryAmount + authorsAmount + founderAmount;
  const dust = totalProfit - splitTotal;

  return {
    stakersAmount,
    treasuryAmount: treasuryAmount + dust,
    authorsAmount,
    founderAmount
  };
};

describe("DividendDistributor", function () {
  let distributor;
  let usdc;
  let treasury;
  let founder;
  let staker1;
  let staker2;
  let author1;
  let author2;

  beforeEach(async function () {
    const signers = await ethers.getSigners();
    [, treasury, founder, staker1, staker2, author1, author2] = signers;

    const MockUSDC = await ethers.getContractFactory("MockUSDC");
    usdc = await MockUSDC.deploy();

    const DividendDistributor = await ethers.getContractFactory("DividendDistributor");
    distributor = await DividendDistributor.deploy(
      await usdc.getAddress(),
      treasury.address,
      founder.address
    );
  });

  it("splits total profit in USDC units", async function () {
    const totalProfit = 10_000_000_000n;
    const monthId = 202401;

    await distributor.createDistribution(monthId, totalProfit);
    await usdc.mint(await distributor.getAddress(), totalProfit);

    await distributor.executeDistribution(
      monthId,
      [staker1.address, staker2.address],
      [1, 3],
      [author1.address, author2.address],
      [2, 1]
    );

    const { stakersAmount, treasuryAmount, authorsAmount, founderAmount } =
      calculateSplit(totalProfit);

    const staker1Expected = (stakersAmount * 1n) / 4n;
    const staker2Expected = stakersAmount - staker1Expected;
    const author1Expected = (authorsAmount * 2n) / 3n;
    const author2Expected = authorsAmount - author1Expected;

    expect(await usdc.balanceOf(staker1.address)).to.equal(staker1Expected);
    expect(await usdc.balanceOf(staker2.address)).to.equal(staker2Expected);
    expect(await usdc.balanceOf(author1.address)).to.equal(author1Expected);
    expect(await usdc.balanceOf(author2.address)).to.equal(author2Expected);
    expect(await usdc.balanceOf(treasury.address)).to.equal(treasuryAmount);
    expect(await usdc.balanceOf(founder.address)).to.equal(founderAmount);
  });

  it("sends split dust to treasury", async function () {
    const totalProfit = 10_000_000_001n;
    const monthId = 202402;

    await distributor.createDistribution(monthId, totalProfit);
    await usdc.mint(await distributor.getAddress(), totalProfit);

    await distributor.executeDistribution(
      monthId,
      [staker1.address],
      [1],
      [author1.address],
      [1]
    );

    const { treasuryAmount } = calculateSplit(totalProfit);

    expect(await usdc.balanceOf(treasury.address)).to.equal(treasuryAmount);
  });

  it("reverts when staker cap exceeded", async function () {
    const totalProfit = 1_000_000n;
    const monthId = 202403;

    const stakers = Array.from({ length: 201 }, () => ethers.Wallet.createRandom().address);
    const shares = Array.from({ length: 201 }, () => 1);

    await distributor.createDistribution(monthId, totalProfit);
    await usdc.mint(await distributor.getAddress(), totalProfit);

    await expect(
      distributor.executeDistribution(monthId, stakers, shares, [], [])
    ).to.be.revertedWith("StakersCapExceeded");
  });

  it("reverts when author cap exceeded", async function () {
    const totalProfit = 1_000_000n;
    const monthId = 202404;

    const authors = Array.from({ length: 51 }, () => ethers.Wallet.createRandom().address);
    const shares = Array.from({ length: 51 }, () => 1);

    await distributor.createDistribution(monthId, totalProfit);
    await usdc.mint(await distributor.getAddress(), totalProfit);

    await expect(
      distributor.executeDistribution(monthId, [], [], authors, shares)
    ).to.be.revertedWith("AuthorsCapExceeded");
  });

  it("moves staker and author allocations to treasury when empty", async function () {
    const totalProfit = 5_000_000n;
    const monthId = 202405;

    await distributor.createDistribution(monthId, totalProfit);
    await usdc.mint(await distributor.getAddress(), totalProfit);

    await distributor.executeDistribution(monthId, [], [], [], []);

    const { treasuryAmount, stakersAmount, authorsAmount } = calculateSplit(totalProfit);
    const expectedTreasury = treasuryAmount + stakersAmount + authorsAmount;

    expect(await usdc.balanceOf(treasury.address)).to.equal(expectedTreasury);
  });
});
