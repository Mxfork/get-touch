import os
import json
import time
import logging
from typing import List, Dict, Any, Optional

import requests
from dotenv import load_dotenv
from web3 import Web3
from web3.contract import Contract
from web3.logs import DISCARD
from web3.types import LogReceipt

# --- Configuration & Setup ---

# Load environment variables from .env file
load_dotenv()

# Configure logging to provide detailed output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bridge_listener.log')
    ]
)

# --- Constants ---

# Placeholder ABIs for the bridge contracts on source and destination chains
# In a real-world scenario, these would be loaded from JSON files.
SOURCE_BRIDGE_ABI = json.loads('''
[
    {
        "anonymous": false,
        "inputs": [
            {"indexed": true, "name": "sender", "type": "address"},
            {"indexed": true, "name": "recipient", "type": "address"},
            {"indexed": false, "name": "amount", "type": "uint256"},
            {"indexed": false, "name": "destinationChainId", "type": "uint256"},
            {"indexed": false, "name": "nonce", "type": "uint256"}
        ],
        "name": "TokensLocked",
        "type": "event"
    }
]
''')

DESTINATION_BRIDGE_ABI = json.loads('''
[
    {
        "inputs": [
            {"name": "recipient", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "sourceNonce", "type": "uint256"}
        ],
        "name": "mintTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]
''')

# --- Core Classes ---

class BlockchainConnector:
    """
    Manages the connection to a specific blockchain via its RPC endpoint.
    Handles basic health checks and contract object instantiation.
    """

    def __init__(self, rpc_url: str):
        """
        Initializes the connector and establishes a connection.

        Args:
            rpc_url (str): The HTTP RPC endpoint of the blockchain node.
        """
        self.rpc_url = rpc_url
        self.web3 = None
        self._connect()

    def _connect(self) -> None:
        """
        Establishes a connection to the RPC endpoint and performs a health check.
        Raises ConnectionError on failure.
        """
        try:
            # Use requests for a preliminary health check with a timeout
            response = requests.post(self.rpc_url, json={'jsonrpc':'2.0','method':'web3_clientVersion','params':[],'id':1}, timeout=10)
            response.raise_for_status()
            if 'error' in response.json():
                raise ConnectionError(f"RPC endpoint returned an error: {response.json()['error']}")

            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self.web3.is_connected():
                raise ConnectionError(f"Failed to connect to Web3 provider at {self.rpc_url}")
            logging.info(f"Successfully connected to blockchain node at {self.rpc_url}")
        except requests.exceptions.RequestException as e:
            logging.error(f"HTTP request to RPC endpoint {self.rpc_url} failed: {e}")
            raise ConnectionError(f"Could not reach RPC endpoint: {self.rpc_url}") from e

    def get_contract(self, address: str, abi: List[Dict[str, Any]]) -> Optional[Contract]:
        """
        Creates a Web3 contract object for a given address and ABI.

        Args:
            address (str): The Ethereum address of the smart contract.
            abi (List[Dict[str, Any]]): The contract's Application Binary Interface (ABI).

        Returns:
            Optional[Contract]: A Web3 contract object, or None if the address is invalid.
        """
        if not self.web3 or not self.web3.is_address(address):
            logging.error(f"Invalid contract address provided: {address}")
            return None
        return self.web3.eth.contract(address=self.web3.to_checksum_address(address), abi=abi)

    def get_latest_block(self) -> int:
        """
        Fetches the latest block number from the connected blockchain.

        Returns:
            int: The latest block number.
        """
        if not self.web3:
            raise ConnectionError("Web3 provider is not initialized.")
        return self.web3.eth.block_number


