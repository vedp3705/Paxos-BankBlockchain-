import hashlib

sender = 4  
receiver = 5
amount = 10
nonce = "lZtWpkz0xWWc6Raz"  
prev_hash = "5d9caa4238d82dd8695b27b48ad98b3911b0ccbe555211639cfd01aac9b4bf41"  

content = f"{sender}|{receiver}|{amount}|{nonce}|{prev_hash}"
hash_result = hashlib.sha256(content.encode()).hexdigest()
print(hash_result)
print(f"Last character: {hash_result[-1]}")

