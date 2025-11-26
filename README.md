# get-touch: A Cross-Chain Bridge Event Listener Simulation

This repository contains a comprehensive Python script that simulates the core component of a cross-chain bridge: the event listener and relayer. This component is responsible for listening for specific events on a source blockchain (e.g., users locking tokens) and relaying that information to a destination blockchain to complete the cross-chain action (e.g., minting wrapped tokens).

This script is an educational tool designed to demonstrate the architecture of a relayer. It simulates the necessary logic without sending real transactions, making it safe for experimentation and development.

## Concept

Cross-chain bridges are essential for blockchain interoperability, allowing assets and data to move between different networks. A common design pattern for these bridges is the "lock-and-mint" mechanism:

1.  **Lock**: A user locks their assets (e.g., ETH) in a smart contract on the source chain (e.g., Ethereum).
2.  **Event Emission**: The source chain contract emits an event (`TokensLocked`) containing details like the recipient's address on the destination chain and the amount.
3.  **Listen & Relay**: Off-chain services, known as "relayers" or "validators," constantly listen for these events.
4.  **Verification**: Upon detecting a valid `TokensLocked` event, a relayer submits a transaction to a smart contract on the destination chain (e.g., Polygon). This transaction proves the lock event occurred.
5.  **Mint**: The destination chain contract verifies the proof and mints a corresponding amount of a wrapped asset (e.g., WETH) to the recipient.

This script simulates the critical **Steps 3 and 4** of this process, acting as the off-chain relayer node.

## Code Architecture

The script is designed with a modular, object-oriented approach to separate concerns and enhance maintainability.

```
+-----------------------+
|       main.py         |  (Entry Point & Orchestration)
+-----------+-----------+
            |
+-----------v-----------+
|      BridgeRelayer    |  (Core logic, state management, transaction simulation)
+-----------+-----------+
            |           |
+-----------v-----------+     +-----------------------+
|      EventScanner     |----->| BlockchainConnector   | (Manages Web3 connection)
+-----------------------+     | (Source Chain)        | (Handles contract interaction)
                              +-----------------------+

+-----------------------+
| BlockchainConnector   | (Manages Web3 connection)
| (Destination Chain)   | (Handles contract interaction)
+-----------------------+

+-----------------------+
|         .env          | (Configuration: RPC URLs, Private Keys, Addresses)
+-----------------------+
```

*   `BlockchainConnector`: A reusable class that manages the connection to a single blockchain node via its RPC URL. It uses `web3.py` for blockchain interaction.
*   `EventScanner`: Responsible for scanning a specified range of blocks on the source chain for a particular event (e.g., `TokensLocked`). It handles potential RPC node limitations by querying in smaller chunks.
*   `BridgeRelayer`: The main orchestrator. It contains the primary execution loop. It uses the `EventScanner` to find new events, manages state to avoid re-processing events (replay protection), and simulates crafting and signing transactions for the destination chain.
*   `main.py` (Script Body): The entry point that loads configuration from the `.env` file, initializes all the necessary objects, and starts the relayer's main loop.

## How it Works

The relayer operates in a continuous loop, performing the following steps:

