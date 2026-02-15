# Paxos-BankBlockchain-

# Paxos-Based Distributed Blockchain (5-Node Local Cluster)

## Overview

This project implements a fault-tolerant distributed blockchain using the Paxos consensus algorithm.

Five independent nodes run locally on different ports and coordinate over TCP sockets to:

- Elect a leader dynamically
- Reach consensus on new transactions
- Commit blocks atomically
- Maintain replicated account balances
- Recover from failures via state synchronization
- Persist blockchain state to disk

The system simulates a decentralized cryptocurrency-style ledger with integrated Proof-of-Work (PoW) and consensus guarantees.

---

## Cluster Configuration

The system runs 5 nodes on localhost:

```json
{
  "nodes": [
    { "id": 1, "host": "localhost", "port": 5001 },
    { "id": 2, "host": "localhost", "port": 5002 },
    { "id": 3, "host": "localhost", "port": 5003 },
    { "id": 4, "host": "localhost", "port": 5004 },
    { "id": 5, "host": "localhost", "port": 5005 }
  ]
}
```

Each node:
- Maintains its own blockchain replica
- Maintains local account balances
- Participates in Paxos consensus
- Communicates via TCP sockets
- Persists state to disk (`node_X_blockchain.json`, `node_X_balances.json`)

---

## System Architecture

### 1. Blockchain Layer

Each block contains:

- `sender_id`
- `receiver_id`
- `amount`
- `nonce` (Proof-of-Work)
- `prev_hash`
- `depth`
- `hash`

Genesis block:
- Depth = 0
- Hash = 64 zeros

Each node starts with:

```
Node 1–5 balance = 100
```

---

### 2. Proof of Work (PoW)

Before proposing a block, the node must compute a nonce such that:

```
SHA256(sender|receiver|amount|nonce|prev_hash)
```

has a last character in:

```
0, 1, 2, 3, or 4
```

This introduces computational cost before consensus begins.

---

### 3. Paxos Consensus Implementation

The system implements classic Paxos:

#### Phase 1 — PREPARE
- Node increments ballot number
- Sends `PREPARE` to all peers
- Waits for majority `PROMISE`

#### Phase 2 — ACCEPT
- If majority promises received:
  - Node becomes leader
  - Sends `ACCEPT` with proposed block

#### Phase 3 — DECIDE
- If majority `ACCEPTED` responses received:
  - Block is committed
  - `DECIDE` broadcast to cluster

Majority required: 3 of 5 nodes

Ballot format:

```
(sequence_number, node_id, blockchain_depth)
```

---

## Fault Tolerance & Recovery

The system handles:

- Node crashes
- Out-of-date blockchain
- Higher ballot preemption
- Network delay simulation (3s artificial delay)
- Manual resynchronization

If a node detects it is out-of-date:

```
REQUEST_BLOCKCHAIN → BLOCKCHAIN_UPDATE
```

It replaces its chain with the longest valid chain.

Each node persists:

```
node_X_blockchain.json
node_X_balances.json
```

This enables crash recovery and restart without data loss.

---

## Commands

Once running, each node supports:

```
moneyTransfer <receiver_id> <amount>
failProcess
printBlockchain
printBalance
sync
```

### Example Usage

```
moneyTransfer 3 25
printBlockchain
printBalance
```

---

## How to Run

### 1. Start Nodes

Open five terminals and run:

```bash
python node.py 1 config.json
python node.py 2 config.json
python node.py 3 config.json
python node.py 4 config.json
python node.py 5 config.json
```

---

### 2. Simulate a Transaction

On any node:

```
moneyTransfer 4 10
```

Observe:
- PoW computation
- Leader election
- Consensus logs
- Block commit

---

### 3. Simulate Failure

```
failProcess
```

Restart the node and run:

```
sync
```

---

## Makefile Utilities

Kill all running nodes:

```bash
make kill
```

Clean blockchain and balance files:

```bash
make clean
```

This:
- Stops all node processes
- Clears persistent JSON files

---

## Key Design Decisions

### Deterministic Ballot Ordering

Ballots include:
- Sequence number
- Node ID
- Blockchain depth

This ensures total ordering across nodes.

### Thread Safety

All state transitions are guarded by:

```python
self.lock = threading.Lock()
```

Ensuring atomic consensus transitions.

---

## Example Hash Validation Script

A standalone SHA256 verification snippet can validate PoW:

```python
content = f"{sender}|{receiver}|{amount}|{nonce}|{prev_hash}"
hash_result = hashlib.sha256(content.encode()).hexdigest()
print(hash_result)
print(f"Last character: {hash_result[-1]}")
```

---

## Properties Achieved

- Replicated state machine
- Leader election via Paxos
- Majority quorum safety
- Crash recovery
- Network delay simulation
- Proof-of-Work integration
- Persistent ledger
- Eventual consistency


## Technical Stack

- Python
- TCP sockets
- Multithreading
- JSON persistence
- SHA-256 hashing
- Paxos consensus algorithm
