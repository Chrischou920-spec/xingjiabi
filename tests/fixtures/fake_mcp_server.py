import json
import sys
import threading
import time


write_lock = threading.Lock()


def reply(message, result):
    with write_lock:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}) + "\n")
        sys.stdout.flush()


def delayed_reply(message, result):
    time.sleep(message["params"]["arguments"].get("delay", 0.15))
    reply(message, result)


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1"},
        }
    elif method == "tools/call":
        result = {
            "content": [{"type": "text", "text": json.dumps(message["params"]["arguments"])}],
            "isError": False,
        }
    else:
        continue
    if method == "tools/call" and message["params"]["name"] == "slow":
        threading.Thread(target=delayed_reply, args=(message, result), daemon=True).start()
    else:
        reply(message, result)
