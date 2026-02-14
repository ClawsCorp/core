// SPDX-License-Identifier: BSL-1.1
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract FundingPool {
    using SafeERC20 for IERC20;

    IERC20 public immutable usdc;

    mapping(bytes32 => uint256) private totalStakedByProject;
    mapping(bytes32 => mapping(address => uint256)) private stakedByProjectByUser;

    event Staked(address indexed staker, bytes32 indexed projectKey, uint256 amount);
    event Unstaked(address indexed staker, bytes32 indexed projectKey, uint256 amount);

    constructor(address usdcAddress) {
        require(usdcAddress != address(0), "USDC address required");
        usdc = IERC20(usdcAddress);
    }

    function stake(bytes32 projectKey, uint256 amount) external {
        require(amount > 0, "Amount required");

        usdc.safeTransferFrom(msg.sender, address(this), amount);

        stakedByProjectByUser[projectKey][msg.sender] += amount;
        totalStakedByProject[projectKey] += amount;

        emit Staked(msg.sender, projectKey, amount);
    }

    function unstake(bytes32 projectKey, uint256 amount) external {
        require(amount > 0, "Amount required");

        uint256 currentStake = stakedByProjectByUser[projectKey][msg.sender];
        require(currentStake >= amount, "Insufficient stake");

        stakedByProjectByUser[projectKey][msg.sender] = currentStake - amount;
        totalStakedByProject[projectKey] -= amount;

        usdc.safeTransfer(msg.sender, amount);

        emit Unstaked(msg.sender, projectKey, amount);
    }

    function stakeOf(bytes32 projectKey, address staker) external view returns (uint256) {
        return stakedByProjectByUser[projectKey][staker];
    }

    function totalStake(bytes32 projectKey) external view returns (uint256) {
        return totalStakedByProject[projectKey];
    }
}
