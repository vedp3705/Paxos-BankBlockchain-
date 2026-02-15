.PHONY: clean kill

kill:
	@-pkill -f "python.*node.py" 2>/dev/null || true
	@-lsof -ti:5001-5005 2>/dev/null | xargs kill -9 2>/dev/null || true
	@sleep 1

clean: kill
	@rm -f node_*_blockchain.json node_*_balances.json
	@rm -f test_results.txt