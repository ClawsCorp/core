require("@nomicfoundation/hardhat-toolbox");

const { subtask } = require("hardhat/config");
const { TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD } = require("hardhat/builtin-tasks/task-names");

// Hardhat normally downloads solc builds from upstream.
// To avoid flaky CI due to network issues, force Hardhat to use the locally installed
// solc-js (pinned in package.json) for the configured compiler version.
subtask(TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD).setAction(
  async ({ solcVersion, quiet }, hre, runSuper) => {
    if (solcVersion !== "0.8.24") {
      return runSuper({ solcVersion, quiet });
    }

    // This resolves to the top-level solc dependency in contracts/node_modules.
    // We intentionally fail if it doesn't match the configured solcVersion to
    // avoid accidentally compiling with a different compiler.
    // eslint-disable-next-line global-require
    const solc = require("solc");
    const longVersion = typeof solc.version === "function" ? solc.version() : "";
    if (!longVersion.startsWith(solcVersion)) {
      throw new Error(
        `Installed solc (${longVersion || "unknown"}) does not match required ${solcVersion}. ` +
          `Run: npm --prefix contracts ci (or install solc@${solcVersion}).`
      );
    }

    return {
      version: solcVersion,
      longVersion,
      compilerPath: require.resolve("solc/soljson.js"),
      isSolcJs: true
    };
  }
);

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200
      },
      viaIR: true
    }
  },
  paths: {
    sources: "./contracts",
    tests: "./test",
    cache: "./cache",
    artifacts: "./artifacts"
  }
};