1.  **Initialization**: The script starts by loading configuration from the `.env` file (RPC URLs, contract addresses, relayer's private key) and the contract ABIs.
2.  **Connection**: It instantiates two `BlockchainConnector` objects, one for the source chain and one for the destination chain, establishing and verifying the connections.
3.  **Looping**: The `BridgeRelayer` enters its main `run()` loop.
4.  **Block Range Calculation**: In each iteration, it fetches the latest block number from the source chain. It calculates the range of blocks to scan, starting from the last block it processed and ending at `latest_block - REORG_SAFETY_MARGIN`. This margin ensures it only processes blocks that are unlikely to be part of a chain reorganization.
5.  **Event Scanning**: It calls the `EventScanner` to query the source chain's bridge contract for `TokensLocked` events within the calculated block range.
6.  **Event Processing**: If new events are found, they are sorted by block number to ensure correct order. For each event:
    *   It decodes the event data (recipient, amount, nonce).
    *   It checks its internal state (`processed_nonces`) to ensure this event hasn't been relayed before.
    *   It simulates building and signing a `mintTokens` transaction for the destination chain using the relayer's private key.
    *   It logs the simulated transaction details.
7.  **State Update**: After processing the events in a batch, it updates `last_processed_block` to the end of the scanned range.
8.  **Polling**: The script then waits for a configured poll interval (e.g., 15 seconds) before starting the next iteration.

Error handling is included for connection issues and other potential exceptions to ensure the relayer is resilient.

## Getting Started

### 1. Requirements

*   Python 3.8+
*   Access to RPC endpoints for two Ethereum-compatible chains (e.g., using Infura, Alchemy, or a local node). For this example, we can use public testnet RPCs like Sepolia and Mumbai.
*   Contract ABIs (in JSON format) for the source and destination bridge contracts.

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/your-username/get-touch.git
cd get-touch

# Create a Python virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`

# Install the required dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a file named `.env` in the project's root directory to store your configuration. The script uses this file to load settings as environment variables. **Do not commit this file to version control.**

Here is an example `.env` template:
```env
# .env file example

# RPC endpoint for the source chain (e.g., Ethereum Sepolia)
SOURCE_CHAIN_RPC_URL="https://rpc.sepolia.org"

# RPC endpoint for the destination chain (e.g., Polygon Mumbai)
DESTINATION_CHAIN_RPC_URL="https://rpc-mumbai.maticvigil.com"

# Address of the bridge contract on the source chain
SOURCE_BRIDGE_CONTRACT_ADDRESS="0x..."

# Address of the bridge contract on the destination chain
DESTINATION_BRIDGE_CONTRACT_ADDRESS="0x..."

# Private key of the relayer's wallet.
# IMPORTANT: Use a dedicated account with test funds only.
# This account requires a small balance on the destination chain to pay for gas fees.
RELAYER_PRIVATE_KEY="0x..."

# The block number from which to start scanning on the source chain.
# Set this to the block number when the contract was deployed, or a recent block.
START_BLOCK="1234567"
```

### 4. Run the Relayer

Execute the script from your terminal:

```bash
python main.py
```

### 5. Monitor the Output

The script will start logging its activities to the console and to a `bridge_relayer.log` file. You will see output similar to the following as it scans blocks and processes events.

```
2023-10-27 10:30:00,123 - INFO - main - --- Initializing Bridge Components ---
2023-10-27 10:30:01,456 - INFO - BlockchainConnector - Successfully connected to blockchain node at https://rpc.sepolia.org
2023-10-27 10:30:02,789 - INFO - BlockchainConnector - Successfully connected to blockchain node at https://rpc-mumbai.maticvigil.com
2023-10-27 10:30:02,790 - INFO - BridgeRelayer - Bridge Relayer initialized. Relayer address: 0xYourRelayerAddress...
2023-10-27 10:30:02,791 - INFO - BridgeRelayer - Starting scan from block: 1234567
2023-10-27 10:30:02,792 - INFO - BridgeRelayer - Starting relayer event loop...
2023-10-27 10:30:05,100 - INFO - EventScanner - Scanning for 'TokensLocked' events from block 1234568 to 1234600
2023-10-27 10:30:07,200 - INFO - EventScanner - Found 1 event(s) between blocks 1234568 and 1234600
2023-10-27 10:30:07,201 - INFO - BridgeRelayer - Processing event with nonce 101: Send 5000000000000000000 to 0xRecipientAddress...
2023-10-27 10:30:07,500 - INFO - BridgeRelayer - [SIMULATION] Sent 'mintTokens' transaction for nonce 101.
2023-10-27 10:30:07,501 - INFO - BridgeRelayer - [SIMULATION] TX Details: {'from': '0xYourRelayerAddress...', 'nonce': 5, ...}
2023-10-27 10:30:17,800 - INFO - BridgeRelayer - No new blocks to scan. Current head: 1234605
...
```