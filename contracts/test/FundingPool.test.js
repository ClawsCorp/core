const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("FundingPool", function () {
  let owner;
  let staker;
  let other;
  let usdc;
  let pool;
  let projectKey;

  beforeEach(async function () {
    [owner, staker, other] = await ethers.getSigners();

    const MockUSDC = await ethers.getContractFactory("MockUSDC");
    usdc = await MockUSDC.deploy();

    const FundingPool = await ethers.getContractFactory("FundingPool");
    pool = await FundingPool.deploy(await usdc.getAddress());

    projectKey = ethers.id("project-alpha");
  });

  it("stakes USDC and tracks totals", async function () {
    const amount = 5_000_000n;

    await usdc.mint(staker.address, amount);
    await usdc.connect(staker).approve(await pool.getAddress(), amount);

    await expect(pool.connect(staker).stake(projectKey, amount))
      .to.emit(pool, "Staked")
      .withArgs(staker.address, projectKey, amount);

    expect(await pool.stakeOf(projectKey, staker.address)).to.equal(amount);
    expect(await pool.totalStake(projectKey)).to.equal(amount);
    expect(await usdc.balanceOf(staker.address)).to.equal(0n);
    expect(await usdc.balanceOf(await pool.getAddress())).to.equal(amount);
  });

  it("unstakes USDC and updates balances", async function () {
    const amount = 7_500_000n;
    const unstakeAmount = 2_000_000n;

    await usdc.mint(staker.address, amount);
    await usdc.connect(staker).approve(await pool.getAddress(), amount);

    await pool.connect(staker).stake(projectKey, amount);

    await expect(pool.connect(staker).unstake(projectKey, unstakeAmount))
      .to.emit(pool, "Unstaked")
      .withArgs(staker.address, projectKey, unstakeAmount);

    expect(await pool.stakeOf(projectKey, staker.address)).to.equal(
      amount - unstakeAmount
    );
    expect(await pool.totalStake(projectKey)).to.equal(amount - unstakeAmount);
    expect(await usdc.balanceOf(staker.address)).to.equal(unstakeAmount);
    expect(await usdc.balanceOf(await pool.getAddress())).to.equal(
      amount - unstakeAmount
    );
  });

  it("rejects zero stake", async function () {
    await expect(pool.connect(staker).stake(projectKey, 0)).to.be.revertedWith(
      "Amount required"
    );
  });

  it("rejects zero unstake", async function () {
    await expect(
      pool.connect(staker).unstake(projectKey, 0)
    ).to.be.revertedWith("Amount required");
  });

  it("rejects unstake larger than balance", async function () {
    const amount = 1_000_000n;

    await usdc.mint(staker.address, amount);
    await usdc.connect(staker).approve(await pool.getAddress(), amount);
    await pool.connect(staker).stake(projectKey, amount);

    await expect(
      pool.connect(staker).unstake(projectKey, amount + 1n)
    ).to.be.revertedWith("Insufficient stake");
  });

  it("tracks separate stakes per user", async function () {
    const stakerAmount = 3_000_000n;
    const otherAmount = 4_000_000n;

    await usdc.mint(staker.address, stakerAmount);
    await usdc.mint(other.address, otherAmount);

    await usdc.connect(staker).approve(await pool.getAddress(), stakerAmount);
    await usdc.connect(other).approve(await pool.getAddress(), otherAmount);

    await pool.connect(staker).stake(projectKey, stakerAmount);
    await pool.connect(other).stake(projectKey, otherAmount);

    expect(await pool.stakeOf(projectKey, staker.address)).to.equal(
      stakerAmount
    );
    expect(await pool.stakeOf(projectKey, other.address)).to.equal(otherAmount);
    expect(await pool.totalStake(projectKey)).to.equal(
      stakerAmount + otherAmount
    );
  });
});
