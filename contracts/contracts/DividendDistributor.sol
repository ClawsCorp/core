// SPDX-License-Identifier: BSL-1.1
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

contract DividendDistributor is Ownable {
    using SafeERC20 for IERC20;

    uint256 public constant MAX_STAKERS = 200;
    uint256 public constant MAX_AUTHORS = 50;

    uint256 public constant STAKERS_BPS = 6600;
    uint256 public constant TREASURY_BPS = 1900;
    uint256 public constant AUTHORS_BPS = 1000;
    uint256 public constant FOUNDER_BPS = 500;
    uint256 public constant BPS_DENOMINATOR = 10000;

    IERC20 public immutable usdc;
    address public immutable treasuryWallet;
    address public immutable founderWallet;

    struct Distribution {
        uint256 totalProfit;
        bool distributed;
        bool exists;
    }

    mapping(uint256 => Distribution) private distributions;

    event DistributionCreated(uint256 indexed profitMonthId, uint256 totalProfit);
    event DistributionExecuted(uint256 indexed profitMonthId, uint256 totalProfit);

    constructor(
        address usdcAddress,
        address treasuryWalletAddress,
        address founderWalletAddress
    ) Ownable(msg.sender) {
        require(usdcAddress != address(0), "USDC address required");
        require(treasuryWalletAddress != address(0), "Treasury address required");
        require(founderWalletAddress != address(0), "Founder address required");
        usdc = IERC20(usdcAddress);
        treasuryWallet = treasuryWalletAddress;
        founderWallet = founderWalletAddress;
    }

    function createDistribution(uint256 profitMonthId, uint256 totalProfit) external onlyOwner {
        Distribution storage distribution = distributions[profitMonthId];
        require(!distribution.exists, "Distribution exists");
        require(totalProfit > 0, "Total profit required");

        distributions[profitMonthId] = Distribution({
            totalProfit: totalProfit,
            distributed: false,
            exists: true
        });

        emit DistributionCreated(profitMonthId, totalProfit);
    }

    function executeDistribution(
        uint256 profitMonthId,
        address[] calldata stakers,
        uint256[] calldata stakerShares,
        address[] calldata authors,
        uint256[] calldata authorShares
    ) external onlyOwner {
        Distribution storage distribution = distributions[profitMonthId];
        require(distribution.exists, "Distribution missing");
        require(!distribution.distributed, "Distribution already executed");

        require(stakers.length <= MAX_STAKERS, "Stakers cap exceeded");
        require(authors.length <= MAX_AUTHORS, "Authors cap exceeded");
        require(stakers.length == stakerShares.length, "Staker share mismatch");
        require(authors.length == authorShares.length, "Author share mismatch");

        uint256 totalProfit = distribution.totalProfit;
        require(usdc.balanceOf(address(this)) >= totalProfit, "Insufficient USDC");

        uint256 stakersAmount = (totalProfit * STAKERS_BPS) / BPS_DENOMINATOR;
        uint256 treasuryAmount = (totalProfit * TREASURY_BPS) / BPS_DENOMINATOR;
        uint256 authorsAmount = (totalProfit * AUTHORS_BPS) / BPS_DENOMINATOR;
        uint256 founderAmount = (totalProfit * FOUNDER_BPS) / BPS_DENOMINATOR;

        uint256 allocated = stakersAmount + treasuryAmount + authorsAmount + founderAmount;
        uint256 dust = totalProfit - allocated;
        treasuryAmount += dust;

        if (stakers.length == 0) {
            treasuryAmount += stakersAmount;
            stakersAmount = 0;
        } else {
            _distributeByShares(stakers, stakerShares, stakersAmount);
        }

        if (authors.length == 0) {
            treasuryAmount += authorsAmount;
            authorsAmount = 0;
        } else {
            _distributeByShares(authors, authorShares, authorsAmount);
        }

        usdc.safeTransfer(founderWallet, founderAmount);
        usdc.safeTransfer(treasuryWallet, treasuryAmount);

        distribution.distributed = true;
        emit DistributionExecuted(profitMonthId, totalProfit);
    }

    function getDistribution(uint256 profitMonthId) external view returns (Distribution memory) {
        return distributions[profitMonthId];
    }

    function _distributeByShares(
        address[] calldata recipients,
        uint256[] calldata shares,
        uint256 amount
    ) private {
        uint256 totalShares = 0;
        for (uint256 i = 0; i < shares.length; i++) {
            totalShares += shares[i];
        }
        require(totalShares > 0, "Total shares required");

        uint256 remaining = amount;
        for (uint256 i = 0; i < recipients.length; i++) {
            uint256 payout;
            if (i == recipients.length - 1) {
                payout = remaining;
            } else {
                payout = (amount * shares[i]) / totalShares;
                remaining -= payout;
            }
            if (payout > 0) {
                usdc.safeTransfer(recipients[i], payout);
            }
        }
    }
}
