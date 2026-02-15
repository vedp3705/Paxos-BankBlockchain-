import socket
import threading
import json
import hashlib
import random
import string
import time
import os
import sys
from collections import defaultdict

class Block:
    def __init__(self, sender_id, receiver_id, amount, nonce, prev_hash, depth):
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.amount = amount
        self.nonce = nonce
        self.prev_hash = prev_hash
        self.depth = depth
        self.hash = self.calculate_hash()
    
    def calculate_hash(self):
        if self.depth == 0:  # first block
            return "0" * 64

        content = f"{self.sender_id}|{self.receiver_id}|{self.amount}|{self.nonce}|{self.prev_hash}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def to_dict(self):
        return {
            'sender_id': self.sender_id,
            'receiver_id': self.receiver_id,
            'amount': self.amount,
            'nonce': self.nonce,
            'prev_hash': self.prev_hash,
            'depth': self.depth,
            'hash': self.hash
        }
    
    @staticmethod
    def from_dict(data):
        block = Block(data['sender_id'], data['receiver_id'], data['amount'], data['nonce'], data['prev_hash'], data['depth'])
        block.hash = data['hash']
        return block

class PaxosNode:
    def __init__(self, node_id, port, config_file):
        self.node_id = node_id
        self.port = port
        self.peers = {}
        self.load_config(config_file)
        
        self.blockchain = []
        self.balances = {}
        for i in range(1, 6):
            self.balances[i] = 100
        self.blockchain_depth = 0
        
        self.promised_ballot = {}  
        self.accepted_ballot = {}  
        self.accepted_value = {}  
        self.current_seq = 0
        
        self.is_leader = False   # basically book flag
        self.promise_count = 0
        self.accept_count = 0
        self.pending_block = None
        self.pending_ballot = None
        self.promises_received = threading.Event()
        
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('localhost', self.port))
        self.running = True
        
        self.blockchain_file = f"node_{node_id}_blockchain.json"
        self.balances_file = f"node_{node_id}_balances.json"
        self.load_from_disk()
        
        if len(self.blockchain) == 0:   # make 1st block if not there
            first_block = Block(0, 0, 0, "", "", 0)
            self.blockchain.append(first_block)
            self.blockchain_depth = 1
            self.save_to_disk()
        
        self.lock = threading.Lock()
        
    def load_config(self, config_file):
        with open(config_file, 'r') as f:
            config = json.load(f)
            for node_info in config['nodes']:
                if node_info['id'] != self.node_id:
                    self.peers[node_info['id']] = (node_info['host'], node_info['port'])
    
    def load_from_disk(self):
        if os.path.exists(self.blockchain_file):
            with open(self.blockchain_file, 'r') as f:
                data = json.load(f)
                self.blockchain = []
                for block_data in data['blocks']:
                    block = Block.from_dict(block_data)  # conv to block obj
                    self.blockchain.append(block)        #    add to bc
                self.blockchain_depth = len(self.blockchain)
        
        if os.path.exists(self.balances_file):
            with open(self.balances_file, 'r') as f:
                self.balances = json.load(f)
                new_balances = {}
                for i, j in self.balances.items():
                    new_balances[int(i)] = j 
                self.balances = new_balances
    
    def save_to_disk(self):
        with open(self.blockchain_file, 'w') as f:
            json.dump({'blocks': [b.to_dict() for b in self.blockchain]}, f)
        
        with open(self.balances_file, 'w') as f:
            json.dump(self.balances, f)
    
    def find_nonce(self, sender_id, receiver_id, amount, prev_hash):
        print(f"[Node {self.node_id}] Computing nonce (Proof of Work)...")
        while True:
            nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            content = f"{sender_id}|{receiver_id}|{amount}|{nonce}|{prev_hash}"
            hash_val = hashlib.sha256(content.encode()).hexdigest()
            if hash_val[-1] in '01234':
                print(f"[Node {self.node_id}] Found valid nonce: {nonce}")
                print(f"[Node {self.node_id}] PoW Hash: {hash_val} (last char: {hash_val[-1]})")
                return nonce
        
    def start_paxos_leader_election(self, sender_id, receiver_id, amount):
        with self.lock:
            # current_seq++
            self.current_seq += 1
            ballot = (self.current_seq, self.node_id, self.blockchain_depth)
            # ballot = (self.blockchain_depth, self.current_seq, self.node_id)  ###
            self.pending_ballot = ballot
            self.promise_count = 1  # auto set self promise to 1 so no promise msg has to be sent/recv to self
            self.accept_count = 0
            self.is_leader = False
            self.promises_received.clear()
            
            prev_block = self.blockchain[-1]    ## last block
            prev_hash = prev_block.hash
            
        nonce = self.find_nonce(sender_id, receiver_id, amount, prev_hash) # do outsid e lock cuz may take long
        
        with self.lock:
            self.pending_block = Block(sender_id, receiver_id, amount, nonce, prev_hash, self.blockchain_depth)
            print(f"[Node {self.node_id}] Block Hash: {self.pending_block.hash}")
            
        print(f"[Node {self.node_id}] Starting Paxos with ballot {ballot}")
        
        prepare_msg = {
            'type': 'PREPARE',
            'ballot': ballot,
            'from': self.node_id    # prep msg to other cli
        }
        
        for peer_id in self.peers:
            threading.Thread(target=self.send_message, args=(peer_id, prepare_msg)).start()
        
        timeout = 8     # 8s w 3s in consideration
        if self.promises_received.wait(timeout):
            with self.lock:
                if self.pending_ballot != ballot:   # check if abort due to out of date
                    print(f"[Node {self.node_id}] Leader election aborted due to ballot being changed)")
                    return
                    
                if self.promise_count >= 3:  ## paxos majority
                    self.is_leader = True
                    print(f"[Node {self.node_id}] Became leader with ballot {ballot}")
                    self.send_accept_messages()
                else:
                    print(f"[Node {self.node_id}] Failed to get majority promises (got {self.promise_count})")
        else:
            print(f"[Node {self.node_id}] Timeout waiting for promises")
            print('\n')
    
    def send_accept_messages(self):
        accept_msg = {    # accept msg - simialr to prep j w block
            'type': 'ACCEPT',
            'ballot': self.pending_ballot,
            'block': self.pending_block.to_dict(),
            'from': self.node_id
        }
        
        self.accept_count = 1 
        
        print(f"[Node {self.node_id}] Sending ACCEPT messages for block at depth {self.blockchain_depth}")
        
        for peer_id in self.peers:
            threading.Thread(target=self.send_message, args=(peer_id, accept_msg)).start()
    
    def send_message(self, peer_id, message):
        time.sleep(3)        # sim network delay
        try:      # put in try in case node down
            host, port = self.peers[peer_id]
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            sock.sendall(json.dumps(message).encode() + b'\n')
            sock.close()
        except Exception as e:
            print(f"[Node {self.node_id}] Failed to send to Node {peer_id}: {e}")
    
    def send_message_no_delay(self, peer_id, message):
        try:
            host, port = self.peers[peer_id]   # no delay for sync 
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((host, port))
            sock.sendall(json.dumps(message).encode() + b'\n')
            sock.close()
        except Exception:
            pass     # can be retried
    
    def handle_prepare(self, ballot, from_node):
        with self.lock:
            depth = ballot[2]     # bc depth for new block
            
            if depth < self.blockchain_depth:    # check if sender has ood bc : if so send nack
                print(f"[Node {self.node_id}] Received old PREPARE from Node {from_node} (depth {depth} < {self.blockchain_depth})")
                response = {
                    'type': 'NACK',
                    'ballot': ballot,
                    'current_depth': self.blockchain_depth,    # to see how far off
                    'from': self.node_id
                }
                threading.Thread(target=self.send_message, args=(from_node, response)).start()
                return
            
            if (depth not in self.promised_ballot) or (ballot > self.promised_ballot[depth]):   # if 1st ballot for depth or highest ballot
                self.promised_ballot[depth] = ballot
                response = {
                    'type': 'PROMISE',
                    'ballot': ballot,
                    'accepted_ballot': self.accepted_ballot.get(depth),
                    'accepted_value': self.accepted_value[depth].to_dict() if depth in self.accepted_value else None,
                    'from': self.node_id
                }

                print(f"[Node {self.node_id}] Sending PROMISE for ballot {ballot}")
                threading.Thread(target=self.send_message, args=(from_node, response)).start()
            else:  # already higher ballot - nack
                print(f"[Node {self.node_id}] Rejecting PREPARE from Node {from_node} due promise to higher ballot)")
                response = {
                    'type': 'NACK',
                    'ballot': ballot,
                    'current_depth': self.blockchain_depth,
                    'promised_ballot': self.promised_ballot[depth],
                    'from': self.node_id
                }
                threading.Thread(target=self.send_message, args=(from_node, response)).start()
    
    def handle_promise(self, ballot, from_node):
        with self.lock:
            if self.pending_ballot == ballot:
                self.promise_count += 1
                print(f"[Node {self.node_id}] Received PROMISE from Node {from_node} (count: {self.promise_count})")
                if self.promise_count >= 3:      # if majority reached
                    self.promises_received.set()
    
    def handle_accept(self, ballot, block_data, from_node):
        with self.lock:
            depth = ballot[2]
            
            if depth < self.blockchain_depth:    # ignore old msg
                return
            
            if (depth not in self.promised_ballot) or (ballot >= self.promised_ballot[depth]):
                self.promised_ballot[depth] = ballot
                self.accepted_ballot[depth] = ballot
                block = Block.from_dict(block_data)
                self.accepted_value[depth] = block
                
                response = {
                    'type': 'ACCEPTED',
                    'ballot': ballot,
                    'from': self.node_id
                }

                print(f"[Node {self.node_id}] Accepted block at depth {depth} from Node {from_node}")
                threading.Thread(target=self.send_message, args=(from_node, response)).start()
    
    def handle_accepted(self, ballot, from_node):
        with self.lock:
            if (self.pending_ballot == ballot) and (self.is_leader):
                self.accept_count += 1
                print(f"[Node {self.node_id}] Received ACCEPTED from Node {from_node} (count: {self.accept_count})")
                print(f'\n')
                
                if self.accept_count == 3:  # consensus cond
                    print(f"[Node {self.node_id}] Consensus reached. Committing block.")
                    self.commit_block(self.pending_block)
                    self.send_decide_messages()
    
    def commit_block(self, block):
        self.blockchain.append(block)
        self.blockchain_depth = len(self.blockchain)
        self.current_seq = 0        #############
        
        if block.sender_id != 0:    # check not 1st
            self.balances[block.sender_id] -= block.amount
            self.balances[block.receiver_id] += block.amount
        
        self.save_to_disk()
        print(f"[Node {self.node_id}] Block committed at depth {block.depth}")
        print(f"[Node {self.node_id}] Transaction: {block.sender_id} to {block.receiver_id}, Amount: {block.amount}")
        print('\n')
    
    def send_decide_messages(self):
        decide_msg = {
            'type': 'DECIDE',
            'block': self.pending_block.to_dict(),
            'from': self.node_id
        }
        
        for peer_id in self.peers:
            threading.Thread(target=self.send_message, args=(peer_id, decide_msg)).start()
    
    def handle_decide(self, block_data, from_node):
        with self.lock:
            block = Block.from_dict(block_data)
            
            if block.depth < self.blockchain_depth:
                return   # ood block
            
            if block.depth == self.blockchain_depth:   # expected block
                print(f"[Node {self.node_id}] Received DECIDE from Node {from_node} for block at depth {block.depth}")
                self.commit_block(block)
            elif block.depth > self.blockchain_depth:    ## curr ood
                print(f"[Node {self.node_id}] Received DECIDE from Node {from_node} for future block (depth {block.depth}, current {self.blockchain_depth})")
                print(f"[Node {self.node_id}] Blockchain out of date - requesting update from Node {from_node}...")
                self.request_blockchain_update(from_node)
    
    def request_blockchain_update(self, peer_id):
        request = {
            'type': 'REQUEST_BLOCKCHAIN',
            'current_depth': self.blockchain_depth,
            'from': self.node_id
        }
        threading.Thread(target=self.send_message_no_delay, args=(peer_id, request)).start()
    
    def handle_request_blockchain(self, from_node, requester_depth=None):
        with self.lock:
            if requester_depth is None or self.blockchain_depth > requester_depth:   # if curr has more depth then send
                response = {
                    'type': 'BLOCKCHAIN_UPDATE',
                    'blockchain': [b.to_dict() for b in self.blockchain],
                    'balances': self.balances,
                    'from': self.node_id
                }
                threading.Thread(target=self.send_message_no_delay, args=(from_node, response)).start()
                print(f"[Node {self.node_id}] Sending blockchain update to Node {from_node}")
    
    def handle_blockchain_update(self, blockchain_data, balances):
        with self.lock:
            if len(blockchain_data) > len(self.blockchain):   # update if incoming longer
                print(f"[Node {self.node_id}] Updating blockchain from depth {self.blockchain_depth} to {len(blockchain_data)}...")

                self.blockchain = [Block.from_dict(b) for b in blockchain_data]
                self.blockchain_depth = len(self.blockchain)

                new_balances = {} 
                for i, j in balances.items(): 
                    new_balances[int(i)] = j

                self.balances = new_balances 
                self.save_to_disk()

                print(f"[Node {self.node_id}] Blockchain updated to depth {self.blockchain_depth}")
                print(f"[Node {self.node_id}] Balances updated: {self.balances}")
                print(f"[Node {self.node_id}] Sync complete. Ready to participate in consensus")
            else:
                print(f"[Node {self.node_id}] Blockchain already up to date (depth {self.blockchain_depth})")
    
    def handle_nack(self, ballot, current_depth, from_node, promised_ballot=None):    ##  if bc ood or ballot rejec
        with self.lock:
            if ballot:
                my_depth = ballot[2] 
            else:
                my_depth = self.blockchain_depth  
            
            if current_depth > my_depth: ## ood check
                print(f"[Node {self.node_id}] Received NACK from Node {from_node}: Blockchain out of date (current depth {my_depth}, peer has {current_depth})")
                print(f"[Node {self.node_id}] Requesting blockchain update from Node {from_node}...")
                self.request_blockchain_update(from_node)
                
                if self.pending_ballot == ballot:    #if ood stop election
                    print(f"[Node {self.node_id}] Aborting leader election - blockchain out of date")
                    self.is_leader = False
                    self.pending_ballot = None
                    self.pending_block = None
            elif promised_ballot:
                print(f"[Node {self.node_id}] Received NACK from Node {from_node}: Already promised to higher ballot {promised_ballot}")
                if self.pending_ballot == ballot:
                    print(f"[Node {self.node_id}] Leader election failed. Need higher ballot number")
    
    def handle_client(self, conn):
        try:
            data = b''
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'\n' in data:
                    break
            
            if data:
                message = json.loads(data.decode().strip())
                msg_type = message['type']
                
                if msg_type == 'PREPARE':
                    self.handle_prepare(tuple(message['ballot']), message['from'])

                elif msg_type == 'PROMISE':
                    self.handle_promise(tuple(message['ballot']), message['from'])

                elif msg_type == 'ACCEPT':
                    self.handle_accept(tuple(message['ballot']), message['block'], message['from'])

                elif msg_type == 'ACCEPTED':
                    self.handle_accepted(tuple(message['ballot']), message['from'])

                elif msg_type == 'DECIDE':
                    self.handle_decide(message['block'], message['from'])

                elif msg_type == 'REQUEST_BLOCKCHAIN':
                    requester_depth = message.get('current_depth')
                    self.handle_request_blockchain(message['from'], requester_depth)

                elif msg_type == 'BLOCKCHAIN_UPDATE':
                    self.handle_blockchain_update(message['blockchain'], message['balances'])

                elif msg_type == 'NACK':
                    ballot = tuple(message['ballot']) if 'ballot' in message else None
                    current_depth = message.get('current_depth')
                    if 'promised_ballot' in message:
                        promised_ballot = tuple(message['promised_ballot'])
                    else:
                        promised_ballot = None 

                    self.handle_nack(ballot, current_depth, message['from'], promised_ballot)

        except Exception as e:
            print(f"[Node {self.node_id}] Error handling client: {e}")
        finally:
            conn.close()
    
    def start_server(self):
        self.socket.listen(10)
        print(f"[Node {self.node_id}] Server started on port {self.port}")
        
        while self.running:
            try:
                self.socket.settimeout(1)
                conn, addr = self.socket.accept()
                threading.Thread(target=self.handle_client, args=(conn,)).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[Node {self.node_id}] Server error: {e}")
    
    def money_transfer(self, receiver_id, amount):
        with self.lock:
            if self.balances[self.node_id] < amount:
                print(f"[Node {self.node_id}] Insufficient balance")
                return
        
        print(f"[Node {self.node_id}] Initiating transfer: {amount} to Node {receiver_id}")

        threading.Thread(target=self.start_paxos_leader_election, 
                        args=(self.node_id, receiver_id, amount)).start()
    
    def manual_sync_with_peers(self):
        print(f"[Node {self.node_id}] Checking for blockchain updates...")
        time.sleep(1)
        
        if self.peers:    # sync w multipel if some failed
            for peer_id in list(self.peers.keys()):
                try:
                    self.request_blockchain_update(peer_id)
                    time.sleep(2)  
                    break 
                except Exception:
                    continue 
    
    def print_blockchain(self):
        print(f"BLOCKCHAIN - Node {self.node_id}")

        for block in self.blockchain:
            print(f"Depth: {block.depth}")

            if block.depth == 0:
                print("  [First Block]")
            else:
                print(f"  Transaction: {block.sender_id} -> {block.receiver_id}, Amount: {block.amount}")
                print(f"  Nonce: {block.nonce}")
                print(f"  Hash: {block.hash}")
                print(f"  Prev Hash: {block.prev_hash}")
                print('\n')

        print()
    
    def print_balances(self):
        print(f"ACCOUNT BALANCES - Node {self.node_id}")
        for node_id in sorted(self.balances.keys()):
            print(f"  Node {node_id}: ${self.balances[node_id]}")
        print('\n')
    
    def run(self):
        server_thread = threading.Thread(target=self.start_server)
        server_thread.daemon = True
        server_thread.start()
        
        time.sleep(0.5)
        
        print(f"\n[Node {self.node_id}] Ready. Available commands:")
        print("  moneyTransfer <credit_node> <amount>")
        print("  failProcess")
        print("  printBlockchain")
        print("  printBalance")
        print("  sync")
        print()
        
        while self.running:
            try:
                cmd = input().strip()
                if not cmd:
                    continue
                
                parts = cmd.split()
                
                if parts[0] == 'moneyTransfer':
                    receiver_id = int(parts[1])
                    amount = int(parts[2])
                    self.money_transfer(receiver_id, amount)
                
                elif parts[0] == 'failProcess':
                    print(f"[Node {self.node_id}] Failing process...")
                    self.running = False
                    self.socket.close()
                    break
                
                elif parts[0] == 'printBlockchain':
                    self.print_blockchain()
                
                elif parts[0] == 'printBalance':
                    self.print_balances()
                
                elif parts[0] == 'sync':
                    print(f"[Node {self.node_id}] Manually syncing with peers...")
                    self.manual_sync_with_peers()
                
                else:
                    print("Unknown command")
            
            except EOFError:
                break
            except Exception as e:
                print(f"Error: {e}")
        
        print(f"[Node {self.node_id}] Shutting down...")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python node.py <node_id> <config_file>")
        sys.exit(1)
    
    node_id = int(sys.argv[1])
    config_file = sys.argv[2]
    
    node = PaxosNode(node_id, 5000 + node_id, config_file)
    node.run()