class EventScanner:
    """
    Scans a range of blocks on a source blockchain for a specific event.
    Includes logic to handle block ranges and potential node limitations.
    """

    def __init__(self, connector: BlockchainConnector, contract: Contract, event_name: str):
        """
        Initializes the event scanner.

        Args:
            connector (BlockchainConnector): The connector for the source blockchain.
            contract (Contract): The Web3 contract object to scan for events.
            event_name (str): The name of the event to listen for (e.g., 'TokensLocked').
        """
        self.connector = connector
        self.contract = contract
        self.event_name = event_name
        self.event_filter = self.contract.events[event_name]

    def scan_blocks(self, from_block: int, to_block: int, max_range: int = 1000) -> List[LogReceipt]:
        """
        Scans a range of blocks for events, handling large ranges by splitting them into chunks.

        Args:
            from_block (int): The starting block number.
            to_block (int): The ending block number.
            max_range (int): The maximum number of blocks to scan in a single query.

        Returns:
            List[LogReceipt]: A list of event logs found in the specified range.
        """
        if from_block > to_block:
            return []

        logging.info(f"Scanning for '{self.event_name}' events from block {from_block} to {to_block}")
        all_events = []
        start = from_block

        while start <= to_block:
            end = min(start + max_range - 1, to_block)
            try:
                event_logs = self.event_filter.get_logs(fromBlock=start, toBlock=end)
                if event_logs:
                    logging.info(f"Found {len(event_logs)} event(s) between blocks {start} and {end}")
                    all_events.extend(event_logs)
                start = end + 1
            except Exception as e:
                # This can happen if the RPC node is overloaded or the range is too large
                logging.error(f"Error fetching logs from block {start} to {end}: {e}")
                # Wait a bit before retrying the same chunk
                time.sleep(10)
        
        return all_events


class BridgeRelayer:
    """
    The main orchestrator. It uses an EventScanner to find events on the source chain
    and simulates relaying them to the destination chain.
    """

    def __init__(self, source_scanner: EventScanner, dest_connector: BlockchainConnector, dest_contract: Contract, relayer_pk: str, start_block: int):
        """
        Initializes the Bridge Relayer.

        Args:
            source_scanner (EventScanner): Scanner for the source chain.
            dest_connector (BlockchainConnector): Connector for the destination chain.
            dest_contract (Contract): The bridge contract on the destination chain.
            relayer_pk (str): Private key of the relayer account for signing transactions.
            start_block (int): The block to start scanning from.
        """
        self.source_scanner = source_scanner
        self.dest_connector = dest_connector
        self.dest_contract = dest_contract
        
        if not relayer_pk:
             raise ValueError("Relayer private key is not set.")
        self.relayer_account = self.dest_connector.web3.eth.account.from_key(relayer_pk)
        self.relayer_address = self.relayer_account.address

        # State management to prevent re-processing events
        self.processed_nonces = set()
        self.last_processed_block = start_block
        # Number of blocks to wait for confirmation to avoid reorgs
        self.reorg_safety_margin = 5 
        
        logging.info(f"Bridge Relayer initialized. Relayer address: {self.relayer_address}")
        logging.info(f"Starting scan from block: {self.last_processed_block}")

    def process_event(self, event: LogReceipt) -> None:
        """
        Processes a single 'TokensLocked' event and simulates relaying it.

        Args:
            event (LogReceipt): The event log to process.
        """
        try:
            nonce = event['args']['nonce']
            recipient = event['args']['recipient']
            amount = event['args']['amount']

            if nonce in self.processed_nonces:
                logging.warning(f"Skipping already processed nonce: {nonce}")
                return

            logging.info(f"Processing event with nonce {nonce}: Send {amount} to {recipient}")

            # --- Simulate Transaction to Destination Chain ---
            w3 = self.dest_connector.web3
            
            # 1. Build the transaction to call 'mintTokens'
            tx_data = self.dest_contract.functions.mintTokens(
                recipient,
                amount,
                nonce
            ).build_transaction({
                'from': self.relayer_address,
                'nonce': w3.eth.get_transaction_count(self.relayer_address),
                'gas': 200000, # Estimated gas, in a real app this should be calculated
                'gasPrice': w3.eth.gas_price
            })

            # 2. Sign the transaction
            signed_tx = self.relayer_account.sign_transaction(tx_data)

            # 3. Send the transaction (SIMULATION - we are not actually sending it)
            # In a real relayer, you would uncomment the following line:
            # tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            # logging.info(f"Transaction sent to destination chain. Tx Hash: {tx_hash.hex()}")
            # receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            # if receipt.status == 0:
            #    logging.error(f"Transaction for nonce {nonce} failed on destination chain!")
            #    return
            
            logging.info(f"[SIMULATION] Sent 'mintTokens' transaction for nonce {nonce}.")
            logging.info(f"[SIMULATION] TX Details: {tx_data}")

            # 4. Mark as processed
            self.processed_nonces.add(nonce)

        except Exception as e:
            logging.error(f"Failed to process event {event}: {e}")

    def run(self, poll_interval: int = 15) -> None:
        """
        The main execution loop of the relayer.
        """
        logging.info("Starting relayer event loop...")
        while True:
            try:
                latest_block = self.source_scanner.connector.get_latest_block()
                # Define the block range to scan, leaving a margin for finality
                to_block = latest_block - self.reorg_safety_margin

                if to_block > self.last_processed_block:
                    events = self.source_scanner.scan_blocks(
                        from_block=self.last_processed_block + 1,
                        to_block=to_block
                    )

                    if events:
                        # Sort events by block number and log index to process in order
                        events.sort(key=lambda e: (e['blockNumber'], e['logIndex']))
                        for event in events:
                            self.process_event(event)
                    
                    self.last_processed_block = to_block
                else:
                    logging.info(f"No new blocks to scan. Current head: {latest_block}")

                time.sleep(poll_interval)
            except ConnectionError as e:
                logging.error(f"Connection error in main loop: {e}. Retrying in 60 seconds...")
                time.sleep(60)
            except Exception as e:
                logging.critical(f"An unexpected error occurred in the relayer loop: {e}", exc_info=True)
                time.sleep(30)

