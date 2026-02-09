// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract DividendDistributor {
    using SafeERC20 for IERC20;

    uint256 public constant MAX_STAKERS = 200;
    uint256 public constant MAX_AUTHORS = 50;

    uint256 public constant BASIS_POINTS = 10_000;
    uint256 public constant STAKERS_BPS = 6_600;
    uint256 public constant TREASURY_BPS = 1_900;
    uint256 public constant AUTHORS_BPS = 1_000;
    uint256 public constant FOUNDER_BPS = 500;

    struct Distribution {
        uint256 totalProfit;
        bool created;
        bool distributed;
    }

    IERC20 public immutable usdc;
    address public immutable treasuryWallet;
    address public immutable founderWallet;

    mapping(uint256 => Distribution) public distributions;

    constructor(address usdcAddress, address treasuryWalletAddress, address founderWalletAddress) {
        require(usdcAddress != address(0), "USDCZeroAddress");
        require(treasuryWalletAddress != address(0), "TreasuryZeroAddress");
        require(founderWalletAddress != address(0), "FounderZeroAddress");

        usdc = IERC20(usdcAddress);
        treasuryWallet = treasuryWalletAddress;
        founderWallet = founderWalletAddress;
    }

    function createDistribution(uint256 profitMonthId, uint256 totalProfit) external {
        Distribution storage distribution = distributions[profitMonthId];
        require(!distribution.created, "DistributionExists");

        distribution.totalProfit = totalProfit;
        distribution.created = true;
    }

    function executeDistribution(
        uint256 profitMonthId,
        address[] calldata stakers,
        uint256[] calldata stakerShares,
        address[] calldata authors,
        uint256[] calldata authorShares
    ) external {
        require(stakers.length <= MAX_STAKERS, "StakersCapExceeded");
        require(authors.length <= MAX_AUTHORS, "AuthorsCapExceeded");
        require(stakers.length == stakerShares.length, "StakerSharesMismatch");
        require(authors.length == authorShares.length, "AuthorSharesMismatch");

        Distribution storage distribution = distributions[profitMonthId];
        require(distribution.created, "DistributionMissing");
        require(!distribution.distributed, "DistributionAlreadyExecuted");

        uint256 totalProfit = distribution.totalProfit;
        require(usdc.balanceOf(address(this)) >= totalProfit, "InsufficientUSDC");

        uint256 stakersAmount = (totalProfit * STAKERS_BPS) / BASIS_POINTS;
        uint256 treasuryAmount = (totalProfit * TREASURY_BPS) / BASIS_POINTS;
        uint256 authorsAmount = (totalProfit * AUTHORS_BPS) / BASIS_POINTS;
        uint256 founderAmount = (totalProfit * FOUNDER_BPS) / BASIS_POINTS;
        uint256 splitTotal = stakersAmount + treasuryAmount + authorsAmount + founderAmount;
        uint256 splitDust = totalProfit - splitTotal;
        treasuryAmount += splitDust;

        if (stakers.length == 0) {
            treasuryAmount += stakersAmount;
            stakersAmount = 0;
        }

        if (authors.length == 0) {
            treasuryAmount += authorsAmount;
            authorsAmount = 0;
        }

        distribution.distributed = true;

        if (treasuryAmount > 0) {
            usdc.safeTransfer(treasuryWallet, treasuryAmount);
        }
        if (founderAmount > 0) {
            usdc.safeTransfer(founderWallet, founderAmount);
        }

        if (stakersAmount > 0) {
            _distributeByShares(stakers, stakerShares, stakersAmount);
        }

        if (authorsAmount > 0) {
            _distributeByShares(authors, authorShares, authorsAmount);
        }
    }

    function _distributeByShares(
        address[] calldata recipients,
        uint256[] calldata shares,
        uint256 totalAmount
    ) private {
        uint256 totalShares = 0;
        for (uint256 i = 0; i < shares.length; i++) {
            totalShares += shares[i];
        }
        require(totalShares > 0, "SharesZero");

        uint256 remaining = totalAmount;
        uint256 lastIndex = recipients.length - 1;
        for (uint256 i = 0; i < recipients.length; i++) {
            uint256 payout;
            if (i == lastIndex) {
                payout = remaining;
            } else {
                payout = (totalAmount * shares[i]) / totalShares;
                remaining -= payout;
            }
            if (payout > 0) {
                usdc.safeTransfer(recipients[i], payout);
            }
        }
    }
}
