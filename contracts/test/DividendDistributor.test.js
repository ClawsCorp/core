const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("DividendDistributor", function () {
  let owner;
  let treasury;
  let founder;
  let staker1;
  let staker2;
  let author1;
  let author2;
  let usdc;
  let distributor;

  beforeEach(async function () {
    [
      owner,
      treasury,
      founder,
      staker1,
      staker2,
      author1,
      author2
    ] = await ethers.getSigners();

    const MockUSDC = await ethers.getContractFactory("MockUSDC");
    usdc = await MockUSDC.deploy();

    const Distributor = await ethers.getContractFactory("DividendDistributor");
    distributor = await Distributor.deploy(
      await usdc.getAddress(),
      treasury.address,
      founder.address
    );
  });

  it("splits USDC profit by basis points", async function () {
    const totalProfit = 10_000_000_000n;
    const profitMonthId = 202501;

    await usdc.mint(await distributor.getAddress(), totalProfit);
    await distributor.createDistribution(profitMonthId, totalProfit);

    await distributor.executeDistribution(
      profitMonthId,
      [staker1.address, staker2.address],
      [1, 1],
      [author1.address, author2.address],
      [1, 3]
    );

    const stakersAmount = (totalProfit * 6600n) / 10000n;
    const treasuryAmount = (totalProfit * 1900n) / 10000n;
    const authorsAmount = (totalProfit * 1000n) / 10000n;
    const founderAmount = (totalProfit * 500n) / 10000n;

    expect(await usdc.balanceOf(staker1.address)).to.equal(stakersAmount / 2n);
    expect(await usdc.balanceOf(staker2.address)).to.equal(stakersAmount / 2n);
    expect(await usdc.balanceOf(author1.address)).to.equal(authorsAmount / 4n);
    expect(await usdc.balanceOf(author2.address)).to.equal((authorsAmount * 3n) / 4n);
    expect(await usdc.balanceOf(founder.address)).to.equal(founderAmount);
    expect(await usdc.balanceOf(treasury.address)).to.equal(treasuryAmount);
  });

  it("routes dust from the split to treasury", async function () {
    const totalProfit = 1_000_003n;
    const profitMonthId = 202502;

    await usdc.mint(await distributor.getAddress(), totalProfit);
    await distributor.createDistribution(profitMonthId, totalProfit);

    await distributor.executeDistribution(
      profitMonthId,
      [staker1.address],
      [1],
      [author1.address],
      [1]
    );

    const stakersAmount = (totalProfit * 6600n) / 10000n;
    const treasuryAmount = (totalProfit * 1900n) / 10000n;
    const authorsAmount = (totalProfit * 1000n) / 10000n;
    const founderAmount = (totalProfit * 500n) / 10000n;
    const allocated = stakersAmount + treasuryAmount + authorsAmount + founderAmount;
    const dust = totalProfit - allocated;

    expect(await usdc.balanceOf(treasury.address)).to.equal(treasuryAmount + dust);
  });

  it("enforces caps for stakers and authors", async function () {
    const totalProfit = 1_000_000n;
    const profitMonthId = 202503;

    await usdc.mint(await distributor.getAddress(), totalProfit);
    await distributor.createDistribution(profitMonthId, totalProfit);

    const tooManyStakers = Array(201).fill(staker1.address);
    const stakerShares = Array(201).fill(1);

    await expect(
      distributor.executeDistribution(
        profitMonthId,
        tooManyStakers,
        stakerShares,
        [],
        []
      )
    ).to.be.revertedWith("Stakers cap exceeded");

    const tooManyAuthors = Array(51).fill(author1.address);
    const authorShares = Array(51).fill(1);

    await expect(
      distributor.executeDistribution(
        profitMonthId,
        [],
        [],
        tooManyAuthors,
        authorShares
      )
    ).to.be.revertedWith("Authors cap exceeded");
  });
});