def main():
    """
    Entry point for the script.
    """
    # --- Load Configuration ---
    SOURCE_RPC_URL = os.getenv("SOURCE_CHAIN_RPC_URL")
    DESTINATION_RPC_URL = os.getenv("DESTINATION_CHAIN_RPC_URL")
    SOURCE_BRIDGE_CONTRACT = os.getenv("SOURCE_BRIDGE_CONTRACT_ADDRESS")
    DESTINATION_BRIDGE_CONTRACT = os.getenv("DESTINATION_BRIDGE_CONTRACT_ADDRESS")
    RELAYER_PRIVATE_KEY = os.getenv("RELAYER_PRIVATE_KEY")
    START_BLOCK = int(os.getenv("START_BLOCK", "0"))

    # --- Validate Configuration ---
    required_vars = {
        "SOURCE_CHAIN_RPC_URL": SOURCE_RPC_URL,
        "DESTINATION_CHAIN_RPC_URL": DESTINATION_RPC_URL,
        "SOURCE_BRIDGE_CONTRACT_ADDRESS": SOURCE_BRIDGE_CONTRACT,
        "DESTINATION_BRIDGE_CONTRACT_ADDRESS": DESTINATION_BRIDGE_CONTRACT,
        "RELAYER_PRIVATE_KEY": RELAYER_PRIVATE_KEY
    }
    for var_name, value in required_vars.items():
        if not value:
            logging.error(f"Environment variable '{var_name}' is not set. Please create a .env file.")
            return
    
    try:
        # --- Initialize Components ---
        logging.info("--- Initializing Bridge Components ---")
        source_connector = BlockchainConnector(rpc_url=SOURCE_RPC_URL)
        dest_connector = BlockchainConnector(rpc_url=DESTINATION_RPC_URL)

        source_contract = source_connector.get_contract(SOURCE_BRIDGE_CONTRACT, SOURCE_BRIDGE_ABI)
        dest_contract = dest_connector.get_contract(DESTINATION_BRIDGE_CONTRACT, DESTINATION_BRIDGE_ABI)

        if not source_contract or not dest_contract:
            logging.error("Failed to initialize one or more contracts. Exiting.")
            return
        
        scanner = EventScanner(source_connector, source_contract, 'TokensLocked')
        relayer = BridgeRelayer(
            source_scanner=scanner,
            dest_connector=dest_connector,
            dest_contract=dest_contract,
            relayer_pk=RELAYER_PRIVATE_KEY,
            start_block=START_BLOCK
        )

        # --- Start the Relayer ---
        relayer.run()
    
    except ConnectionError as e:
        logging.critical(f"Failed to establish initial blockchain connection: {e}")
    except Exception as e:
        logging.critical(f"A fatal error occurred during initialization: {e}", exc_info=True)


if __name__ == "__main__":
    main()
# @-internal-utility-start
CACHE = {}
def get_from_cache_3088(key: str):
    """Retrieves an item from cache. Implemented on 2025-11-03 14:04:52"""
    return CACHE.get(key, None)
# @-internal-utility-end

